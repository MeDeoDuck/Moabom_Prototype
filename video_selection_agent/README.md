# Video Selection Agent (FR-005)

LangGraph 기반 유튜브 리뷰 영상 선택 에이전트. 제품별로 25~50개 후보 풀에서 **Auto / Custom** 방식으로 3~10개를 선정한다. 편향 완화 (대형 채널 쏠림 억제) + Explainable AI (정량 점수 6차원 + LLM rationale).

설계 문서: [docs/VIDEO_SELECTION_AGENT_DESIGN.md](../docs/VIDEO_SELECTION_AGENT_DESIGN.md)

## 상태

**Phase-3 완료** (2026-04 기준):
- ✅ Phase-1: 폴더 구조·데이터 모델·노드 stub·API 엔드포인트·DB 스키마.
- ✅ Phase-2: 정량 스코어링 (6차원) + YouTube API 연동 + 다양성 필터.
- ✅ Phase-3: Azure GPT-4.1-mini rerank + rationale + 웹 UI 통합.

iPhone 15 Pro 기준 end-to-end 검증: 30 후보 → 29 LLM rerank → 5 선정, 한국어 rationale 자동 생성.

## 구조

```
core/        데이터 모델, SelectionPolicyConfig, VideoSelectionAgent facade
graph/       LangGraph state / builder / 7개 노드
  nodes/     fetch_candidates → enrich_metadata → score_quantitative
             → diversity_filter ↔ relax_constraints (조건부 루프)
             → llm_rerank → finalize_selection → generate_rationale
scoring/     6차원 정량 점수 (relevance / engagement / recency
             / channel_anti_bias / duration / weights)
youtube/     candidate_pool (다중 쿼리) / channel_service
llm/         Azure OpenAI GPT-4.1-mini 클라이언트 + json_schema 프롬프트
persistence/ video_selection_runs / video_selection_scores 영속화
api/         POST /products/{id}/select-videos, GET /selection-runs/{run_id}
tests/       smoke / unit / integration (TODO)
```

`langgraph` 미설치 환경에서도 `_FallbackLinearGraph`가 동일 로직을 파이썬으로 에뮬레이션.

## 사용 — 코드

```python
from video_selection_agent.core.agent import VideoSelectionAgent
from video_selection_agent.core.models import ProductContext

agent = VideoSelectionAgent()
decision = agent.select(
    product=ProductContext(product_id=1, name="iPhone 15 Pro", brand="Apple"),
    mode="auto",  # 또는 "custom"
    k=5,          # 3~10
)
for v in decision.selected:
    print(f"#{v.rank} [{v.tier}] {v.title} — {v.final_score:.3f}")
    print(f"   {v.rationale_short}")
```

## 사용 — API

서버 기동: `docker compose up -d postgres && python main.py` → http://localhost:8000

### `POST /products/{product_id}/select-videos`

```json
{
  "mode": "auto",              // "auto" | "custom"
  "k": 5,                      // 3..10
  "candidate_pool_size": 30,   // 25..50
  "selected_video_ids": [],    // custom 모드에서 사용자 체크박스 선택
  "weights_override": null
}
```

응답:
```json
{
  "run_id": "uuid",
  "mode": "auto",
  "selected": [
    {
      "video_id": "...", "title": "...", "channel_name": "...",
      "tier": "large", "rank": 1, "final_score": 0.682,
      "dimensions": {"relevance": 0.73, "engagement": 0.82, ...},
      "weighted_contributions": {...},
      "rationale_short": "장기 사용기 중심으로 2026년에도 유효한 리뷰.",
      "rationale_full": "...",
      "selection_reasons": ["심층 리뷰 길이", "리뷰 적합성"]
    }
  ],
  "candidates_preview": [...],   // Custom 모드: 30개 후보 전체 (체크박스용)
  "diversity_report": {
    "channels_unique": 23,
    "tier_distribution": {"large": 13, "mega": 14, "mid": 2},
    "max_channel_occurrence": 1
  },
  "candidate_count": 30,
  "model_used": "gpt-4.1-mini",
  "policy_version": "v1.0.0-skeleton"
}
```

### `GET /products/{product_id}/selection-runs/{run_id}`

저장된 선정 결과 재조회.

## 사용 — UI

[templates/product_detail.html](../templates/product_detail.html) — `🎯 AI 영상 선택 (FR-005)` 보라색 버튼:

1. 모드 라디오 (Auto / Custom) + K 슬라이더 (3~10) + 풀 슬라이더 (25~50)
2. **AI 선택 시작** → 30~60초 (YouTube + 스코어링 + LLM rerank + rationale)
3. 결과 모달: 순위 카드 + 티어 뱃지 + 점수 + 이유 칩 + rationale_short
4. **왜 선택됨?** 모달: 6차원 점수 바 + 가중 기여도 + rationale_full
5. Custom 모드: 30개 후보 체크박스 (Auto 선정분 미리체크) → 3~10개 선택 → "Custom 선택으로 확정"

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | (필수) | `https://<resource>.cognitiveservices.azure.com` |
| `AZURE_OPENAI_API_KEY` | (필수) | Azure 리소스 키 |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4.1-mini` | 배포 이름 |
| `AZURE_OPENAI_API_VERSION` | `2025-01-01-preview` | API 버전 |
| `YOUTUBE_API_KEY` | (필수) | YouTube Data API v3 |
| `DATABASE_URL` | `postgresql://postgres:postgres@127.0.0.1:5432/techdb` | Postgres |

LLM 미설정 시 자동 graceful degradation: rerank 실패 → 정량 점수만 사용, rationale 실패 → `selection_reasons` 기반 fallback 문구.

## 편향 완화 전략

1. **채널 상한** (하드): `max_per_channel = 2`
2. **티어 쿼터**: 메가 채널 비율 ≤ 40%, 풀에 중소 채널 있으면 ≥ 20%
3. **anti-mega 가중치** (소프트): `1 - log10(subs)/7` → 1k 구독자 0.57 vs 10M 0.0
4. **다중 쿼리**: `"리뷰" / "review" / "단점" / "{brand} {name}"` 4종 → 다양화
5. 다양성 부족 시 `relax_constraints` 노드로 1회 자동 완화 후 재시도

## YouTube API 쿼터

회당 4 × search(100) + 2 × list(1) = **402 units**. 일일 10,000 한도 대비 충분.

## 비용

LLM 호출은 **정확히 2회/run** (rerank + rationale). GPT-4.1-mini ~$0.005/run, `max_tokens` 고정으로 상한 보장.

## 후속 과제

- 댓글 감성 기반 진짜 관점 다양성 (FR-010/011 이후)
- 재선택 시 이전 분석 데이터 정리 정책 확정
- 통합 테스트 추가 ([tests/](tests/))
