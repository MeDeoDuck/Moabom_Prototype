"""
Sync API route - synchronize YouTube data for products
Uses comment_filtering_agent for advanced comment processing
"""
from fastapi import HTTPException
from scripts.database.queries import query_one, query_all, execute_update, execute_insert
from scripts.database.connection import get_connection
from scripts.youtube.video_service import fetch_product_videos
from scripts.youtube.comment_service import fetch_video_comments  # Fallback용 항상 import
from scripts.config import YOUTUBE_API_KEY, GROQ_API_KEY, DATABASE_URL  # 항상 import
from scripts.analysis.confidence_weights import (
    get_analysis_weight,
    LOW_CONFIDENCE_WARNING_THRESHOLD,
)
import uuid
import random
import re
from datetime import datetime
from typing import Dict, List
import psycopg2
from psycopg2.extras import RealDictCursor

# Import comment filtering agent
try:
    from comment_filtering_agent.services.comment_collector import YouTubeCommentCollector
    from comment_filtering_agent.filters.rule_based_filter import RuleBasedFilter
    from comment_filtering_agent.classifiers.optimized_batch_classifier import OptimizedBatchClassifier
    from comment_filtering_agent.core.agent import AgentDecisionEngine
    from comment_filtering_agent.core.models import AgentAction
    from comment_filtering_agent.analyzers.groq_analyzer import GroqAspectSentimentAnalyzer
    AGENT_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Comment filtering agent not available: {e}")
    AGENT_AVAILABLE = False


DAILY_TOKEN_BUDGET = 60000
TOKEN_BUDGET_PER_VIDEO = 2000
MAX_COMMENT_CHARS = 140
MAX_LLM_COMMENTS = 20
CLASSIFICATION_BATCH_SIZE = 8
RAW_COMMENT_FETCH_LIMIT = 1000
PREPROCESS_CANDIDATE_MIN = 250
PREPROCESS_CANDIDATE_MAX = 300
TOP_PER_SOURCE = 30


