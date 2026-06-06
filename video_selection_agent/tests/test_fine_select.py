"""PR3 fine/final_select 단위 테스트.

verifier 는 순수 결정적 코드라 stub 없이 정책을 직접 검증. LLM·자막 fetch 경계는 stub.
"""
from __future__ import annotations

from video_selection_agent.clustering import fine, final_select, shadow
from video_selection_agent.clustering.final_select import VerifyPolicy, verify_and_select


# ---------- fine.sample_transcript ----------

def test_sample_short_returns_whole():
    t = "짧은 자막"
    assert fine.sample_transcript(t) == t


def test_sample_long_first_middle_last():
    t = "A" * 1000 + "B" * 3000 + "C" * 1000  # 5000자 > 4500
    s = fine.sample_transcript(t, chunk=1500)
    assert s.startswith("A")        # 앞 구간
    assert s.rstrip().endswith("C") # 뒤 구간(단점 중후반 보존)
    assert "…" in s
    assert len(s) < len(t)


# ---------- verify_and_select (결정적 정책) ----------

def _c(vid, *, fit=0.5, depth=0.5, risk=0.0, tier="mid", ch="ch", cluster=0, scope=0):
    return {"video_id": vid, "fit": fit, "depth": depth, "risk": risk,
            "tier": tier, "channel_id": ch, "cluster_id": cluster, "scope_label": scope}


def test_scope_videos_excluded():
    cands = [_c("a", fit=0.9, scope=1), _c("b", fit=0.5), _c("c", fit=0.4)]
    r = verify_and_select(cands, VerifyPolicy(k=2))
    assert "a" not in r["selected"]           # 비교영상 하드 제외
    assert r["stats"]["scope_excluded"] == 1


def test_mega_cap_enforced():
    # mega 6 + mid 3, k=5 → mega_cap=⌈5·0.4⌉=2
    cands = [_c(f"m{i}", fit=0.9, tier="mega", ch=f"c{i}", cluster=i) for i in range(6)]
    cands += [_c(f"x{i}", fit=0.5, tier="mid", ch=f"d{i}", cluster=i) for i in range(3)]
    r = verify_and_select(cands, VerifyPolicy(k=5))
    assert len(r["selected"]) == 5
    assert r["stats"]["mega"] == 2            # mega 상한 준수


def test_channel_cap_enforced():
    # 같은 채널 4개 고득점 + 다른 채널 3개, k=3, max_per_channel=2
    cands = [_c(f"a{i}", fit=0.9, ch="same", cluster=i) for i in range(4)]
    cands += [_c(f"b{i}", fit=0.4, ch=f"other{i}", cluster=i) for i in range(3)]
    r = verify_and_select(cands, VerifyPolicy(k=3, max_per_channel=2))
    same_cnt = sum(1 for d in r["detail"] if d["video_id"].startswith("a"))
    assert same_cnt <= 2


def test_non_mega_floor_swaps():
    # mega 2(고득점) + mid 1(저득점), k=2, mega_cap 충분 → 둘 다 mega 뽑힘 → floor 가 교체
    cands = [_c("m0", fit=0.9, tier="mega", ch="a", cluster=0),
             _c("m1", fit=0.85, tier="mega", ch="b", cluster=1),
             _c("d0", fit=0.3, tier="mid", ch="c", cluster=2)]
    r = verify_and_select(cands, VerifyPolicy(k=2, mega_ratio=1.0))
    tiers = [d["tier"] for d in r["detail"]]
    assert "mega" in tiers and any(t != "mega" for t in tiers)  # 최소 1 non-mega


def test_fallback_when_under_k():
    cands = [_c("a", fit=0.9), _c("b", fit=0.5)]
    r = verify_and_select(cands, VerifyPolicy(k=5))
    assert r["fallback"] is True and len(r["selected"]) == 2


def test_higher_score_preferred_and_deterministic():
    cands = [_c("low", fit=0.3, cluster=0), _c("high", fit=0.95, cluster=0), _c("mid", fit=0.6, cluster=0)]
    r1 = verify_and_select(cands, VerifyPolicy(k=1))
    r2 = verify_and_select(list(reversed(cands)), VerifyPolicy(k=1))
    assert r1["selected"] == ["high"] == r2["selected"]  # 입력 순서 무관 결정적


# ---------- llm_final_select (stub) ----------

def test_llm_final_select_filters_hallucination(monkeypatch):
    def fake(self, system, user, json_schema, **kw):
        return {"judgments": [
            {"video_id": "a", "fit": 0.8, "depth": 0.7, "risk": 0.1, "reason": "good"},
            {"video_id": "ZZZ", "fit": 0.9, "depth": 0.9, "risk": 0.0, "reason": "hallucinated"},
        ]}
    monkeypatch.setattr(
        "video_selection_agent.llm.azure_openai_client.AzureOpenAIClient.chat_structured", fake)
    cands = [{"video_id": "a", "title": "t", "description": "d"}]
    out, meta = final_select.llm_final_select(cands, transcripts={"a": "자막"})
    assert set(out.keys()) == {"a"}          # ZZZ 환각 차단
    assert meta["with_transcript"] == 1
    assert 0.0 <= out["a"]["fit"] <= 1.0


def test_llm_final_select_failure_isolated(monkeypatch):
    def boom(self, *a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(
        "video_selection_agent.llm.azure_openai_client.AzureOpenAIClient.chat_structured", boom)
    out, meta = final_select.llm_final_select([{"video_id": "a", "title": "t"}], {})
    assert out == {} and "error" in meta


# ---------- shadow fine 확장 (stub) ----------

def test_shadow_do_fine_runs_pipeline(monkeypatch):
    from video_selection_agent.clustering import coarse, embedder, lang_normalize, shortlist
    monkeypatch.setattr(lang_normalize, "normalize_texts",
                        lambda texts: (list(texts), {"n_total": len(texts)}))
    monkeypatch.setattr(embedder, "embed_texts",
                        lambda texts: ([[float(i)] for i in range(len(texts))], {"backend": "stub", "dim": 1}))
    monkeypatch.setattr(coarse, "kmeans_labels",
                        lambda vecs, k=5: ([0, 1], {"k_effective": 2, "cluster_sizes": {}}))
    monkeypatch.setattr(shortlist, "build_shortlist",
                        lambda cands, labels: ([{"video_id": "a", "cluster_id": 0, "cluster_label": "L", "reason": "r"},
                                                {"video_id": "b", "cluster_id": 1, "cluster_label": "L2", "reason": "r2"}],
                                               {"shortlist_size": 2}))
    monkeypatch.setattr(fine, "fetch_shortlist_transcripts",
                        lambda ids: ({"a": "자막A"}, {"attempted": 2, "succeeded": 1, "failed": 1}))
    monkeypatch.setattr(final_select, "llm_final_select",
                        lambda cands, tx: ({"a": {"fit": 0.9, "depth": 0.8, "risk": 0.1, "reason": "ok"},
                                            "b": {"fit": 0.6, "depth": 0.5, "risk": 0.2, "reason": "meh"}},
                                           {"n": 2}))
    cands = [{"video_id": "a", "title": "ta", "tier": "mid", "channel_id": "x", "scope_label": 0},
             {"video_id": "b", "title": "tb", "tier": "mega", "channel_id": "y", "scope_label": 0}]
    out = shadow.run_shadow(cands, v1_selected_ids=[], do_fine=True)
    assert out["ok"] is True
    assert "final_select" in out
    fs = out["final_select"]
    assert set(fs["selected"]) == {"a", "b"}
    assert fs["transcript_fetch"]["succeeded"] == 1


def test_shadow_no_fine_by_default(monkeypatch):
    from video_selection_agent.clustering import coarse, embedder, lang_normalize, shortlist
    monkeypatch.setattr(lang_normalize, "normalize_texts", lambda texts: (list(texts), {}))
    monkeypatch.setattr(embedder, "embed_texts", lambda texts: ([[1.0]] * len(texts), {"backend": "stub"}))
    monkeypatch.setattr(coarse, "kmeans_labels", lambda vecs, k=5: ([0] * len(vecs), {"k_effective": 1}))
    monkeypatch.setattr(shortlist, "build_shortlist",
                        lambda cands, labels: ([{"video_id": "a", "cluster_id": 0, "cluster_label": "L", "reason": "r"}], {}))
    out = shadow.run_shadow([{"video_id": "a", "title": "t"}], v1_selected_ids=[])  # do_fine 기본 False
    assert "final_select" not in out
