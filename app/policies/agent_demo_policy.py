from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.enums import BehaviorType, InterventionType, WarningSensitivity


@dataclass(frozen=True, slots=True)
class InterventionPlan:
    level: int
    intervention_type: str
    speech_text: str
    ui_text: str
    next_check_after_ms: int


@dataclass(frozen=True, slots=True)
class ToolPlan:
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    confirmation_required: bool
    intent: str


@dataclass(frozen=True, slots=True)
class AgentReplyPlan:
    intent: str
    text: str
    tool: ToolPlan | None = None


BEHAVIOR_TEXT: dict[str, tuple[str, str]] = {
    BehaviorType.DROWSINESS.value: (
        "졸음 징후가 감지됐습니다. 잠시 환기하고 가까운 휴식 지점을 확인해 주세요.",
        "졸음 징후가 감지되었습니다.",
    ),
    BehaviorType.PHONE_USE.value: (
        "휴대폰 사용이 감지됐습니다. 시선은 전방에 두고 필요한 작업은 제가 도와드릴게요.",
        "휴대폰 사용 위험이 감지되었습니다.",
    ),
    BehaviorType.FOOD_OR_DRINK.value: (
        "음식 또는 음료 섭취가 감지됐습니다. 조작이 필요한 상황이면 잠시 정차해 주세요.",
        "음식 또는 음료 섭취 위험이 감지되었습니다.",
    ),
    BehaviorType.GAZE_AWAY.value: (
        "전방 주시가 흐트러졌습니다. 도로 상황을 다시 확인해 주세요.",
        "전방 주시 이탈이 감지되었습니다.",
    ),
    BehaviorType.SECONDARY_TASK.value: (
        "보조 작업이 감지됐습니다. 필요한 요청은 음성으로 말씀해 주세요.",
        "운전 외 작업 위험이 감지되었습니다.",
    ),
    BehaviorType.REACHING_BEHIND.value: (
        "뒤쪽을 향한 움직임이 감지됐습니다. 차량이 안정된 뒤 확인해 주세요.",
        "후방 물건 조작 위험이 감지되었습니다.",
    ),
    BehaviorType.SMOKING.value: (
        "흡연 동작이 감지됐습니다. 주행 중 한 손 조작을 줄여 주세요.",
        "흡연 관련 위험 동작이 감지되었습니다.",
    ),
}


def plan_intervention_for_behavior(
    *,
    behavior_type: str,
    risk_level: int,
    recurrence_count: int,
    average_confidence: Decimal,
    warning_sensitivity: str,
    behavior_warning_sensitivity: dict[str, int],
) -> InterventionPlan:
    base_level = max(1, min(3, risk_level if risk_level > 0 else 1))
    sensitivity_value = int(behavior_warning_sensitivity.get(behavior_type, 7))
    sensitivity_boost = 1 if sensitivity_value >= 9 else 0
    recurrence_boost = 1 if recurrence_count >= 2 else 0
    profile_boost = 1 if warning_sensitivity == WarningSensitivity.HIGH.value else 0
    confidence_boost = 1 if average_confidence >= Decimal("0.8500") else 0
    raw_level = (
        base_level
        + sensitivity_boost
        + recurrence_boost
        + profile_boost
        + confidence_boost
    )
    level = max(1, min(3, raw_level))

    speech_text, ui_text = BEHAVIOR_TEXT.get(
        behavior_type,
        (
            "위험 행동이 감지됐습니다. 주행에 집중해 주세요.",
            "위험 행동이 감지되었습니다.",
        ),
    )
    intervention_type = (
        InterventionType.TOOL_OFFER.value if level >= 3 else InterventionType.WARNING.value
    )
    next_check_after_ms = {1: 5000, 2: 3500, 3: 2000}[level]
    return InterventionPlan(
        level=level,
        intervention_type=intervention_type,
        speech_text=speech_text,
        ui_text=ui_text,
        next_check_after_ms=next_check_after_ms,
    )


def plan_agent_reply(*, text: str) -> AgentReplyPlan:
    normalized = text.strip().lower()
    if any(keyword in normalized for keyword in ("노래", "음악", "music", "틀어", "재생")):
        return AgentReplyPlan(
            intent="PLAY_MUSIC",
            text="운전에 방해되지 않는 밝은 주행 음악을 준비했습니다.",
            tool=ToolPlan(
                tool_name="music.play",
                arguments={"mood": "drive", "source": "agent"},
                result={"status": "READY", "executionMode": "SIMULATED"},
                confirmation_required=False,
                intent="PLAY_MUSIC",
            ),
        )
    if any(keyword in normalized for keyword in ("문자", "메시지", "보내", "전송", "message")):
        return AgentReplyPlan(
            intent="SEND_MESSAGE",
            text="메시지 전송은 확인이 필요합니다. 승인하면 안전한 시점에 전송 요청을 실행합니다.",
            tool=ToolPlan(
                tool_name="message.prepare",
                arguments={"channel": "sms", "requiresDriverConfirmation": True},
                result=None,
                confirmation_required=True,
                intent="SEND_MESSAGE",
            ),
        )
    if any(keyword in normalized for keyword in ("근처", "찾아", "검색", "장소", "place")):
        return AgentReplyPlan(
            intent="SEARCH_PLACE",
            text="주변 후보를 검색해 경로 안내에 사용할 수 있도록 준비했습니다.",
            tool=ToolPlan(
                tool_name="place.search",
                arguments={"query": text.strip(), "scope": "nearby"},
                result={"status": "READY", "candidateCount": 3},
                confirmation_required=False,
                intent="SEARCH_PLACE",
            ),
        )
    if any(keyword in normalized for keyword in ("경로", "길", "우회", "route")):
        return AgentReplyPlan(
            intent="UPDATE_ROUTE",
            text="현재 주행 상황을 기준으로 경로 변경 가능성을 확인했습니다.",
            tool=ToolPlan(
                tool_name="route.review",
                arguments={"request": text.strip()},
                result={"status": "READY", "routeChangeAvailable": True},
                confirmation_required=False,
                intent="UPDATE_ROUTE",
            ),
        )
    return AgentReplyPlan(
        intent="SAFE_ASSISTANT_FALLBACK",
        text="운전 중에는 안전과 주행 보조에 필요한 요청을 우선 도와드릴게요.",
    )
