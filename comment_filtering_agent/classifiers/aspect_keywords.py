"""제품 속성 키워드 — VR → ANALYZE 승격 판단용 후처리 매칭.

agent.py 의 `_handle_video_reaction` 는 `mentioned_product_features` 가
2개 이상이면 분석 대상으로 승격한다. 워커 기반 로컬 분류기(klue-roberta-large
3-class)는 라벨만 내므로, VR 댓글에 한해 이 키워드로 features 를 채워준다.

⚠️ `scripts/api/sync.py:PRODUCT_ASPECT_KEYWORDS` 와 **동기**된 리스트.
(재현 testLocalvsAPI `local_classifier/keywords.py` 와도 동일.) 한쪽을 바꾸면
양쪽 모두 업데이트할 것 — 두 backend(api/worker) 간 동등 비교의 전제다.
sync.py 에서 직접 import 하지 않는 이유: sync 모듈은 import 시 DB/환경 부작용이
있어 분류기 어댑터가 끌어오기엔 무겁고 순환 의존 위험이 있다.
"""
from __future__ import annotations

# 소비자 전자제품 리뷰에서 공통적으로 등장하는 속성(attribute) 키워드.
# 감정어(좋다/나쁘다/추천 등)는 의도적으로 제외 — 영상 반응 댓글과 구분 불가.
PRODUCT_ASPECT_KEYWORDS: list[str] = [
    # 성능/처리
    "성능", "속도", "처리", "발열", "온도", "쿨링",
    # 배터리
    "배터리", "충전", "배터리수명", "전력",
    # 디스플레이
    "화면", "디스플레이", "해상도", "밝기",
    # 디자인/외형
    "디자인", "무게", "크기", "마감", "색상", "두께",
    # 카메라
    "카메라", "화질", "사진",
    # 가격/가성비
    "가격", "가성비", "성가비",
    # 소프트웨어/UI
    "소프트웨어", "앱", "업데이트", "버그",
    # 내구성/서비스
    "내구성", "AS", "서비스", "품질",
    # 음향
    "소리", "음질", "스피커",
]


def extract_mentioned_features(
    text: str, extra_keywords: list[str] | None = None
) -> list[str]:
    """댓글 텍스트에 등장하는 제품 속성 키워드 추출.

    Args:
        text: 댓글 원문
        extra_keywords: 추가 매칭할 키워드 (예: product_name 토큰). default None.

    Returns:
        매칭된 키워드 리스트 (중복 제거, 입력 순서 유지).
    """
    if not text:
        return []
    haystack = text.lower()
    all_kw = PRODUCT_ASPECT_KEYWORDS + (extra_keywords or [])
    matched: list[str] = []
    seen: set[str] = set()
    for kw in all_kw:
        if not kw:
            continue
        kw_lower = kw.lower()
        if kw_lower in seen:
            continue
        if kw_lower in haystack:
            matched.append(kw)
            seen.add(kw_lower)
    return matched
