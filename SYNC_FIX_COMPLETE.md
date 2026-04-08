# Sync.py 문제점 분석 및 수정 완료

## 🐛 발견된 문제들

### 1. ❌ `fetch_video_comments` import 누락
**문제:**
```python
except ImportError as e:
    AGENT_AVAILABLE = False
    from scripts.youtube.comment_service import fetch_video_comments  # 여기서만 import
```

Agent가 사용 가능할 때는 import 안 됨. 하지만 fallback 코드에서 사용함!

**수정:** ✅
```python
from scripts.youtube.comment_service import fetch_video_comments  # 항상 import
```

---

### 2. ❌ Config 변수들 조건부 import
**문제:**
```python
try:
    from scripts.config import YOUTUBE_API_KEY, GROQ_API_KEY, DATABASE_URL  # try 안에만
    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False  # 이 경우 변수들이 없음!
```

Agent import 실패하면 `DATABASE_URL`, `GROQ_API_KEY` 등도 사용 불가.

**수정:** ✅
```python
from scripts.config import YOUTUBE_API_KEY, GROQ_API_KEY, DATABASE_URL  # 항상 import
```

---

## ✅ 현재 수정된 Import 구조

```python
# 항상 import (필수)
from fastapi import HTTPException
from scripts.database.queries import query_one, query_all, execute_update, execute_insert
from scripts.database.connection import get_connection
from scripts.youtube.video_service import fetch_product_videos
from scripts.youtube.comment_service import fetch_video_comments  # ✅ 항상
from scripts.config import YOUTUBE_API_KEY, GROQ_API_KEY, DATABASE_URL  # ✅ 항상
import uuid
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

# Agent import (선택적)
try:
    from comment_filtering_agent.services.comment_collector import YouTubeCommentCollector
    from comment_filtering_agent.filters.rule_based_filter import RuleBasedFilter
    from comment_filtering_agent.classifiers.groq_classifier import GroqClassifier
    from comment_filtering_agent.core.agent import AgentDecisionEngine
    from comment_filtering_agent.core.models import AgentAction
    from comment_filtering_agent.analyzers.groq_analyzer import GroqAspectSentimentAnalyzer
    AGENT_AVAILABLE = True
except ImportError as e:
    print(f"[WARN] Comment filtering agent not available: {e}")
    AGENT_AVAILABLE = False
```

---

## 🔍 추가 체크 완료

### ✅ 다른 잠재적 문제들
1. **config.py 존재 확인** ✅
   - `DATABASE_URL`, `YOUTUBE_API_KEY`, `GROQ_API_KEY` 정의됨
   
2. **comment_service.py 확인** ✅
   - `fetch_video_comments()` 함수 존재
   
3. **Fallback 로직 확인** ✅
   - Agent 실패 시 기존 방식으로 정상 작동

---

## 🎯 결과

모든 import 문제 해결 완료!
- ✅ Agent 사용 가능 시: Agent 파이프라인 사용
- ✅ Agent 사용 불가 시: 기존 방식으로 fallback
- ✅ 두 경우 모두 필요한 함수/변수 접근 가능

---

## 🚀 테스트 방법

1. 서버 재시작
2. 제품 Sync 재실행
3. Agent가 정상 작동하거나, fallback으로 기존 방식 실행됨

**기대 결과:**
- Agent 정상: 고급 필터링 + LLM 분류
- Agent 에러: 기존 단순 댓글 수집 + 감정 분석
