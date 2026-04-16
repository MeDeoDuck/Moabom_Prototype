"""
댓글 필터링 Agent - 의사결정 엔진

1차 규칙 필터 + 2차 LLM 분류 결과를 종합하여
최종 액션을 결정하는 조정자(Coordinator)
"""
from typing import Optional, List
from datetime import datetime

from comment_filtering_agent.core.models import (
    AgentDecision,
    AgentAction,
    ExclusionReason,
    AgentPolicyConfig
)
from comment_filtering_agent.filters.models import FilterResult
from comment_filtering_agent.classifiers.models import (
    ClassificationResult,
    CommentLabel
)


class AgentDecisionEngine:
    """
    댓글 필터링 Agent - 의사결정 엔진
    
    역할:
    - 1차 규칙 필터 결과 검토
    - 2차 LLM 분류 결과 검토
    - 최종 액션 결정 (ANALYZE/AUXILIARY_STORE/EXCLUDE/HOLD/RECLASSIFY)
    - 다음 단계 플래그 설정
    """
    
    def __init__(self, policy_config: Optional[AgentPolicyConfig] = None):
        """
        Args:
            policy_config: Agent 정책 설정
        """
        self.policy = policy_config or AgentPolicyConfig()
    
    def decide(
        self,
        comment: str,
        filter_result: FilterResult,
        classification_result: Optional[ClassificationResult] = None,
        index: int = 0
    ) -> AgentDecision:
        """
        단일 댓글에 대한 최종 결정
        
        Args:
            comment: 원본 댓글
            filter_result: 1차 필터 결과
            classification_result: 2차 분류 결과 (1차 통과 시만 존재)
            index: 댓글 인덱스
        
        Returns:
            AgentDecision
        """
        # 의사결정 시작
        decision_reasoning = []
        
        # ========================================
        # 우선순위 1: 1차 규칙 필터 체크
        # ========================================
        if not filter_result.is_passed:
            decision_reasoning.append(f"1차 필터 REJECT: {filter_result.reject_reason_codes}")
            
            return self._create_exclude_decision(
                comment=comment,
                index=index,
                reason="1차 규칙 필터에서 제외됨",
                exclusion_reason=ExclusionReason.RULE_FILTERED,
                exclusion_details=f"규칙: {', '.join(filter_result.matched_rules)}",
                decision_reasoning=decision_reasoning,
                rule_filter_passed=False
            )
        
        decision_reasoning.append("1차 필터 PASS")
        
        # ========================================
        # 우선순위 2: 2차 LLM 분류 체크
        # ========================================
        if classification_result is None:
            # LLM 분류 실패
            decision_reasoning.append("2차 LLM 분류 실패")
            
            return AgentDecision(
                index=index,
                original_comment=comment,
                final_action=AgentAction.HOLD,
                final_reason="LLM 분류 실패로 보류",
                needs_human_review=True,
                decision_reasoning=" → ".join(decision_reasoning),
                agent_version=self.policy.version,
                decided_at=datetime.now(),
                rule_filter_passed=True
            )
        
        # LLM 분류 정보 추출
        label = classification_result.label
        confidence = classification_result.confidence
        needs_recheck = classification_result.needs_recheck
        is_product_related = classification_result.is_product_related
        mentioned_features = classification_result.mentioned_product_features
        
        confidence_level = self.policy.get_confidence_level(confidence)
        decision_reasoning.append(f"2차 분류: {label.value}, 확신도: {confidence:.2f} ({confidence_level})")
        
        # ========================================
        # 우선순위 3: 라벨별 처리
        # ========================================
        
        # 3-1. PRODUCT_OPINION
        if label == CommentLabel.PRODUCT_OPINION:
            return self._handle_product_opinion(
                comment=comment,
                index=index,
                confidence=confidence,
                needs_recheck=needs_recheck,
                mentioned_features=mentioned_features,
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 3-2. QUESTION
        elif label == CommentLabel.QUESTION:
            return self._handle_question(
                comment=comment,
                index=index,
                is_product_related=is_product_related,
                confidence=confidence,
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 3-3. VIDEO_REACTION
        elif label == CommentLabel.VIDEO_REACTION:
            return self._handle_video_reaction(
                comment=comment,
                index=index,
                mentioned_features=mentioned_features,
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 3-4. CHATTER
        elif label == CommentLabel.CHATTER:
            return self._handle_chatter(
                comment=comment,
                index=index,
                confidence=confidence,
                needs_recheck=needs_recheck,
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 3-5. OFF_TOPIC
        elif label == CommentLabel.OFF_TOPIC:
            return self._handle_off_topic(
                comment=comment,
                index=index,
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 기본값 (도달하면 안 됨)
        decision_reasoning.append("알 수 없는 라벨")
        return AgentDecision(
            index=index,
            original_comment=comment,
            final_action=AgentAction.HOLD,
            final_reason="알 수 없는 분류 라벨",
            needs_human_review=True,
            decision_reasoning=" → ".join(decision_reasoning),
            agent_version=self.policy.version,
            decided_at=datetime.now(),
            rule_filter_passed=True,
            llm_label=label.value if label else None,
            llm_confidence=confidence
        )
    
    def decide_batch(
        self,
        comments: List[str],
        filter_results: List[FilterResult],
        classification_results: List[Optional[ClassificationResult]]
    ) -> List[AgentDecision]:
        """
        배치 댓글 의사결정
        
        Args:
            comments: 댓글 리스트
            filter_results: 1차 필터 결과 리스트
            classification_results: 2차 분류 결과 리스트 (None 가능)
        
        Returns:
            AgentDecision 리스트
        """
        decisions = []
        
        for idx, (comment, filter_result, classification_result) in enumerate(
            zip(comments, filter_results, classification_results)
        ):
            decision = self.decide(
                comment=comment,
                filter_result=filter_result,
                classification_result=classification_result,
                index=idx
            )
            decisions.append(decision)
        
        return decisions
    
    # ========================================
    # 라벨별 처리 로직
    # ========================================
    
    def _handle_product_opinion(
        self,
        comment: str,
        index: int,
        confidence: float,
        needs_recheck: bool,
        mentioned_features: List[str],
        decision_reasoning: List[str],
        classification_result: ClassificationResult
    ) -> AgentDecision:
        """PRODUCT_OPINION 처리"""
        # PRODUCT_OPINION은 확신도와 무관하게 분석 진행
        # (낮은 확신도/재확인 필요는 제외 기준이 아니라 검토 플래그로 관리)
        confidence_level = self.policy.get_confidence_level(confidence)

        review_required = needs_recheck or confidence_level in {"LOW", "VERY_LOW"}
        if needs_recheck:
            decision_reasoning.append("재확인 필요 플래그 감지(분석은 진행)")
        if confidence_level in {"LOW", "VERY_LOW"}:
            decision_reasoning.append(f"낮은 확신도 ({confidence:.2f}, {confidence_level}) 감지(분석은 진행)")
        decision_reasoning.append(f"제품 평가 댓글 (확신도: {confidence:.2f}) → ANALYZE")
        
        return AgentDecision(
            index=index,
            original_comment=comment,
            final_action=AgentAction.ANALYZE,
            final_reason=f"제품 평가 댓글 분석 진행 (확신도: {confidence:.2f})",
            should_run_sentiment=True,
            should_run_aspect_analysis=True,
            is_low_confidence=confidence_level in {"LOW", "VERY_LOW"},
            needs_human_review=review_required,
            decision_reasoning=" → ".join(decision_reasoning),
            agent_version=self.policy.version,
            confidence_threshold=self.policy.high_confidence_threshold,
            decision_metadata={
                "mentioned_features": mentioned_features,
                "confidence_level": confidence_level,
                "needs_recheck": needs_recheck,
            },
            decided_at=datetime.now(),
            rule_filter_passed=True,
            llm_label=classification_result.label.value,
            llm_confidence=confidence
        )
    
    def _handle_question(
        self,
        comment: str,
        index: int,
        is_product_related: bool,
        confidence: float,
        decision_reasoning: List[str],
        classification_result: ClassificationResult
    ) -> AgentDecision:
        """QUESTION 처리"""
        # 정책: 모든 질문 제외
        if self.policy.exclude_all_questions:
            decision_reasoning.append("정책: 모든 질문 제외 → EXCLUDE")
            return self._create_exclude_decision(
                comment=comment,
                index=index,
                reason="질문 댓글 제외 정책",
                exclusion_reason=ExclusionReason.OFF_TOPIC_QUESTION,
                exclusion_details="정책에 의해 모든 질문 제외",
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 제품 관련 여부 체크
        if is_product_related:
            decision_reasoning.append("제품 관련 질문 → AUXILIARY_STORE")
            
            return AgentDecision(
                index=index,
                original_comment=comment,
                final_action=AgentAction.AUXILIARY_STORE,
                final_reason="제품 관련 질문을 보조 데이터로 저장",
                should_store_as_question=True,
                decision_reasoning=" → ".join(decision_reasoning),
                agent_version=self.policy.version,
                decision_metadata={
                    "is_product_related": is_product_related,
                    "confidence": confidence
                },
                decided_at=datetime.now(),
                rule_filter_passed=True,
                llm_label=classification_result.label.value,
                llm_confidence=confidence
            )
        else:
            decision_reasoning.append("제품 무관 질문 → EXCLUDE")
            return self._create_exclude_decision(
                comment=comment,
                index=index,
                reason="제품과 무관한 질문",
                exclusion_reason=ExclusionReason.OFF_TOPIC_QUESTION,
                exclusion_details="제품과 관련 없는 질문",
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
    
    def _handle_video_reaction(
        self,
        comment: str,
        index: int,
        mentioned_features: List[str],
        decision_reasoning: List[str],
        classification_result: ClassificationResult
    ) -> AgentDecision:
        """VIDEO_REACTION 처리"""
        # 정책: 제품 특성 많이 언급하면 예외
        if self.policy.allow_video_reaction_with_features:
            if len(mentioned_features) >= self.policy.min_product_features_for_analysis:
                decision_reasoning.append(
                    f"영상 반응이지만 제품 특성 {len(mentioned_features)}개 언급 → ANALYZE"
                )
                
                return AgentDecision(
                    index=index,
                    original_comment=comment,
                    final_action=AgentAction.ANALYZE,
                    final_reason=f"영상 반응이지만 제품 특성 다수 언급 ({len(mentioned_features)}개)",
                    should_run_sentiment=True,
                    should_run_aspect_analysis=True,
                    decision_reasoning=" → ".join(decision_reasoning),
                    agent_version=self.policy.version,
                    decision_metadata={
                        "mentioned_features": mentioned_features,
                        "original_label": "VIDEO_REACTION"
                    },
                    decided_at=datetime.now(),
                    rule_filter_passed=True,
                    llm_label=classification_result.label.value,
                    llm_confidence=classification_result.confidence
                )
        
        # 기본: EXCLUDE
        decision_reasoning.append("영상 반응 댓글 → EXCLUDE")
        return self._create_exclude_decision(
            comment=comment,
            index=index,
            reason="영상 반응 댓글 제외",
            exclusion_reason=ExclusionReason.VIDEO_REACTION,
            exclusion_details="영상/리뷰어에 대한 반응",
            decision_reasoning=decision_reasoning,
            classification_result=classification_result
        )
    
    def _handle_chatter(
        self,
        comment: str,
        index: int,
        confidence: float,
        needs_recheck: bool,
        decision_reasoning: List[str],
        classification_result: ClassificationResult
    ) -> AgentDecision:
        """CHATTER 처리"""
        # 재확인 필요하고 확신도 낮으면 재분류
        if needs_recheck and confidence < self.policy.reclassify_priority_high_confidence_threshold:
            decision_reasoning.append(
                f"잡담이지만 재확인 필요 + 낮은 확신도 ({confidence:.2f}) → RECLASSIFY"
            )
            return self._create_reclassify_decision(
                comment=comment,
                index=index,
                reason=f"잡담 분류 재확인 필요 (확신도: {confidence:.2f})",
                decision_reasoning=decision_reasoning,
                classification_result=classification_result
            )
        
        # 기본: EXCLUDE
        decision_reasoning.append("잡담/무의미 댓글 → EXCLUDE")
        return self._create_exclude_decision(
            comment=comment,
            index=index,
            reason="잡담/무의미 댓글 제외",
            exclusion_reason=ExclusionReason.CHATTER,
            exclusion_details="의미 있는 정보 없음",
            decision_reasoning=decision_reasoning,
            classification_result=classification_result
        )
    
    def _handle_off_topic(
        self,
        comment: str,
        index: int,
        decision_reasoning: List[str],
        classification_result: ClassificationResult
    ) -> AgentDecision:
        """OFF_TOPIC 처리"""
        decision_reasoning.append("제품 무관 댓글 → EXCLUDE")
        return self._create_exclude_decision(
            comment=comment,
            index=index,
            reason="제품과 무관한 댓글 제외",
            exclusion_reason=ExclusionReason.OFF_TOPIC,
            exclusion_details="제품과 완전히 무관",
            decision_reasoning=decision_reasoning,
            classification_result=classification_result
        )
    
    # ========================================
    # 유틸리티 메서드
    # ========================================
    
    def _create_exclude_decision(
        self,
        comment: str,
        index: int,
        reason: str,
        exclusion_reason: ExclusionReason,
        exclusion_details: str,
        decision_reasoning: List[str],
        rule_filter_passed: bool = True,
        classification_result: Optional[ClassificationResult] = None
    ) -> AgentDecision:
        """EXCLUDE 결정 생성"""
        return AgentDecision(
            index=index,
            original_comment=comment,
            final_action=AgentAction.EXCLUDE,
            final_reason=reason,
            exclusion_reason=exclusion_reason,
            exclusion_details=exclusion_details,
            decision_reasoning=" → ".join(decision_reasoning),
            agent_version=self.policy.version,
            decided_at=datetime.now(),
            rule_filter_passed=rule_filter_passed,
            llm_label=classification_result.label.value if classification_result else None,
            llm_confidence=classification_result.confidence if classification_result else None
        )
    
    def _create_reclassify_decision(
        self,
        comment: str,
        index: int,
        reason: str,
        decision_reasoning: List[str],
        classification_result: ClassificationResult
    ) -> AgentDecision:
        """RECLASSIFY 결정 생성"""
        return AgentDecision(
            index=index,
            original_comment=comment,
            final_action=AgentAction.RECLASSIFY,
            final_reason=reason,
            should_send_llm_recheck=True,
            needs_reclassification=True,
            is_low_confidence=True,
            decision_reasoning=" → ".join(decision_reasoning),
            agent_version=self.policy.version,
            confidence_threshold=self.policy.reclassify_priority_high_confidence_threshold,
            decided_at=datetime.now(),
            rule_filter_passed=True,
            llm_label=classification_result.label.value,
            llm_confidence=classification_result.confidence
        )
    
    def get_stats(self) -> dict:
        """Agent 통계"""
        return {
            "policy_version": self.policy.version,
            "policy_description": self.policy.description,
            "thresholds": {
                "high_confidence": self.policy.high_confidence_threshold,
                "medium_confidence": self.policy.medium_confidence_threshold,
                "low_confidence": self.policy.low_confidence_threshold,
                "hold_below": self.policy.hold_below_confidence
            },
            "policy_flags": {
                "exclude_all_questions": self.policy.exclude_all_questions,
                "allow_video_reaction_with_features": self.policy.allow_video_reaction_with_features,
                "hold_instead_of_reclassify": self.policy.hold_instead_of_reclassify
            }
        }
