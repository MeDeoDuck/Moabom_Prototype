# Agent 단계 병렬화 파이프라인 설계 (기존 구조 유지)

## 1) 목표
- 기존 sync/수집/저장 흐름은 유지
- **Agent 처리 구간만 병렬화**해서 처리 시간 단축
- LLM API(단일 키) 레이트리밋을 넘지 않도록 안전장치 포함

## 2) 범위 (In / Out)
**In**
- `process_comments_with_agent()` 내부의 Agent 관련 처리 동시화
- 전역 LLM 동시성 제한(세마포어)
- 429 재시도(backoff + jitter)

**Out**
- DB 스키마 대개편
- 전체 DAG/route 구조 변경
- 수집 단계(YouTube fetch) 재설계

## 3) 현재 구조 요약
현재는 영상별로 다음이 순차 실행됨:
1. 1차 필터(rule)
2. 2차 필터/분류(LLM 포함)
3. Agent 의사결정 + 감성/속성 분석(LLM)
4. DB 저장

병목은 Agent/LLM 호출 구간.

## 4) 제안 아키텍처 (핵심)
### A. 영상 루프는 유지
- 기존 `sync.py`의 상위 흐름은 그대로 둠
- 구조를 깨지 않기 위해 route/응답/집계 방식은 변경 최소화

### B. Agent 단계만 병렬화
- `process_comments_with_agent()`에서 Agent 호출 부분만 병렬 executor로 처리
- 예: `ThreadPoolExecutor(max_workers=AGENT_WORKERS)`
- 각 comment 단위 작업:
  - `agent.decide()`
  - 필요한 경우 sentiment/aspect analyzer 호출
  - 결과 객체 반환 (DB write는 메인 스레드에서 일괄)

### C. 전역 LLM 게이트(중요)
- 단일 API 키에서도 병렬 호출 가능하지만, RPM/TPM 제한 존재
- 따라서 LLM 호출 직전에 전역 세마포어 적용:
  - `LLM_MAX_CONCURRENT=2` (초기 권장)
- Agent workers 수와 LLM 동시성은 분리:
  - 예: `AGENT_WORKERS=6`, `LLM_MAX_CONCURRENT=2`

## 5) 구현 포인트 (파일 기준)
1. **`scripts\api\sync.py`**
   - `process_comments_with_agent()` 내부 Agent 처리 loop를 병렬화
   - DB write는 기존처럼 일괄 처리(트랜잭션 경계 유지)

2. **`comment_filtering_agent\analyzers\groq_analyzer.py`**
3. **`comment_filtering_agent\classifiers\groq_classifier.py`**
   - 실제 LLM API 호출 직전에 공통 `acquire/release` 훅 추가
   - 429 시 재시도(backoff)

4. **(신규) `comment_filtering_agent\core\llm_gate.py`**
   - 전역 세마포어/레이트리밋 유틸 집중

## 6) 처리 흐름 (변경 후)
1. rule/2차 필터까지는 기존과 동일
2. Agent 대상 댓글 리스트를 준비
3. executor로 comment 단위 작업 병렬 실행
4. 각 worker는 LLM 호출 전 `llm_gate` 통과
5. 완료 결과를 모아서 기존 DB 저장 로직 실행

## 7) 의사코드
```python
# sync.py (개념)
from concurrent.futures import ThreadPoolExecutor, as_completed

def _run_agent_for_comment(comment):
    decision = agent.decide(comment)         # 내부에서 필요 시 LLM
    sentiment = None
    if decision.action == "ANALYZE":
        sentiment = sentiment_analyzer.analyze_single(comment.text)  # LLM
    return build_result(comment, decision, sentiment)

results = []
with ThreadPoolExecutor(max_workers=AGENT_WORKERS) as ex:
    futures = [ex.submit(_run_agent_for_comment, c) for c in candidate_comments]
    for f in as_completed(futures):
        results.append(f.result())

# 아래 DB write는 기존 코드 재사용
save_agent_results(results)
```

```python
# llm_gate.py (개념)
import threading
LLM_SEM = threading.Semaphore(LLM_MAX_CONCURRENT)

def guarded_llm_call(fn, *args, **kwargs):
    with LLM_SEM:
        return retry_with_backoff(fn, *args, **kwargs)
```

## 8) 설정값 권장
- `AGENT_WORKERS=4~8` (CPU/메모리 보고 조정)
- `LLM_MAX_CONCURRENT=2` (429 많으면 1로)
- `LLM_MAX_RETRIES=3`
- `LLM_BACKOFF_BASE=1.0`

## 9) 실패/안정성 전략
- worker 단위 예외는 수집 후 해당 comment만 실패 처리 (전체 중단 방지)
- 429/5xx만 재시도, 포맷 실패는 기존 정책 유지
- 타임아웃 지정(예: LLM call 20~30s)
- 결과 순서가 바뀌어도 DB upsert 기준(comment_id)으로 정합성 보장

## 10) 기대 효과
- 구조 변경 최소로 도입 가능
- 병목 구간(Agent/LLM) 병렬화로 체감 속도 개선
- 레이트리밋 보호와 안정성(재시도/세마포어) 동시 확보

## 11) Airflow / Spark 사용 방식 정리
### 11-1. Airflow는 현재 어떻게 쓰이고 있나
코드에는 Airflow DAG가 존재하지만, **기본 메인 실행 경로는 FastAPI(`main_youtube_tech_review.py`)**입니다.
즉, 현재 운영이 FastAPI 중심이면 Airflow는 "준비된 별도 오케스트레이션 경로"로 보는 것이 맞습니다.