def _normalize_comment_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.lower()
    cleaned = re.sub(r"[^0-9a-zA-Z가-힣\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _deduplicate_comments(raw_comments):
    seen = set()
    deduped = []
    for c in raw_comments:
        normalized = _normalize_comment_text(c.text_original)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        c.text_original = normalized
        deduped.append(c)
    return deduped


def _spark_preprocess_comments(raw_comments, video_id: str):
    """
    Spark-first preprocessing (with safe Python fallback):
    1) Remove only technical invalid rows (null/blank)
    2) Drop exact duplicates by (video_id, author, text)
    3) Keep text with trim-only normalization
    4) Attach flags for downstream scoring/LLM reference (no hard-drop by flags)
    """
    base_rows: List[Dict] = []
    for c in raw_comments:
        base_rows.append({
            "comment_id": c.comment_id,
            "video_id": video_id,
            "author": c.author_name or "",
            "author_channel_id": c.author_channel_id or "",
            "text": c.text_original,
            "like_count": c.like_count or 0,
            "reply_count": c.reply_count or 0,
            "published_at": c.published_at,
            "is_reply": c.is_reply,
            "parent_comment_id": c.parent_comment_id,
        })

    if not base_rows:
        return [], {"input_count": 0, "output_count": 0, "removed_null_blank": 0, "removed_duplicates": 0}

    # Try Spark path first
    try:
        from pyspark.sql import SparkSession, functions as F

        spark = SparkSession.builder.master("local[*]").appName("comment-preprocess").getOrCreate()
        df = spark.createDataFrame(base_rows)

        input_count = df.count()
        valid_df = (
            df
            .filter(F.col("text").isNotNull())
            .filter(F.trim(F.col("text")) != "")
        )
        valid_count = valid_df.count()

        dedup_df = valid_df.dropDuplicates(["video_id", "author", "text"])
        output_count = dedup_df.count()

        processed_df = (
            dedup_df
            .withColumn("text_cleaned", F.trim(F.col("text")))
            .withColumn("char_count", F.length(F.col("text_cleaned")))
            .withColumn("is_short", F.length(F.col("text_cleaned")) < 5)
            .withColumn("has_url", F.col("text_cleaned").rlike(r"https?://|www\\."))
            .withColumn("is_repetitive", F.col("text_cleaned").rlike(r"^(.)\\1{9,}$"))
        )

        rows = [r.asDict(recursive=True) for r in processed_df.collect()]
        spark.stop()
        return rows, {
            "input_count": input_count,
            "output_count": output_count,
            "removed_null_blank": max(0, input_count - valid_count),
            "removed_duplicates": max(0, valid_count - output_count),
        }
    except Exception:
        # Fallback: same semantics in Python
        valid_rows = []
        for r in base_rows:
            text = r.get("text")
            if text is None:
                continue
            if not str(text).strip():
                continue
            valid_rows.append(r)

        seen = set()
        dedup_rows = []
        for r in valid_rows:
            key = (r["video_id"], r["author"], r["text"])
            if key in seen:
                continue
            seen.add(key)
            dedup_rows.append(r)

        for r in dedup_rows:
            cleaned = str(r["text"]).strip()
            r["text_cleaned"] = cleaned
            r["char_count"] = len(cleaned)
            r["is_short"] = len(cleaned) < 5
            r["has_url"] = bool(re.search(r"https?://|www\.", cleaned))
            r["is_repetitive"] = bool(re.match(r"^(.)\1{9,}$", cleaned))

        return dedup_rows, {
            "input_count": len(base_rows),
            "output_count": len(dedup_rows),
            "removed_null_blank": max(0, len(base_rows) - len(valid_rows)),
            "removed_duplicates": max(0, len(valid_rows) - len(dedup_rows)),
        }


def _keyword_hit_count(comment_text: str, product_name: str) -> int:
    text = _normalize_comment_text(comment_text)
    common_keywords = ["좋다", "나쁘다", "발열", "배터리", "성능", "디자인", "가격", "추천", "실망"]
    product_tokens = [t for t in _normalize_comment_text(product_name).split() if t]
    return sum(1 for kw in (common_keywords + product_tokens) if kw and kw in text)


def _to_timestamp(value) -> float:
    if not value:
        return 0.0
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _normalize_feature(value: float, min_value: float, max_value: float) -> float:
    if max_value <= min_value:
        return 0.0
    return (value - min_value) / (max_value - min_value)


def _select_comments_multicriteria(comment_items, product_name: str):
    if not comment_items:
        return [], {
            "entry_count": 0,
            "primary_pool_count": 0,
            "secondary_pool_count": 0,
            "primary_selected_count": 0,
            "secondary_selected_count": 0,
        }

    per_source = min(TOP_PER_SOURCE, len(comment_items))
    by_like = sorted(comment_items, key=lambda x: (x["like_count"], x["reply_count"]), reverse=True)[:per_source]
    by_reply = sorted(comment_items, key=lambda x: (x["reply_count"], x["like_count"]), reverse=True)[:per_source]
    by_length = sorted(comment_items, key=lambda x: len(x["comment_text"]), reverse=True)[:per_source]
    by_new = sorted(comment_items, key=lambda x: x["published_ts"], reverse=True)[:per_source]
    by_old = sorted(comment_items, key=lambda x: x["published_ts"])[:per_source]
    by_random = random.sample(comment_items, k=per_source)

    source_groups = {
        "like": by_like,
        "many": by_reply,
        "long": by_length,
        "new": by_new,
        "old": by_old,
        "random": by_random,
    }

    meta = {}
    for source_name, group in source_groups.items():
        for item in group:
            cid = item["comment_id"]
            if cid not in meta:
                meta[cid] = {"item": item, "sources": set()}
            meta[cid]["sources"].add(source_name)

    entries = []
    for v in meta.values():
        item = v["item"]
        sources = v["sources"]
        entries.append({
            "item": item,
            "hit_count": len(sources),
            "sources": sorted(sources),
            "secondary_score": 0.0,
        })

    primary = [e for e in entries if e["hit_count"] >= 2]
    primary.sort(
        key=lambda e: (
            e["hit_count"],
            e["item"]["like_count"],
            e["item"]["reply_count"],
            len(e["item"]["comment_text"])
        ),
        reverse=True
    )

    secondary_pool = [e for e in entries if e["hit_count"] == 1]

    if len(primary) >= MAX_LLM_COMMENTS:
        selected = primary[:MAX_LLM_COMMENTS]
        return selected, {
            "entry_count": len(entries),
            "primary_pool_count": len(primary),
            "secondary_pool_count": len(secondary_pool),
            "primary_selected_count": len(selected),
            "secondary_selected_count": 0,
        }

    if secondary_pool:
        likes = [e["item"]["like_count"] for e in secondary_pool]
        replies = [e["item"]["reply_count"] for e in secondary_pool]
        min_like, max_like = min(likes), max(likes)
        min_reply, max_reply = min(replies), max(replies)

        for e in secondary_pool:
            item = e["item"]
            normalized_like = _normalize_feature(item["like_count"], min_like, max_like)
            normalized_reply = _normalize_feature(item["reply_count"], min_reply, max_reply)
            keyword_hits = _keyword_hit_count(item["comment_text"], product_name)
            e["secondary_score"] = normalized_like + normalized_reply + keyword_hits

        secondary_pool.sort(
            key=lambda e: (e["secondary_score"], len(e["item"]["comment_text"])),
            reverse=True
        )

    needed = MAX_LLM_COMMENTS - len(primary)
    selected = primary + secondary_pool[:max(0, needed)]
    selected = selected[:MAX_LLM_COMMENTS]
    return selected, {
        "entry_count": len(entries),
        "primary_pool_count": len(primary),
        "secondary_pool_count": len(secondary_pool),
        "primary_selected_count": sum(1 for e in selected if e["hit_count"] >= 2),
        "secondary_selected_count": sum(1 for e in selected if e["hit_count"] == 1),
    }


def _preprocess_candidate_pool(comment_items, product_name: str):
    """Hard-preprocess candidates (noise/short/rejected already removed) and cap pool size."""
    if not comment_items:
        return [], {"input_count": 0, "output_count": 0, "trimmed_count": 0}

    scored = []
    for item in comment_items:
        text = item["comment_text"]
        engagement = float(item["like_count"]) + (0.7 * float(item["reply_count"]))
        keyword_hits = _keyword_hit_count(text, product_name)
        length_score = min(len(text), MAX_COMMENT_CHARS) / float(MAX_COMMENT_CHARS)
        score = engagement + (2.0 * keyword_hits) + length_score
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [item for _, item in scored[:PREPROCESS_CANDIDATE_MAX]]
    top_preview = [
        {
            "comment_id": item["comment_id"],
            "score": round(score, 3),
            "likes": item["like_count"],
            "replies": item["reply_count"],
            "keyword_hits": _keyword_hit_count(item["comment_text"], product_name),
        }
        for score, item in scored[:5]
    ]
    return selected, {
        "input_count": len(comment_items),
        "output_count": len(selected),
        "trimmed_count": max(0, len(comment_items) - len(selected)),
        "top_preview": top_preview,
    }


def process_comments_with_agent(video_id, product_name):
    """
    Process comments using the comment filtering agent pipeline.
    Returns statistics about processed comments.
    """
    if not AGENT_AVAILABLE:
        raise Exception("Comment filtering agent is not available")
    
    if not GROQ_API_KEY or not YOUTUBE_API_KEY:
        raise Exception("Missing API keys (YOUTUBE_API_KEY or GROQ_API_KEY)")
    
    print(f"[AGENT] Starting comment processing for video: {video_id}")
    batch_id = str(uuid.uuid4())
    
    # Initialize components
    collector = YouTubeCommentCollector(api_key=YOUTUBE_API_KEY)
    rule_filter = RuleBasedFilter()
    
    # Optimized batch classifier + analyzer config
    from comment_filtering_agent.analyzers.models import AnalyzerConfig
    classifier = OptimizedBatchClassifier(
        api_key=GROQ_API_KEY,
        batch_size=CLASSIFICATION_BATCH_SIZE,
        confidence_threshold=0.75
    )
    
    agent = AgentDecisionEngine()
    
    analyzer_config = AnalyzerConfig()
    analyzer_config.model_name = "llama-3.3-70b-versatile"
    sentiment_analyzer = GroqAspectSentimentAnalyzer(api_key=GROQ_API_KEY, config=analyzer_config)
    
    stats = {
        "collected": 0,
        "rule_passed": 0,
        "rule_rejected": 0,
        "selected_pre_llm": 0,
        "selected_post_llm": 0,
        "analyzed": 0,
        "excluded": 0,
        "errors": 0
    }
    deduped_count = 0
    preprocessed_count = 0
    selected_before_budget_count = 0
    selected_after_budget_count = 0
    classified_count = 0
    low_confidence_analyzed_count = 0
    
    try:
        # Step 1: Collect comments from YouTube
        print(f"[AGENT] Step 1: Collecting comments (target={RAW_COMMENT_FETCH_LIMIT})...")
        raw_comments = collector.collect_comments(video_id, max_results=RAW_COMMENT_FETCH_LIMIT)
        stats["collected"] = len(raw_comments)
        print(f"[AGENT] Step 1 result: collected_count={len(raw_comments)}")

        if not raw_comments:
            return stats

        # Spark-style preprocessing: technical cleanup + dedup + flags
        print("[AGENT] Step 2: Spark preprocess (technical cleanup + dedup + flags)...")
        spark_rows, spark_diag = _spark_preprocess_comments(raw_comments, video_id)
        deduped_count = len(spark_rows)
        print(
            "[AGENT] Spark preprocess summary: "
            f"input={spark_diag['input_count']}, output={spark_diag['output_count']}, "
            f"removed_null_blank={spark_diag['removed_null_blank']}, "
            f"removed_duplicates={spark_diag['removed_duplicates']}"
        )
        print(f"[AGENT] Step 2 result: preprocessed_count={len(spark_rows)}")
        
        # Step 3: Save comments + rule filtering
        print("[AGENT] Step 3: Persisting comments + rule filter (PASS/REJECT)...")
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        candidate_comments = []
        for row in spark_rows:
            try:
                comment_id = row["comment_id"]
                comment_text = row["text_cleaned"]
                
                # Save to comments table (기존 테이블)
                cur.execute("""
                    INSERT INTO comments (
                        comment_id, video_id, text_raw, 
                        author_name, author_channel_id,
                        like_count, reply_count, published_at,
                        collected_at, collection_batch_id, is_reply,
                        parent_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (comment_id) DO UPDATE SET
                        like_count = EXCLUDED.like_count,
                        reply_count = EXCLUDED.reply_count
                """, (
                    comment_id, video_id, comment_text,
                    row["author"], row["author_channel_id"],
                    row["like_count"], row["reply_count"],
                    row["published_at"], datetime.now(), batch_id,
                    row["is_reply"],
                    row["parent_comment_id"]  # 답글 관계 추가
                ))
                
                # Soft filtering: record PASS/REJECT, but keep all Spark-preprocessed rows as candidates
                filter_result = rule_filter.filter_single(comment_text)
                cur.execute("""
                    INSERT INTO rule_filter_results (
                        comment_id, filter_status, rejected_by_rule, 
                        reject_reason, filtered_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (comment_id) DO UPDATE SET
                        filter_status = EXCLUDED.filter_status,
                        rejected_by_rule = EXCLUDED.rejected_by_rule,
                        reject_reason = EXCLUDED.reject_reason,
                        filtered_at = EXCLUDED.filtered_at
                """, (
                    comment_id,
                    'PASS' if filter_result.is_passed else 'REJECT',
                    ','.join(filter_result.matched_rules) if filter_result.matched_rules else None,
                    ','.join([r.value for r in filter_result.reject_reason_codes]) if filter_result.reject_reason_codes else None,
                    datetime.now()
                ))
                if filter_result.is_passed:
                    stats["rule_passed"] += 1
                else:
                    stats["rule_rejected"] += 1

                candidate_comments.append({
                    "comment_id": comment_id,
                    "comment_text": comment_text[:MAX_COMMENT_CHARS],
                    "like_count": row["like_count"] or 0,
                    "reply_count": row["reply_count"] or 0,
                    "published_ts": _to_timestamp(row["published_at"]),
                    "filter_result": filter_result,
                    "spark_flags": {
                        "char_count": int(row.get("char_count", len(comment_text))),
                        "is_short": bool(row.get("is_short", False)),
                        "has_url": bool(row.get("has_url", False)),
                        "is_repetitive": bool(row.get("is_repetitive", False)),
                    }
                })
                conn.commit()
                
            except Exception as e:
                print(f"[AGENT] Error processing comment {row.get('comment_id')}: {e}")
                stats["errors"] += 1
                conn.rollback()
                import traceback
                traceback.print_exc()
                continue

        print(
            "[AGENT] Rule filter summary: "
            f"passed={stats['rule_passed']}, rejected={stats['rule_rejected']}, errors={stats['errors']}"
        )
        print(f"[AGENT] Step 3 result: candidate_count={len(candidate_comments)}")

        # Step 4: Multi-criteria extraction + overlap priority + token budget
        if candidate_comments:
            print("[AGENT] Step 4: Candidate preprocessing (score/rank cap)...")
            preprocessed_candidates, preprocess_diag = _preprocess_candidate_pool(candidate_comments, product_name)
            if preprocess_diag["output_count"] < PREPROCESS_CANDIDATE_MIN:
                print(
                    "[AGENT] Preprocess pool below recommended minimum: "
                    f"output={preprocess_diag['output_count']} < {PREPROCESS_CANDIDATE_MIN}"
                )
            print(
                "[AGENT] Preprocess summary: "
                f"input={preprocess_diag['input_count']}, "
                f"output={preprocess_diag['output_count']}, "
                f"trimmed={preprocess_diag['trimmed_count']}, "
                f"target_range={PREPROCESS_CANDIDATE_MIN}~{PREPROCESS_CANDIDATE_MAX}"
            )
            preprocessed_count = len(preprocessed_candidates)
            print(f"[AGENT] Step 4 result: preprocessed_count={len(preprocessed_candidates)}")
            if preprocess_diag.get("top_preview"):
                print(f"[AGENT] Preprocess top_preview: {preprocess_diag['top_preview']}")

            print(f"[AGENT] Step 5: Multi-criteria top-{TOP_PER_SOURCE} + overlap selection...")
            selected_meta, selection_diag = _select_comments_multicriteria(preprocessed_candidates, product_name)
            selected_items = [m["item"] for m in selected_meta]
            print(
                "[AGENT] Selection summary: "
                f"entries={selection_diag['entry_count']}, "
                f"primary_pool(hit>=2)={selection_diag['primary_pool_count']}, "
                f"secondary_pool(hit=1)={selection_diag['secondary_pool_count']}, "
                f"primary_selected={selection_diag['primary_selected_count']}, "
                f"secondary_selected={selection_diag['secondary_selected_count']}, "
                f"selected_total={len(selected_items)}"
            )
            selected_before_budget_count = len(selected_items)
            print(f"[AGENT] Step 5 result: selected_before_budget={len(selected_items)}")
            approx_tokens = sum(max(10, len(i["comment_text"]) // 3) for i in selected_items)
            if approx_tokens > TOKEN_BUDGET_PER_VIDEO:
                before_trim_count = len(selected_meta)
                selected_meta = sorted(
                    selected_meta,
                    key=lambda m: (
                        m["hit_count"],
                        m["secondary_score"],
                        m["item"]["like_count"],
                        m["item"]["reply_count"]
                    ),
                    reverse=True
                )
                while selected_meta and sum(max(10, len(m["item"]["comment_text"]) // 3) for m in selected_meta) > TOKEN_BUDGET_PER_VIDEO:
                    selected_meta.pop()
                selected_items = [m["item"] for m in selected_meta]
                after_trim_count = len(selected_meta)
                print(
                    "[AGENT] Token budget trim: "
                    f"before={before_trim_count}, after={after_trim_count}, "
                    f"trimmed={before_trim_count - after_trim_count}, "
                    f"budget={TOKEN_BUDGET_PER_VIDEO}"
                )
                selected_after_budget_count = len(selected_items)
                print(f"[AGENT] Step 5.5 result: selected_after_budget={len(selected_items)}")
            else:
                print(
                    "[AGENT] Token budget trim: "
                    f"before={len(selected_meta)}, after={len(selected_meta)}, "
                    f"trimmed=0, budget={TOKEN_BUDGET_PER_VIDEO}"
                )
                selected_after_budget_count = len(selected_items)
                print(f"[AGENT] Step 5.5 result: selected_after_budget={len(selected_items)}")

            if not selected_items:
                print("[AGENT] No comments selected after token budget check")
                return stats

            stats["selected_pre_llm"] = len(selected_items)
            print(f"[AGENT] Step 6: LLM batch classification (count={len(selected_items)})...")
            print(f"[AGENT] Selected comments detail ({len(selected_meta)}):")
            for rank, meta in enumerate(selected_meta, start=1):
                item = meta["item"]
                preview = (item["comment_text"][:60] + "...") if len(item["comment_text"]) > 60 else item["comment_text"]
                print(
                    f"[AGENT]   #{rank:02d} "
                    f"comment_id={item['comment_id']} "
                    f"hit_count={meta['hit_count']} "
                    f"sources={','.join(meta['sources'])} "
                    f"secondary_score={meta['secondary_score']:.3f} "
                    f"likes={item['like_count']} replies={item['reply_count']} "
                    f"text='{preview}'"
                )

            classification_results = classifier.classify_batch(
                [c["comment_text"] for c in selected_items],
                start_index=0
            )
            if len(classification_results) != len(selected_items):
                raise Exception(
                    f"Batch classification result size mismatch: "
                    f"{len(classification_results)} != {len(selected_items)}"
                )
            print(f"[AGENT] Classification summary: results={len(classification_results)}")
            classified_count = len(classification_results)
            print(f"[AGENT] Step 6 result: classified_count={len(classification_results)}")

            # Step 5/6: Agent decision + sentiment/aspect
            print("[AGENT] Step 7: Agent decision + sentiment/aspect persistence...")
            for i, item in enumerate(selected_items):
                try:
                    comment_id = item["comment_id"]
                    comment_text = item["comment_text"]
                    filter_result = item["filter_result"]
                    classification = classification_results[i]

                    cur.execute("""
                        INSERT INTO llm_classifications (
                            comment_id, predicted_label, confidence_score,
                            model_name, reasoning, classified_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (comment_id) DO UPDATE SET
                            predicted_label = EXCLUDED.predicted_label,
                            confidence_score = EXCLUDED.confidence_score,
                            model_name = EXCLUDED.model_name,
                            reasoning = EXCLUDED.reasoning,
                            classified_at = EXCLUDED.classified_at
                    """, (
                        comment_id,
                        classification.label.value,
                        float(classification.confidence),
                        classification.model_name,
                        classification.rationale_short,
                        datetime.now()
                    ))

                    decision = agent.decide(
                        comment=comment_text,
                        filter_result=filter_result,
                        classification_result=classification,
                        index=i
                    )

                    cur.execute("""
                        INSERT INTO agent_decisions (
                            comment_id, final_action, exclusion_reason,
                            exclusion_details, decision_reasoning,
                            needs_human_review, agent_version, decided_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (comment_id) DO UPDATE SET
                            final_action = EXCLUDED.final_action,
                            exclusion_reason = EXCLUDED.exclusion_reason,
                            exclusion_details = EXCLUDED.exclusion_details,
                            decision_reasoning = EXCLUDED.decision_reasoning,
                            needs_human_review = EXCLUDED.needs_human_review,
                            agent_version = EXCLUDED.agent_version,
                            decided_at = EXCLUDED.decided_at
                    """, (
                        comment_id,
                        decision.final_action.value,
                        decision.exclusion_reason.value if decision.exclusion_reason else None,
                        decision.exclusion_details,
                        decision.decision_reasoning,
                        decision.needs_human_review,
                        decision.agent_version,
                        datetime.now()
                    ))

                    if decision.final_action == AgentAction.ANALYZE:
                        sentiment_result = sentiment_analyzer.analyze_single(comment_text)
                        sentiment_map = {"POSITIVE": "positive", "NEUTRAL": "neutral", "NEGATIVE": "negative"}
                        sentiment_label = sentiment_map.get(sentiment_result.overall_sentiment.value, "neutral")
                        analysis_weight = get_analysis_weight(bool(decision.is_low_confidence))
                        if decision.is_low_confidence:
                            low_confidence_analyzed_count += 1

                        cur.execute("""
                            INSERT INTO comment_sentiments (
                                comment_id, sentiment_label, sentiment_score, analysis_weight, created_at
                            ) VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (comment_id) DO UPDATE SET
                                sentiment_label = EXCLUDED.sentiment_label,
                                sentiment_score = EXCLUDED.sentiment_score,
                                analysis_weight = EXCLUDED.analysis_weight
                        """, (
                            comment_id,
                            sentiment_label,
                            float(sentiment_result.overall_score),
                            float(analysis_weight),
                            datetime.now()
                        ))

                        if sentiment_result.aspects:
                            for aspect in sentiment_result.aspects:
                                aspect_sentiment_map = {"POSITIVE": "POSITIVE", "NEUTRAL": "NEUTRAL", "NEGATIVE": "NEGATIVE"}
                                cur.execute("""
                                    INSERT INTO aspect_extractions (
                                        comment_id, aspect_name, mention_text,
                                        aspect_sentiment, aspect_sentiment_score,
                                        extraction_confidence, extracted_at
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                """, (
                                    comment_id,
                                    aspect.aspect,
                                    aspect.mention_text,
                                    aspect_sentiment_map.get(aspect.sentiment.value, "NEUTRAL"),
                                    float(aspect.score) if aspect.score else None,
                                    None,
                                    datetime.now()
                                ))
                        stats["analyzed"] += 1
                    else:
                        stats["excluded"] += 1

                    conn.commit()
                except Exception as e:
                    print(f"[AGENT] Error processing classified comment {item['comment_id']}: {e}")
                    stats["errors"] += 1
                    conn.rollback()
                    import traceback
                    traceback.print_exc()
                    continue
            stats["selected_post_llm"] = stats["analyzed"]
            print(
                "[AGENT] Step 7 summary: "
                f"analyzed={stats['analyzed']}, excluded={stats['excluded']}, errors={stats['errors']}"
            )
            print(
                "[AGENT] Step 7 result: "
                f"final_analyzed_count={stats['analyzed']}, final_excluded_count={stats['excluded']}"
            )
            if stats["analyzed"] > 0:
                low_conf_ratio = low_confidence_analyzed_count / stats["analyzed"]
                level = "WARN" if low_conf_ratio > LOW_CONFIDENCE_WARNING_THRESHOLD else "INFO"
                print(
                    f"[{level}] Low-confidence analyzed ratio: "
                    f"{low_confidence_analyzed_count}/{stats['analyzed']} ({low_conf_ratio:.2%})"
                )

        print(
            "[AGENT] FINAL FUNNEL SUMMARY: "
            f"collected={stats['collected']} -> "
            f"deduped={deduped_count} -> "
            f"rule_pass={stats['rule_passed']} -> "
            f"preprocessed={preprocessed_count} -> "
            f"selected_before_budget={selected_before_budget_count} -> "
            f"selected_after_budget={selected_after_budget_count} -> "
            f"classified={classified_count} -> "
            f"analyzed={stats['analyzed']} / excluded={stats['excluded']} / errors={stats['errors']}"
        )
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"[AGENT] Processing complete. Stats: {stats}")
        return stats
        
    except Exception as e:
        print(f"[AGENT] Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        raise


def register_sync_routes(app):
    """Register sync-related routes"""
    
    @app.post("/products/{product_id}/sync")
    async def sync_product_videos(product_id: int, data: dict = None):
        """Sync videos and comments from YouTube for a product."""
        print(f"[SYNC] START: product_id={product_id}")
        
        try:
            product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
            print(f"[SYNC] Product query OK: {product}")
            
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            
            max_results = (data or {}).get("max_results", 5)
            print(f"[SYNC] max_results={max_results}")
            
            # DELETE all existing data for this product (clean slate approach)
            execute_update(
                """DELETE FROM comment_sentiments
                   WHERE comment_id IN (
                     SELECT c.comment_id FROM comments c
                     INNER JOIN videos v ON c.video_id = v.video_id
                     WHERE v.product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted comment_sentiments")
            
            execute_update(
                """DELETE FROM comments
                   WHERE video_id IN (
                     SELECT video_id FROM videos WHERE product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted comments")
            
            execute_update(
                """DELETE FROM video_transcripts
                   WHERE video_id IN (
                     SELECT video_id FROM videos WHERE product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted video_transcripts")
            
            execute_update(
                """DELETE FROM video_reports
                   WHERE video_id IN (
                     SELECT video_id FROM videos WHERE product_id = %s
                   )""",
                (product_id,)
            )
            print(f"[SYNC] Deleted video_reports")
            
            execute_update(
                "DELETE FROM videos WHERE product_id = %s",
                (product_id,)
            )
            print(f"[SYNC] Deleted videos")
            
            # Fetch videos from YouTube
            print(f"[SYNC] Fetching videos for '{product['name']}'...")
            videos = fetch_product_videos(product["name"], max_results=5)
            print(f"[SYNC] Got {len(videos)} videos from YouTube")
            
            videos_count = 0
            comments_count = 0
            transcripts_count = 0
            llm_selected_pre_count = 0
            llm_selected_post_count = 0
            
            for video in videos:
                print(f"[SYNC] Processing video: {video['video_id']}")
                
                # INSERT new video
                execute_update(
                    """INSERT INTO videos (video_id, product_id, title, description, published_at,
                       thumbnail_url, view_count, like_count, comment_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (video["video_id"], product_id, video["title"], video["description"],
                     video["published_at"], video["thumbnail_url"], video["view_count"],
                     video["like_count"], video["comment_count"])
                )
                videos_count += 1
                print(f"[SYNC]   Video inserted")
                
                # Fetch and process comments with Agent
                print(f"[SYNC]   Processing comments with Agent...")
                if AGENT_AVAILABLE:
                    try:
                        comment_stats = process_comments_with_agent(video["video_id"], product["name"])
                        comments_count += comment_stats.get("collected", 0)
                        llm_selected_pre_count += comment_stats.get("selected_pre_llm", 0)
                        llm_selected_post_count += comment_stats.get("selected_post_llm", 0)
                        print(f"[SYNC]   Agent stats: {comment_stats}")
                    except Exception as e:
                        print(f"[SYNC]   Agent processing failed: {e}, falling back to simple collection")
                        # Fallback to simple comment collection
                        comments = fetch_video_comments(video["video_id"], max_pages=2)
                        for comment in comments:
                            execute_update(
                                """INSERT INTO comments (comment_id, video_id, text_raw, is_product_related)
                                   VALUES (%s, %s, %s, %s)
                                   ON CONFLICT (comment_id) DO UPDATE SET
                                       video_id = EXCLUDED.video_id,
                                       text_raw = EXCLUDED.text_raw,
                                       is_product_related = EXCLUDED.is_product_related""",
                                (comment["comment_id"], video["video_id"], comment["text_raw"], True)
                            )
                            comments_count += 1
                else:
                    # Fallback: Use old comment collection
                    print(f"[SYNC]   Using fallback comment collection...")
                    comments = fetch_video_comments(video["video_id"], max_pages=2)
                    print(f"[SYNC]   Got {len(comments)} comments")
                    
                    for comment in comments:
                        # Insert raw comment
                        execute_update(
                            """INSERT INTO comments (comment_id, video_id, text_raw, is_product_related)
                               VALUES (%s, %s, %s, %s)
                               ON CONFLICT (comment_id) DO UPDATE SET
                                   video_id = EXCLUDED.video_id,
                                   text_raw = EXCLUDED.text_raw,
                                   is_product_related = EXCLUDED.is_product_related""",
                            (comment["comment_id"], video["video_id"], comment["text_raw"], True)
                        )
                        comments_count += 1
                        
                        # Simple sentiment analysis
                        comment_text = comment["text_raw"].lower()
                        positive_keywords = {
                            "좋다", "훌륭", "추천", "완벽", "최고", "멋진", "빠르다", "빠른", "강력", "강력한",
                            "좋은", "좋습니다", "훌륭합니다", "amazing", "great", "excellent", "awesome",
                            "best", "love", "perfect", "worth", "impressed", "beautiful", "fast", "powerful"
                        }
                        
                        negative_keywords = {
                            "나쁘다", "문제", "느리다", "느린", "비싸다", "비싼", "약하다", "약한", "못쓸",
                            "망했", "실망", "후회", "환불", "bad", "terrible", "poor", "awful", "slow",
                            "expensive", "waste", "regret", "disappointing", "broken", "fragile"
                        }
                        
                        pos_count = sum(1 for kw in positive_keywords if kw in comment_text)
                        neg_count = sum(1 for kw in negative_keywords if kw in comment_text)
                        
                        if pos_count > neg_count:
                            sentiment_label = "positive"
                            sentiment_score = 0.7
                        elif neg_count > pos_count:
                            sentiment_label = "negative"
                            sentiment_score = 0.3
                        else:
                            sentiment_label = "neutral"
                            sentiment_score = 0.5
                        
                        # Save sentiment to DB
                        try:
                            conn = get_connection()
                            cur = conn.cursor()
                            cur.execute("DELETE FROM comment_sentiments WHERE comment_id = %s", (comment["comment_id"],))
                            cur.execute("""
                                INSERT INTO comment_sentiments (comment_id, sentiment_label, sentiment_score, analysis_weight, created_at)
                                VALUES (%s, %s, %s, %s, NOW())
                            """, (comment["comment_id"], sentiment_label, sentiment_score, 1.0))
                            conn.commit()
                            cur.close()
                            conn.close()
                        except Exception as e:
                            print(f"[SYNC] Warning: Could not save sentiment for {comment['comment_id']}: {e}")

                # Transcripts will be fetched on-demand when user views the video page
                print(f"[SYNC]   Skipping transcript (will fetch on-demand when viewing video)")
            
            print(
                f"[SYNC] COMPLETE: videos={videos_count}, comments={comments_count}, transcripts={transcripts_count}, "
                f"llm_selected_pre={llm_selected_pre_count}, llm_selected_post={llm_selected_post_count}"
            )
            return {
                "status": "success",
                "videos_count": videos_count,
                "comments_count": comments_count,
                "transcripts_count": transcripts_count,
                "llm_selected_pre_count": llm_selected_pre_count,
                "llm_selected_post_count": llm_selected_post_count,
            }
        except Exception as e:
            print(f"[SYNC] ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise
