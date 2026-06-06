"""llm_cluster_shortlist — LLM#1 (설계 §4 [7]).

클러스터별로 묶인 영상 메타를 받아 ①클러스터 라벨 ②클러스터당 "자막 볼 가치
있는 2개" + 이유 를 출력 → shortlist(~10). 자막 fetch 예산을 배분하는 단계라
여기선 메타(제목·설명·구독자·engagement)만으로 판단한다.

shadow 전용(PR2): 결과는 metrics 에만 기록, 사용자 반환에 영향 없음.
"""
from __future__ import annotations

import json

_PICKS_PER_CLUSTER = 2
_DESC_TRUNC = 300

_SYSTEM = (
    "당신은 유튜브 테크 리뷰 영상을 선별하는 전문가입니다. 입력은 내용 군집별로 "
    "묶인 단일 제품 리뷰 후보들입니다. 각 군집에 대해: (1) 군집을 한 줄 한국어 "
    f"라벨로 요약하고, (2) 자막을 확인할 가치가 가장 큰 영상을 최대 {_PICKS_PER_CLUSTER}개 "
    "고르고 그 이유를 한국어로 쓰세요. 비교/랭킹 영상이 아니라 단일 제품을 깊이 다루는 "
    "영상을 우선하세요. 반드시 입력에 있는 video_id 만 사용하세요."
)

_SCHEMA = {
    "name": "cluster_shortlist",
    "schema": {
        "type": "object",
        "properties": {
            "clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {"type": "integer"},
                        "label": {"type": "string"},
                        "picks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "video_id": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["video_id", "reason"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["cluster_id", "label", "picks"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["clusters"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _group(candidates: list[dict], labels: list[int]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = {}
    for cand, lbl in zip(candidates, labels):
        groups.setdefault(int(lbl), []).append(cand)
    return groups


def build_shortlist(candidates: list[dict], labels: list[int]) -> tuple[list[dict], dict]:
    """군집된 후보 → shortlist + meta.

    candidates: [{video_id, title, description, subscriber_count, engagement,
                  published_at, tier}, ...] (labels 와 같은 순서)
    반환: (shortlist[{video_id, cluster_id, cluster_label, reason}], meta)
    LLM 실패 시 빈 shortlist + meta["error"].
    """
    meta = {"n_clusters": 0, "shortlist_size": 0}
    if not candidates:
        return [], meta

    groups = _group(candidates, labels)
    meta["n_clusters"] = len(groups)

    valid_ids = {c["video_id"] for c in candidates}
    payload = []
    for cid, vids in sorted(groups.items()):
        payload.append(
            {
                "cluster_id": cid,
                "videos": [
                    {
                        "video_id": v["video_id"],
                        "title": v.get("title", ""),
                        "description": (v.get("description", "") or "")[:_DESC_TRUNC],
                        "subscriber_count": v.get("subscriber_count", 0),
                        "engagement": v.get("engagement", 0),
                        "published_at": v.get("published_at", ""),
                        "tier": v.get("tier", ""),
                    }
                    for v in vids
                ],
            }
        )

    try:
        from video_selection_agent.llm.azure_openai_client import AzureOpenAIClient

        data = AzureOpenAIClient().chat_structured(
            system=_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            json_schema=_SCHEMA,
            max_tokens=2000,
            temperature=0.0,
        )
    except Exception as e:
        meta["error"] = f"shortlist llm failed: {e}"
        print(f"[shortlist] {meta['error']}", flush=True)
        return [], meta

    shortlist: list[dict] = []
    seen: set[str] = set()
    for cl in data.get("clusters", []):
        cid = int(cl.get("cluster_id", -1))
        label = cl.get("label", "")
        for pick in cl.get("picks", [])[:_PICKS_PER_CLUSTER]:
            vid = pick.get("video_id", "")
            if vid in valid_ids and vid not in seen:  # 환각 video_id 차단
                seen.add(vid)
                shortlist.append(
                    {
                        "video_id": vid,
                        "cluster_id": cid,
                        "cluster_label": label,
                        "reason": pick.get("reason", ""),
                    }
                )
    meta["shortlist_size"] = len(shortlist)
    return shortlist, meta