- Airflow 코드 위치: `dags\youtube_product_sync_dag.py`
- DAG ID: `youtube_product_sync_pipeline`
- 스케줄 정의: `*/30 * * * *` (30분 주기)
- 관련 callable: `services\analysis\airflow_analysis_runner.py`

정리하면:
- **현재 메인 경로**: FastAPI route 기반 sync/analysis
- **Airflow 경로**: Airflow를 별도로 띄웠을 때에만 사용되는 배치 오케스트레이션 경로

### 11-2. Airflow에서 병렬화가 걸리는 지점
Airflow를 실제 운영에 붙였을 경우 병렬화는 두 레벨에서 결정됩니다.

1. **DAG/Task 레벨**
   - task 분리와 dependency 방식으로 병렬/직렬이 정해짐
   - `max_active_runs`, task retry, pool/concurrency 설정으로 실행량 제어

2. **Task 내부 코드 레벨**
   - 한 task 내부에서 `ThreadPoolExecutor`/async로 추가 병렬화 가능
   - 이번 문서에서 제안한 방식은 여기에 해당 (agent 처리만 병렬화)

핵심은: 현재 FastAPI 메인을 유지해도, 그리고 Airflow를 나중에 붙여도,
**공통으로 task/함수 내부에서 agent만 병렬화**할 수 있다는 점입니다.

### 11-3. Spark는 현재 어떻게 쓰이고 있나
현재는 `sync.py` 내부에 **Spark Local 전처리(우선) + Python fallback** 형태로 적용합니다.

- 위치: `scripts\api\sync.py`의 `_spark_preprocess_comments(...)`
- 동작:
  1) `text` null/blank 제거 (기술적 오류만 제거)
  2) `(video_id, author, text)` 기준 중복 제거
  3) `text_cleaned = trim(text)` 생성 (내부 공백은 건드리지 않음)
  4) `char_count`, `is_short`, `has_url`, `is_repetitive` 플래그 부착
- 주의: 플래그는 **즉시 제거용이 아니라 후단 Agent/점수 참고용**
- 환경에 Spark가 없으면 동일 로직을 Python으로 fallback 실행

즉, 현재 전략은 **Spark 전처리 + Agent 병렬화 + LLM 동시성 제어** 조합입니다.

### 11-4. 그럼 Spark는 언제 고려하나
아래 조건이면 Spark 비중을 더 키우는 것을 고려합니다.

- 영상/댓글 규모가 매우 커져서 단일 프로세스 메모리/CPU 한계에 도달
- 배치 ETL 중심으로 대량 데이터 조인/집계가 필요
- LLM 호출 전 대규모 전처리(정제, 통계, 피처화)를 분산 처리해야 함

현재도 Spark는 전처리에 적용했지만, 여전히 주 병목은 LLM API 호출이므로
**(1) agent 내부 병렬화 + (2) 전역 LLM 게이트 + (3) 재시도/레이트리밋 제어**가 핵심입니다.

### 11-5. 권장 운영 모델 (현재 코드베이스 기준)
- 오케스트레이션(현재): **FastAPI 메인 경로 유지**
- 오케스트레이션(선택): **Airflow DAG는 배치 전환 시 사용**
- 전처리: **Spark Local 우선 + Python fallback**
- 병렬 처리: **agent 단계 executor 병렬화**
- 보호 장치: **LLM semaphore + 429 backoff**
- 확장 순서:  
  1) Spark 전처리 + agent 병렬화 안정화  
  2) 모니터링(후보수/분류수/429)  
  3) 필요 시 영상 단위 병렬화 추가  
  4) 그래도 한계면 Spark 클러스터 확장 검토

## 12) 구조도 (FastAPI + Agent 병렬화 + Spark 얇은 도입)
아래는 **현재 메인(FastAPI) 구조를 유지**하면서, Spark를 전처리 레이어에 얇게 넣는 구조도입니다.

```text
[Client/UI]
    |
    v
[FastAPI: main_youtube_tech_review.py]
    |
    v
[sync route: scripts/api/sync.py]
    |
    +--> [YouTube API 수집]
    |         - videos/comments fetch
    |
    +--> [DB 저장: raw comments]
    |
    +--> [Spark Local 전처리 (선택)]
    |         - null/blank 제거
    |         - (video_id, author, text) dedup
    |         - trim + flags(is_short, has_url, is_repetitive)
    |         - output: candidate_comments
    |
    +--> [Agent 처리 (병렬)]
    |         - ThreadPoolExecutor (AGENT_WORKERS)
    |         - comment 단위 처리
    |         - agent.decide()
    |         - sentiment/aspect 분석
    |
    +--> [LLM Gate]
    |         - Semaphore(LLM_MAX_CONCURRENT)
    |         - 429 retry(backoff+jitter)
    |
    +--> [DB upsert]
    |         - rule_filter_results
    |         - llm_classifications
    |         - agent_decisions
    |         - comment_sentiments / aspect_extractions
    |
    v
[API Response + Report Pipeline]
```

### 12-1. Airflow를 붙일 때 구조
Airflow는 메인 경로를 대체하는 것이 아니라, 같은 처리 함수를 **스케줄 기반으로 호출**하는 오케스트레이션 레이어입니다.

```text
[Airflow DAG (optional)]
    |
    v
[task callable]
    |
    v
[동일한 sync/analysis 함수 재사용]
    |
    v
[Spark 전처리(선택) + Agent 병렬화 + LLM Gate + DB]
```

### 12-2. 발표 포인트(종합설계용)
- "Spark는 대규모 전처리/집계 계층으로 적용"
- "LLM 병목은 Spark가 아니라 동시성 제어(세마포어/재시도)로 해결"
- "기존 FastAPI 구조를 유지해 리스크를 낮추고, Airflow는 확장 가능한 운영 옵션으로 분리"
