"""llm_final_select + verifier (설계 §4 [9], PR3 LLM#2).

- LLM#2: shortlist 각 후보를 자막 기반으로 {fit, depth, risk, reason}(CoT) 평가.
- 코드 verifier: LLM 점수 + coverage bonus 로 **정책 만족 조합**을 결정적으로 선택.
  LLM 에 최종 선택을 통째로 넘기지 않는다(비결정성·정책 미준수 위험) — "LLM 품질
  판단, 코드 조합 최적화"(설계 §2).

정책(설계 §4 [9]): scope 영상 0 · mega ≤ ⌈k·0.4⌉ · 채널당 ≤ max_per_channel ·
non-mega ≥ 1 · small/micro upper cap · k=5. coverage bonus 로 클러스터 다양성 유도.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

_DESC_TRUNC = 400
_TRANSCRIPT_TRUNC = 4000

_SYSTEM = (
    "당신은 단일 제품 유튜브 리뷰 영상을 최종 선별하는 전문가입니다. 각 후보(자막 또는 "
    "제목+설명 제공)에 대해 다음을 0~1로 평가하고 한국어 이유를 쓰세요: "
    "fit(제품 리뷰로서의 적합성), depth(분석 깊이·구체성), risk(과장/홍보/부정확 위험; "
    "높을수록 나쁨). 단계적으로 근거를 들어 판단하되 최종 출력은 각 후보의 점수와 "
    "한 줄 이유입니다. 반드시 입력의 video_id 만 사용하세요."
)

_SCHEMA = {
    "name": "final_judgments",
    "schema": {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "video_id": {"type": "string"},
                        "fit": {"type": "number"},
                        "depth": {"type": "number"},
                        "risk": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["video_id", "fit", "depth", "risk", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["judgments"],
        "additionalProperties": False,
    },
    "strict": True,
}


def llm_final_select(candidates: list[dict], transcripts: dict[str, str]) -> tuple[dict[str, dict], dict]:
    """shortlist 후보별 LLM 판단 → {video_id: {fit, depth, risk, reason}}.

    candidates: [{video_id, title, description, ...}] (shortlist)
    transcripts: {video_id: sampled_text} (없으면 제목+설명 fallback)
    반환: (judgments_by_id, meta). LLM 실패 시 빈 dict + meta["error"].
    """
    meta = {"n": len(candidates), "with_transcript": 0}
    if not candidates:
        return {}, meta

    payload = []
    valid_ids = set()
    for c in candidates:
        vid = c["video_id"]
        valid_ids.add(vid)
        tx = transcripts.get(vid)
        if tx:
            meta["with_transcript"] += 1
            body = {"video_id": vid, "title": c.get("title", ""), "transcript": tx[:_TRANSCRIPT_TRUNC]}
        else:
            body = {
                "video_id": vid,
                "title": c.get("title", ""),
                "description": (c.get("description", "") or "")[:_DESC_TRUNC],
            }
        payload.append(body)

    try:
        from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient

        data = AzureOpenAIClient().chat_structured(
            system=_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            json_schema=_SCHEMA,
            max_tokens=3000,
            temperature=0.0,
        )
    except Exception as e:
        meta["error"] = f"final_select llm failed: {e}"
        print(f"[final_select] {meta['error']}", flush=True)
        return {}, meta

    out: dict[str, dict] = {}
    for j in data.get("judgments", []):
        vid = j.get("video_id", "")
        if vid not in valid_ids:  # 환각 차단
            continue
        out[vid] = {
            "fit": max(0.0, min(1.0, float(j.get("fit", 0.0)))),
            "depth": max(0.0, min(1.0, float(j.get("depth", 0.0)))),
            "risk": max(0.0, min(1.0, float(j.get("risk", 0.0)))),
            "reason": (j.get("reason", "") or "")[:300],
        }
    return out, meta


@dataclass
class VerifyPolicy:
    """설계 §4 [9] 정책 파라미터."""
    k: int = 5
    max_per_channel: int = 2
    coverage_alpha: float = 0.15      # 새 클러스터 가점
    non_mega_min: int = 1
    # mega_cap = ⌈k·0.4⌉, small/micro cap = ⌈k·0.6⌉ 는 k 로부터 파생
    mega_ratio: float = 0.4
    small_below_ratio: float = 0.6

    def mega_cap(self) -> int:
        return math.ceil(self.k * self.mega_ratio)

    def small_below_cap(self) -> int:
        return math.ceil(self.k * self.small_below_ratio)


def _candidate_score(c: dict) -> float:
    """LLM 판단 → 단일 품질 점수. fit 주도, depth 가점, risk 감점."""
    return c.get("fit", 0.0) + 0.3 * c.get("depth", 0.0) - 0.3 * c.get("risk", 0.0)


def verify_and_select(
    candidates: list[dict],
    policy: VerifyPolicy | None = None,
) -> dict:
    """LLM 판단이 달린 후보 → 정책 만족 k개 조합을 결정적으로 선택.

    candidates: [{video_id, cluster_id, tier, channel_id, scope_label,
                  fit, depth, risk, reason}, ...]
    반환: {selected:[video_id...], detail:[{video_id, score, cluster_id, tier}],
           fallback:bool, violations:[...], stats:{...}}
    """
    policy = policy or VerifyPolicy()
    k = policy.k

    # 1) scope 영상(비교/랭킹) 하드 제외
    pool = [c for c in candidates if int(c.get("scope_label", 0) or 0) != 1]
    scope_excluded = len(candidates) - len(pool)

    # 2) 품질 점수순 정렬 (안정적: 점수 desc, video_id asc 로 tie-break → 결정적)
    ranked = sorted(pool, key=lambda c: (-_candidate_score(c), str(c.get("video_id", ""))))

    selected: list[dict] = []
    per_channel: dict[str, int] = {}
    covered_clusters: set = set()
    mega_count = 0
    small_below_count = 0
    violations: list[str] = []

    def _can_add(c: dict) -> bool:
        ch = c.get("channel_id", "")
        if per_channel.get(ch, 0) >= policy.max_per_channel:
            return False
        tier = c.get("tier", "")
        if tier == "mega" and mega_count >= policy.mega_cap():
            return False
        if tier in ("small", "micro") and small_below_count >= policy.small_below_cap():
            return False
        return True

    # 3) 그리디: 점수 + coverage bonus (새 클러스터 가점) 로 k개까지
    remaining = list(ranked)
    while len(selected) < k and remaining:
        best = None
        best_val = None
        for c in remaining:
            if not _can_add(c):
                continue
            bonus = policy.coverage_alpha if c.get("cluster_id") not in covered_clusters else 0.0
            val = _candidate_score(c) + bonus
            if best_val is None or val > best_val:
                best, best_val = c, val
        if best is None:  # 캡 때문에 더 못 넣음
            break
        selected.append(best)
        remaining.remove(best)
        ch = best.get("channel_id", "")
        per_channel[ch] = per_channel.get(ch, 0) + 1
        covered_clusters.add(best.get("cluster_id"))
        if best.get("tier") == "mega":
            mega_count += 1
        if best.get("tier") in ("small", "micro"):
            small_below_count += 1

    # 4) non-mega floor: 전부 mega 면 최저점 mega ↔ 최고점 non-mega 교체
    if selected and all(c.get("tier") == "mega" for c in selected):
        non_mega = [c for c in remaining if c.get("tier") != "mega"]
        if non_mega:
            worst_mega = min(selected, key=_candidate_score)
            best_non = max(non_mega, key=_candidate_score)
            selected[selected.index(worst_mega)] = best_non
        else:
            violations.append("non_mega_min unmet (no non-mega candidate)")

    # 5) k 미달 → 부족 표시 (shadow 는 fallback 으로 v1 가 이미 반환 중)
    fallback = False
    if len(selected) < k:
        violations.append(f"only {len(selected)}/{k} satisfy policy")
        fallback = True

    return {
        "selected": [c["video_id"] for c in selected],
        "detail": [
            {
                "video_id": c["video_id"],
                "score": round(_candidate_score(c), 4),
                "cluster_id": c.get("cluster_id"),
                "tier": c.get("tier", ""),
                "reason": c.get("reason", ""),
            }
            for c in selected
        ],
        "fallback": fallback,
        "violations": violations,
        "stats": {
            "scope_excluded": scope_excluded,
            "mega": mega_count,
            "clusters_covered": len(covered_clusters),
            "channels": len(per_channel),
        },
    }
