# 영상 선정 에이전트 v3 — Coarse-to-Fine Clustering 설계

> 상태: **설계 확정** (2026-06-07) · 대상 모듈: `video_selection_agent/`
> 선행 설계: [VIDEO_SELECTION_AGENT_DESIGN.md](VIDEO_SELECTION_AGENT_DESIGN.md) (현 운영 v1)
> 검증: codex(GPT-5.5 xhigh) 3라운드 적대적 리뷰 + 임베딩 PoC(실측)

---

## 1. 배경 & 목표

현 운영(v1) 영상 선정은 6차원 가중합(`final_score`)이 `diversity_filter`·`finalize_selection`을 지배하는 구조다. 다음 세 문제를 해결한다.

1. **근거 없는 휴리스틱 가중치** — `relevance .30 / engagement .15 / recency .10 / channel_anti_bias .20 / duration_fit .10 / llm_topical_fit .15` 가 손으로 정해졌고, 가중치 변경이 선정 품질을 개선하는지 **측정할 장치가 없다**. (본질은 "숫자가 임의"가 아니라 "효과를 못 잰다".)
2. **중소채널 편향** — MVP 설문에서 "왜 작은 채널이 많이 나오냐" 피드백. `channel_anti_bias=0.20` + `1-log10(subs)/7` 공식이 작은 채널을 강하게 끌어올림.
3. **비교/랭킹 영상 노이즈** — 단일 제품 리뷰만 들어와야 하는데 비교영상이 섞임 (scope 분류기로 일부 대응 중).

**핵심 목표**: 선형 가중합이 selection을 지배하는 구조를 깨고, 각 단계의 역할을 분리해 휴리스틱 의존을 줄이며 **변경 효과를 측정 가능**하게 만든다.

---

## 2. 설계 원칙

| 주체 | 역할 |
|---|---|
| **코드 (결정적)** | gate 제외 · 임베딩 · 클러스터링 · 정책 verify/조합 선택 |
| **LLM (의미 판단)** | 클러스터 라벨 · shortlist · 후보별 판단(fit/depth/risk) + 근거 — 전부 근거 출력 |
| **가중합 (feature)** | selection 지배에서 제거. trace/debug 신호로만 잔존 |

- 가중합으로 "하나의 숫자가 모든 결정을 지배"하지 않게 한다.
- LLM에 최종 선택을 통째로 넘기지 않는다(비결정성·정책 미준수 위험). **LLM은 후보별 판단, 코드가 정책 만족 조합 선택.**
- 비교영상 제외·다양성·k 범위 등 정책은 **코드가 강제**(LLM 기분에 맡기지 않음).

---

## 3. 파이프라인 (병렬/직렬 구조)

```
[1] fetch_candidates                              Data API → 후보 ~30 (한국어 쿼리)
        │
        │  ┌─────────────── 병렬 (asyncio.gather) ───────────────┐
        ├─→│ A) enrich_metadata → score_feature   [Data API]      │
        ├─→│ B) scope_classify (비교영상 분류)     [GPU 워커 HTTP] │
        └─→│ C) lang_normalize (영문만 번역)        [RunYourAI LLM] │
           └──────────────────────┬───────────────────────────────┘
                                   │ (join)
        ┌──────────────────────────────────────────────┐
        │ [4] candidate_gate   ← A.feature + B.scope     │  scope 제외 + 품질게이트
        │     (후보 부족 시 완화, scope는 유지)           │
        └──────────────────────┬─────────────────────────┘
                               │ gate통과 후보 ∩ C.정규화텍스트
        ╔══════════════════ 여기부터 직렬 (앞 결과 의존) ═══════════════════╗
        ║ [6] coarse_cluster   Qwen3-4B 임베딩 → KMeans k=5  [GPU]           ║
        ║         ↓                                                          ║
        ║ [7] llm_cluster_shortlist   LLM#1: 라벨 + 클러스터당 2개           ║
        ║         ↓                                                          ║
        ║ [8] fetch_transcripts   shortlist ~10개 자막 (first/middle/last)   ║
        ║         ↓                                                          ║
        ║ [9] llm_final_select + rationale + verify                          ║
        ║       LLM#2: 후보별 {fit, depth, risk, reason} (CoT)               ║
        ║       → 코드 verifier: 정책 + coverage bonus 조합 선택 → 5개       ║
        ╚════════════════════════════════════════════════════════════════════╝
```

