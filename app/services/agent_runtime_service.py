from __future__ import annotations

import logging

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import (
    AgentMessageRole,
    ConversationMode,
    ConversationStatus,
    DriverResponseType,
    InterventionGeneratedBy,
    InterventionStatus,
    ToolConfirmationStatus,
    ToolExecutionStatus,
)
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppException
from app.core.time import utc_now_for_mysql_datetime
from app.integrations.gemini.agent_response import (
    GeminiAgentResponseClient,
    GeminiNotConfiguredError,
    GeminiProviderError,
)
from app.models import (
    AgentConversation,
    AgentMessage,
    BehaviorEvent,
    DriverProfile,
    DriverResponse,
    DrivingSession,
    Intervention,
    ToolExecution,
)
from app.policies.agent_demo_policy import plan_agent_reply, plan_intervention_for_behavior
from app.schemas.agent import (
    AgentConversationMessageCreateRequest,
    AgentConversationMessageCreateResponse,
    AgentDriverResponseCreateRequest,
    AgentDriverResponseCreateResponse,
    AgentInterventionPlanRequest,
    AgentInterventionPlanResponse,
    AgentMessageResponse,
    ToolExecutionResponse,
)

logger = logging.getLogger(__name__)


class AgentRuntimeService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        gemini_client: GeminiAgentResponseClient | None = None,
    ) -> None:
        self.session = session
        self.gemini_client = gemini_client or GeminiAgentResponseClient(settings=settings)

    async def plan_intervention(
        self,
        *,
        account_id: str,
        behavior_event_id: str,
        request: AgentInterventionPlanRequest,
    ) -> AgentInterventionPlanResponse:
        try:
            behavior_event, profile = await self._get_owned_behavior_event_for_update(
                account_id=account_id,
                behavior_event_id=behavior_event_id,
            )
            if behavior_event is None or profile is None:
                raise self._not_found("행동 이벤트를 찾을 수 없습니다.")

            plan = plan_intervention_for_behavior(
                behavior_type=behavior_event.behavior_type,
                risk_level=behavior_event.risk_level,
                recurrence_count=behavior_event.recurrence_count,
                average_confidence=behavior_event.average_confidence,
                warning_sensitivity=profile.warning_sensitivity,
                behavior_warning_sensitivity=profile.behavior_warning_sensitivity,
            )
            now = utc_now_for_mysql_datetime()
            intervention = Intervention(
                behavior_event_id=behavior_event.id,
                level=plan.level,
                intervention_type=plan.intervention_type,
                speech_text=plan.speech_text,
                ui_text=plan.ui_text,
                generated_by=InterventionGeneratedBy.TEMPLATE.value,
                channels_json=request.channels,
                status=InterventionStatus.WAITING_RESPONSE.value,
                next_check_after_ms=plan.next_check_after_ms,
                started_at=now,
            )
            conversation = AgentConversation(
                session_id=behavior_event.session_id,
                trigger_behavior_event_id=behavior_event.id,
                mode=ConversationMode.SAFETY.value,
                status=ConversationStatus.ACTIVE.value,
                started_at=now,
            )
            self.session.add_all([intervention, conversation])
            await self.session.flush()
            self.session.add_all(
                [
                    AgentMessage(
                        conversation_id=conversation.id,
                        sequence_no=1,
                        role=AgentMessageRole.SYSTEM.value,
                        text="위험 행동 이벤트를 기준으로 안전 개입을 시작합니다.",
                        intent="SAFETY_INTERVENTION_STARTED",
                        input_type="SYSTEM_EVENT",
                        metadata_json={"behaviorEventId": behavior_event.id},
                        created_at=now,
                    ),
                    AgentMessage(
                        conversation_id=conversation.id,
                        sequence_no=2,
                        role=AgentMessageRole.AGENT.value,
                        text=plan.speech_text,
                        intent="SAFETY_INTERVENTION",
                        input_type="SYSTEM_EVENT",
                        metadata_json={"interventionId": intervention.id, "level": plan.level},
                        created_at=now,
                    ),
                ]
            )
            await self.session.flush()
            await self.session.refresh(intervention)
            await self.session.refresh(conversation)
            await self.session.commit()
            return AgentInterventionPlanResponse(
                id=intervention.id,
                behavior_event_id=intervention.behavior_event_id,
                conversation_id=conversation.id,
                level=intervention.level,
                intervention_type=intervention.intervention_type,
                speech_text=intervention.speech_text,
                ui_text=intervention.ui_text,
                generated_by=intervention.generated_by,
                channels_json=intervention.channels_json,
                status=intervention.status,
                next_check_after_ms=intervention.next_check_after_ms,
                started_at=intervention.started_at,
            )
        except AppException:
            await self.session.rollback()
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            await self.session.rollback()
            logger.exception("Agent intervention planning failed event_id=%s", behavior_event_id)
            raise self._internal_error() from exc

    async def send_message(
        self,
        *,
        account_id: str,
        conversation_id: str,
        request: AgentConversationMessageCreateRequest,
    ) -> AgentConversationMessageCreateResponse:
        try:
            conversation = await self._get_owned_conversation_for_update(
                account_id=account_id,
                conversation_id=conversation_id,
            )
            if conversation is None:
                raise self._not_found("Agent 대화를 찾을 수 없습니다.")
            if conversation.status != ConversationStatus.ACTIVE.value:
                raise AppException(
                    "진행 중인 Agent 대화에만 메시지를 추가할 수 있습니다.",
                    status_code=status.HTTP_409_CONFLICT,
                    error_code=ErrorCode.CONVERSATION_NOT_ACTIVE,
                )

            next_sequence = await self._next_message_sequence(conversation.id)
            now = utc_now_for_mysql_datetime()
            try:
                reply_plan = await self.gemini_client.generate_reply(
                    conversation_mode=conversation.mode,
                    message_text=request.text,
                    input_type=request.input_type.value,
                )
                fallback_mode = None
            except (GeminiNotConfiguredError, GeminiProviderError) as exc:
                logger.info(
                    "Using agent response fallback conversation_id=%s reason=%s",
                    conversation.id,
                    getattr(exc, "reason", "gemini_not_configured"),
                )
                reply_plan = plan_agent_reply(text=request.text)
                fallback_mode = "RULE_BASED"
            user_message = AgentMessage(
                conversation_id=conversation.id,
                sequence_no=next_sequence,
                role=AgentMessageRole.USER.value,
                text=request.text,
                intent=reply_plan.intent,
                input_type=request.input_type.value,
                metadata_json={},
                created_at=now,
            )
            agent_message = AgentMessage(
                conversation_id=conversation.id,
                sequence_no=next_sequence + 1,
                role=AgentMessageRole.AGENT.value,
                text=reply_plan.text,
                intent=reply_plan.intent,
                input_type="SYSTEM_EVENT",
                metadata_json={
                    "agentProvider": "GEMINI",
                    "fallbackMode": fallback_mode,
                },
                created_at=now,
            )
            self.session.add_all([user_message, agent_message])
            await self.session.flush()

            tool_execution = None
            if reply_plan.tool is not None:
                tool_execution = self._build_tool_execution(
                    message_id=agent_message.id,
                    tool=reply_plan.tool,
                    now=now,
                )
                self.session.add(tool_execution)
                await self.session.flush()

            await self.session.commit()
            return AgentConversationMessageCreateResponse(
                conversation_id=conversation.id,
                user_message=self._to_message_response(user_message),
                agent_message=self._to_message_response(agent_message),
                tool_execution=(
                    None if tool_execution is None else self._to_tool_response(tool_execution)
                ),
            )
        except AppException:
            await self.session.rollback()
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            await self.session.rollback()
            logger.exception("Agent message processing failed conversation_id=%s", conversation_id)
            raise self._internal_error() from exc

    async def record_driver_response(
        self,
        *,
        account_id: str,
        intervention_id: str,
        request: AgentDriverResponseCreateRequest,
    ) -> AgentDriverResponseCreateResponse:
        try:
            intervention = await self._get_owned_intervention_for_update(
                account_id=account_id,
                intervention_id=intervention_id,
            )
            if intervention is None:
                raise self._not_found("개입 기록을 찾을 수 없습니다.")

            response = DriverResponse(
                intervention_id=intervention.id,
                response_type=request.response_type.value,
                transcript=request.transcript,
                behavior_corrected=request.behavior_corrected,
                response_latency_ms=request.response_latency_ms,
                responded_at=utc_now_for_mysql_datetime(),
            )
            intervention.status = self._intervention_status_after_response(
                request.response_type,
                request.behavior_corrected,
            )
            intervention.ended_at = response.responded_at
            self.session.add(response)
            await self.session.flush()
            await self.session.refresh(response)
            await self.session.commit()
            return AgentDriverResponseCreateResponse.model_validate(response)
        except AppException:
            await self.session.rollback()
            raise
        except (IntegrityError, SQLAlchemyError) as exc:
            await self.session.rollback()
            logger.exception(
                "Agent driver response recording failed intervention_id=%s",
                intervention_id,
            )
            raise self._internal_error() from exc

    async def _get_owned_behavior_event_for_update(
        self,
        *,
        account_id: str,
        behavior_event_id: str,
    ) -> tuple[BehaviorEvent | None, DriverProfile | None]:
        result = await self.session.execute(
            select(BehaviorEvent, DriverProfile)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .join(DriverProfile, DrivingSession.profile_id == DriverProfile.id)
            .where(
                BehaviorEvent.id == behavior_event_id,
                DriverProfile.account_id == account_id,
            )
            .with_for_update()
        )
        row = result.one_or_none()
        return (None, None) if row is None else row

    async def _get_owned_conversation_for_update(
        self,
        *,
        account_id: str,
        conversation_id: str,
    ) -> AgentConversation | None:
        result = await self.session.execute(
            select(AgentConversation)
            .join(DrivingSession, AgentConversation.session_id == DrivingSession.id)
            .join(DriverProfile, DrivingSession.profile_id == DriverProfile.id)
            .where(
                AgentConversation.id == conversation_id,
                DriverProfile.account_id == account_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _get_owned_intervention_for_update(
        self,
        *,
        account_id: str,
        intervention_id: str,
    ) -> Intervention | None:
        result = await self.session.execute(
            select(Intervention)
            .join(BehaviorEvent, Intervention.behavior_event_id == BehaviorEvent.id)
            .join(DrivingSession, BehaviorEvent.session_id == DrivingSession.id)
            .join(DriverProfile, DrivingSession.profile_id == DriverProfile.id)
            .where(
                Intervention.id == intervention_id,
                DriverProfile.account_id == account_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _next_message_sequence(self, conversation_id: str) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(AgentMessage.sequence_no), 0)).where(
                AgentMessage.conversation_id == conversation_id,
            )
        )
        return int(result.scalar_one()) + 1

    @staticmethod
    def _build_tool_execution(*, message_id: str, tool, now) -> ToolExecution:
        confirmation_status = (
            ToolConfirmationStatus.PENDING.value
            if tool.confirmation_required
            else ToolConfirmationStatus.NOT_REQUIRED.value
        )
        execution_status = (
            ToolExecutionStatus.PENDING.value
            if tool.confirmation_required
            else ToolExecutionStatus.SUCCEEDED.value
        )
        return ToolExecution(
            message_id=message_id,
            tool_name=tool.tool_name,
            arguments_json=tool.arguments,
            result_json=tool.result,
            confirmation_required=tool.confirmation_required,
            confirmation_status=confirmation_status,
            execution_status=execution_status,
            is_simulated=True,
            created_at=now,
            started_at=None if tool.confirmation_required else now,
            completed_at=None if tool.confirmation_required else now,
        )

    @staticmethod
    def _intervention_status_after_response(
        response_type: DriverResponseType,
        behavior_corrected: bool | None,
    ) -> str:
        if response_type in {
            DriverResponseType.BEHAVIOR_REPEATED,
            DriverResponseType.NO_RESPONSE,
        }:
            return InterventionStatus.ESCALATED.value
        if response_type in {
            DriverResponseType.BUTTON_DISMISSED,
            DriverResponseType.VOICE_REJECTED,
        }:
            return InterventionStatus.CANCELLED.value
        if behavior_corrected is False:
            return InterventionStatus.ESCALATED.value
        return InterventionStatus.RESOLVED.value

    @staticmethod
    def _to_message_response(message: AgentMessage) -> AgentMessageResponse:
        return AgentMessageResponse(
            id=message.id,
            sequence_no=message.sequence_no,
            role=message.role,
            text=message.text,
            intent=message.intent,
            input_type=message.input_type,
            created_at=message.created_at,
        )

    @staticmethod
    def _to_tool_response(tool_execution: ToolExecution) -> ToolExecutionResponse:
        return ToolExecutionResponse.model_validate(tool_execution)

    @staticmethod
    def _not_found(message: str) -> AppException:
        return AppException(
            message,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=ErrorCode.NOT_FOUND,
        )

    @staticmethod
    def _internal_error() -> AppException:
        return AppException(
            "Agent 실행 흐름을 처리하지 못했습니다.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=ErrorCode.INTERNAL_SERVER_ERROR,
        )
