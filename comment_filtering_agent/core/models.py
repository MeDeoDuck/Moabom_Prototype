"""
댓글 필터링 Agent - 데이터 모델

Agent 의사결정을 위한 데이터 모델
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from datetime import datetime


class AgentAction(str, Enum):
    """Agent 최종 액션"""
    ANALYZE = "ANALYZE"                     # 감정/항목 분석 진행
    AUXILIARY_STORE = "AUXILIARY_STORE"     # 보조 데이터 저장 (질문 등)
    EXCLUDE = "EXCLUDE"                     # 제외 (분석 안 함)
    HOLD = "HOLD"                           # 보류 (판단 불가)
    RECLASSIFY = "RECLASSIFY"               # 재분류 필요


class ExclusionReason(str, Enum):
    """제외 사유"""
    RULE_FILTERED = "RULE_FILTERED"         # 1차 필터에서 제외
    VIDEO_REACTION = "VIDEO_REACTION"       # 영상 반응 댓글
    CHATTER = "CHATTER"                     # 잡담/무의미
    OFF_TOPIC = "OFF_TOPIC"                 # 제품 무관
    OFF_TOPIC_QUESTION = "OFF_TOPIC_QUESTION"  # 제품 무관 질문
    DUPLICATE = "DUPLICATE"                 # 중복
    SPAM = "SPAM"                           # 스팸
    ABUSIVE = "ABUSIVE"                     # 욕설
    LOW_QUALITY = "LOW_QUALITY"             # 저품질


@dataclass
class AgentDecision:
    """Agent 최종 결정"""
    # 기본 정보
    index: int                              # 댓글 인덱스
    original_comment: str                   # 원본 댓글
    
    # 최종 결정
    final_action: AgentAction               # 최종 액션
    final_reason: str                       # 결정 이유 (한 줄)
    
    # 다음 단계 플래그
    should_run_sentiment: bool = False      # 감정 분석 실행 여부
    should_run_aspect_analysis: bool = False  # 항목 추출 실행 여부
    should_store_as_question: bool = False  # 질문으로 저장 여부
    should_send_llm_recheck: bool = False   # LLM 재확인 여부
    
    # 제외 정보 (EXCLUDE인 경우)
    exclusion_reason: Optional[ExclusionReason] = None
    exclusion_details: Optional[str] = None
    
    # 확신도 정보
    is_low_confidence: bool = False         # 저확신 여부
    needs_human_review: bool = False        # 수동 검토 필요 여부
    needs_reclassification: bool = False    # 재분류 필요 여부
    
    # 메타데이터
    decision_reasoning: str = ""            # 상세 의사결정 과정
    agent_version: str = "1.0"
    confidence_threshold: Optional[float] = None
    decision_metadata: dict = field(default_factory=dict)
    decided_at: Optional[datetime] = None
    
    # 입력 정보 참조
    rule_filter_passed: bool = True         # 1차 필터 통과 여부
    llm_label: Optional[str] = None         # 2차 분류 라벨
    llm_confidence: Optional[float] = None  # 2차 분류 확신도
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "index": self.index,
            "original_comment": self.original_comment,
            "final_action": self.final_action.value,
            "final_reason": self.final_reason,
            "should_run_sentiment": self.should_run_sentiment,
            "should_run_aspect_analysis": self.should_run_aspect_analysis,
            "should_store_as_question": self.should_store_as_question,
            "should_send_llm_recheck": self.should_send_llm_recheck,
            "exclusion_reason": self.exclusion_reason.value if self.exclusion_reason else None,
            "exclusion_details": self.exclusion_details,
            "is_low_confidence": self.is_low_confidence,
            "needs_human_review": self.needs_human_review,
            "needs_reclassification": self.needs_reclassification,
            "decision_reasoning": self.decision_reasoning,
            "agent_version": self.agent_version,
            "confidence_threshold": self.confidence_threshold,
            "decision_metadata": self.decision_metadata,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "rule_filter_passed": self.rule_filter_passed,
            "llm_label": self.llm_label,
            "llm_confidence": self.llm_confidence
        }
    
    @property
    def next_stage(self) -> str:
        """다음 단계 이름"""
        if self.final_action == AgentAction.ANALYZE:
            return "SENTIMENT_ANALYSIS"
        elif self.final_action == AgentAction.AUXILIARY_STORE:
            return "QUESTION_STORAGE"
        elif self.final_action == AgentAction.EXCLUDE:
            return "EXCLUDED_LOG"
        elif self.final_action == AgentAction.HOLD:
            return "MANUAL_REVIEW"
        elif self.final_action == AgentAction.RECLASSIFY:
            return "RECLASSIFICATION_QUEUE"
        return "UNKNOWN"


@dataclass
class AgentPolicyConfig:
    """Agent 정책 설정"""
    # 버전 정보
    version: str = "1.0"
    description: str = "기본 의사결정 정책"
    
    # 확신도 임계값
    high_confidence_threshold: float = 0.8
    medium_confidence_threshold: float = 0.6
    low_confidence_threshold: float = 0.5
    
    # 정책 플래그
    exclude_all_questions: bool = False     # 모든 질문 제외
    allow_video_reaction_with_features: bool = True  # 제품 특성 많으면 허용
    hold_instead_of_reclassify: bool = False  # 재분류 대신 보류
    
    # 1차 필터 예외 허용 (특정 사유는 2차 분류로 넘김)
    allow_llm_override_rules: List[str] = field(default_factory=list)
    
    # 최소 제품 특성 언급 수 (VIDEO_REACTION 예외 처리)
    min_product_features_for_analysis: int = 2
    
    # 재분류 우선순위
    reclassify_priority_high_confidence_threshold: float = 0.7
    
    # 보류 조건
    hold_below_confidence: float = 0.5
    
    def get_confidence_level(self, confidence: float) -> str:
        """확신도 레벨 반환"""
        if confidence >= self.high_confidence_threshold:
            return "HIGH"
        elif confidence >= self.medium_confidence_threshold:
            return "MEDIUM"
        elif confidence >= self.low_confidence_threshold:
            return "LOW"
        else:
            return "VERY_LOW"