- **앞단(A·B·C)은 서로 다른 외부 서비스 + 독립 데이터**라 병렬(`asyncio.gather`, self-healing 기존 패턴 재사용). **클러스터 이후는 앞 결과 의존이라 직렬.**
- LLM 콜은 직렬 2개(#1 shortlist, #2 select+rationale) + 영문 있을 때 번역 1개(앞단 병렬). 기존 `generate_rationale` 별도 노드는 **#2에 통합·제거**.

---

## 4. 노드별 명세

### [1] fetch_candidates — (유지)
Data API search/videos. 한국어 쿼리("리뷰/단점/브랜드"). **개선**: 후보 부족 대비 pool 확장(30→50)·쿼리 다양화를 candidate_gate 완화 경로와 연동.

### [2] enrich_metadata → [3] score_quantitative — (변경)
채널 메타(구독자/tier) 보강 후 6차원 **feature 추출만**. `final_score` 가중합은 selection 기준에서 제거(trace용 잔존).

### [4] candidate_gate — (scope_filter 확장)
- **scope 제외**: 비교/랭킹 영상(klue-roberta 워커, `label=1 & conf≥0.7`). ⚠️ 현 `scope_filter`가 `rank>0`만 분류하던 한계를 버리고 **전체 후보** 분류.
- **품질 게이트**: 명백한 부적합 제외(`duration<180s` shorts, `relevance=0` 완전 무관).
- **후보 부족 시 완화**: ①pool 30→50 ②쿼리 추가 ③duration 조건부 완화 ④relevance 완화는 최후(+ title fuzzy hit 있을 때만). **scope(비교영상)는 절대 유지.** 목표 k=5 최대한 보장.

### [5] lang_normalize — (신규)
`is_en()` 언어 감지 → **영문만** RunYourAI GPT-4.1 batch 1콜로 한국어 번역(제목+설명). 한국어는 그대로. 임베딩 입력 언어 통일로 cross-lingual 확보. (실전 후보는 대부분 한국어라 평소 비용 ≈ 0, 영문 섞일 때만 +2-3초)

### [6] coarse_cluster — (신규)
정규화된 `제목+설명(앞 500자)` → **Qwen3-Embedding-4B**(데스크탑 GPU, fp16, dim 2560) → **KMeans k=5**(seed 고정). 클러스터는 "관점 정답"이 아니라 **자막 fetch 예산 배분 + 중복 완화** 장치로 본다.

### [7] llm_cluster_shortlist — (신규, LLM#1)
입력: 클러스터별 묶인 영상 `{cluster_id, 제목, 설명, 구독자수, engagement, 게시일, tier(원시값)}`.
출력(structured): 각 클러스터 라벨 + 클러스터당 "자막 볼 가치 있는 2개" + 이유 → shortlist ~10개.

### [8] fetch_transcripts — (신규)
shortlist ~10개만 자막 fetch(병렬 Semaphore=5). 자막은 임베딩/입력 한도 고려해 **first/middle/last 샘플링**(테크 리뷰는 단점이 중후반에 나옴 — 앞부분 cap 금지). 자막 없으면 제목+설명 fallback.

### [9] llm_final_select + rationale + verify — (신규, LLM#2)
- LLM#2: shortlist **각 후보**에 대해 CoT로 `{fit, depth, risk, reason}` 출력. (자막 기반이라 근거 풍부)
- 코드 verifier: `fit + coverage bonus`로 정책 만족 **조합** 선택.
  - 정책: `scope 영상 0` · `mega ≤ 2(=⌈5·0.4⌉)` · `채널당 ≤ max_per_channel` · `non-mega ≥ 1` · `small/micro upper cap` · `k=5`.
  - 위반 시 클러스터 내 차순위 교체, 최종 실패 시 v1_weighted fallback.
- **rationale 통합**: 모든 후보에 reason을 미리 달아두므로, 코드가 어떤 조합을 고르든(verify 교체 포함) 근거가 이미 존재. 별도 `generate_rationale` 노드 불필요. (shortlist 밖 fallback 영상만 heuristic 근거 보강)

---

## 5. 핵심 설계 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 임베딩 모델 | **Qwen3-Embedding-4B** (자체호스팅 GPU) | PoC에서 관점 분리 3-large >> 우위. 무료(비용 민감). RTX 4060 Ti 16GB 적재 가능 |
| 입력 언어 | 영문만 GPT-4.1 번역으로 한국어 통일 | PoC: 언어가 1차 분할축 → 통일 시 관점 분리. 실전 대부분 한국어라 저비용 |
| 클러스터링 | KMeans k=5 (예산배분기) + coverage bonus | "클러스터당 best 1 강제"는 불균형 시 좋은 후보 버림 → soft bonus로 다양성 유도 |
| 최종 선택 | LLM 후보별 판단 + 코드 조합 선택 | LLM 직접 선택은 repair 모순·비결정성. "LLM 품질판단, 코드 조합최적화" |
| rationale | llm_final_select에 통합(CoT) | LLM 콜 3→2, 판단-근거 일관성, 자막 기반 근거 |
| 다양성 | 내용 클러스터 + tier 정책 분리 | 클러스터(내용)는 tier 다양성 자동 보장 X → tier floor/cap 별도 강제 |
| tier 정책 | mega≤2, non-mega≥1, small/micro upper cap | 설문 불만은 micro/small 과다 — non-mega≥1만으론 못 막음 |

> **scikit-learn 추가**: 명세 임시안엔 "미적용"이었으나 본 설계에서 KMeans용으로 도입 결정(NR-007 의존성 정책 인지하에 팀 합의). docker `requirements` 반영, 이미지 ~100MB↑(scipy 동반).

---

## 6. PoC 근거 (실측, 2026-06-04)

아이폰17 후보로 임베딩→KMeans k=5 비교 ([[project-video-clustering-poc]] 메모리).

- **3-large**: 언어로 강하게 갈림(순영문/순한글 분리), 관점 혼재("한국어 덩어리"). cross-lingual 실패.
- **Qwen3-4B**: 관점 분리 개선, 단 한/영 섞으면 여전히 언어가 1차 분할.
- **한국어-only 통제실험**: Qwen3-4B가 **세대비교 / 장기실사용기·내구성 / 타사비교 / 단점·비판 / 스펙대결**로 깔끔하게 관점 분리. 3-large는 12개 덩어리로 혼재.

→ 결론: **Qwen3-4B + 언어 통일이면 제목+설명만으로도 관점 클러스터링 성립** (자막 없이도). codex의 "제목+설명으론 관점 불가" 경고를 강한 모델 + 언어통일이 부분 반증.

부가 검증: RunYourAI 게이트웨이가 `text-embedding-3-large` 라우팅 OK(HTTP 200, dim 3072). 자막 fetch 실측 영상당 ~1.9s(콜드 12s), 30개 병렬5 ≈ 20~25s ([[reference-transcript-fetch-timing]]).

---

## 7. 측정 지표 (라벨 없이)

- `mega/large/mid/small/micro share` (중소채널 편향)
- `scope leakage` (비교영상 최종 선정 = **0 목표**)
- `repeated-run Jaccard` (안정성/비결정성)
- `latency p95`
- `fallback rate` (높으면 새 구조가 실제로 동작 안 한다는 신호 — fallback은 안전망이지 정상경로 X)
- `v1 대비 선정 overlap`
- `transcript fetch 성공/실패/시간`

---

## 8. Feature flag / Shadow / 무중단

- `SELECTION_STRATEGY = v1_weighted | v3_cluster` (env kill switch)
- **shadow 단계**: v1 결과를 사용자에게 반환 + v3 결과는 trace/DB에만 기록. ⚠️ shadow도 자막 fetch하면 차단 위험이 그대로 늘므로 **전체 트래픽이 아니라 일부 제품/요청에만** 켠다.
- 지표 통과 시 일부 제품 → 전체로 승격. 실패 시 즉시 v1 fallback.

---

## 9. PR 분해 (codex 권고 순서 — 측정 우선)

| PR | 내용 |
|---|---|
| **PR1** 계측 + 공통선행 | strategy별 측정(latency/tier share/scope leakage/fallback/overlap/transcript) + feature flag + v1 현황 저장 + `rationale_prompts` "비교 리뷰 가점" 제거 + candidate_pool view_count 절삭/쿼리 다양화 점검 |
| **PR2** coarse shadow | lang_normalize + coarse_cluster(Qwen3 임베딩 워커) + shortlist를 shadow로. 자막 fetch 없음/극소수 샘플. v1 반환 유지 |
| **PR3** fine + select | fetch_transcripts + llm_final_select(후보별 판단 + verifier 조합) + rationale 통합 |
| **PR4** 활성화 | fallback rate·latency p95 기준 통과 시 일부 제품 v3_cluster on → 확대 |

> 측정을 PR1로 앞당기는 이유: shadow 결과를 해석하려면 계측이 먼저 있어야 함.

---

## 10. 미해결 / 리스크

- **Qwen3 임베딩 워커 인프라** — scope-classify 워커와 동일 패턴(데스크탑 GPU)으로 추가. 워커 부재 시 fallback(3-large 또는 v1) 필요.
- **candidate_pool `view_count` 내림차순 절삭** (`candidate_pool.py:176`) — 클러스터링 전에 이미 대형 채널 편향. tier 다양성 위해 pool 확장/쿼리 다양화 선행 필요.
- **KMeans 불안정성** — 후보 추가/삭제 시 클러스터 흔들림, 불균형/소형 클러스터. coverage bonus·예산배분기 격하로 영향 축소했으나 모니터링 필요.
- **휴리스틱 위치 이동 경계** (codex 경고) — 클러스터 파라미터/LLM 프롬프트/coverage α/gate 임계가 새 휴리스틱이 될 수 있음. "역할 분리"로 정당화하되 측정으로 검증.
- **자막 차단** — 공식 API로 제3자 자막 불가([[reference-transcript-fetch-timing]]), 스크래핑 차단 위험. shortlist만 fetch로 현행 수준 유지.

---

## 11. 참고

- 로드맵: [[project-video-selection-overhaul]]
- PoC 실측: [[project-video-clustering-poc]]
- 자막 비용·공식 API 제약: [[reference-transcript-fetch-timing]]
- scope 분류기 별 repo: [[project-scope-classifier]]
- 임베딩 라우팅: [[reference-runyourai-embeddings]]
- v1 설문(속도 P0): [[project-v1-survey-rollout]]
