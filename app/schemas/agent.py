from datetime import datetime

from pydantic import Field, field_serializer, field_validator
from pydantic_core import PydanticCustomError

from app.core.enums import AgentInputType, ConversationMode, DriverResponseType
from app.core.error_codes import ErrorCode
from app.core.time import format_utc_datetime
from app.schemas.base import ApiBaseModel, ApiRequestModel

INVALID_CONVERSATION_MODE_MESSAGE = "지원하지 않는 Agent 대화 모드입니다."


class AgentConversationCreateRequest(ApiRequestModel):
    mode: str = Field(json_schema_extra={"enum": [ConversationMode.GENERAL_ASSISTANT.value]})

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, value: object) -> str:
        if not isinstance(value, str):
            raise PydanticCustomError(
                ErrorCode.INVALID_CONVERSATION_MODE.value,
                INVALID_CONVERSATION_MODE_MESSAGE,
            )

        if value not in {
            ConversationMode.GENERAL_ASSISTANT.value,
            ConversationMode.SAFETY.value,
        }:
            raise PydanticCustomError(
                ErrorCode.INVALID_CONVERSATION_MODE.value,
                INVALID_CONVERSATION_MODE_MESSAGE,
            )

        return value


class AgentConversationCreateResponse(ApiBaseModel):
    id: str
    session_id: str
    mode: str
    status: str
    started_at: datetime

    @field_serializer("started_at")
    def serialize_started_at(self, value: datetime) -> str:
        return format_utc_datetime(value)


class AgentMessageResponse(ApiBaseModel):
    id: str
    sequence_no: int
    role: str
    text: str | None
    intent: str | None
    input_type: str | None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return format_utc_datetime(value)


class AgentConversationDetailResponse(ApiBaseModel):
    id: str
    session_id: str
    mode: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    messages: list[AgentMessageResponse]

    @field_serializer("started_at", "ended_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc_datetime(value)


class AgentConversationMessageCreateRequest(ApiRequestModel):
    text: str = Field(min_length=1, max_length=1000)
    input_type: AgentInputType = AgentInputType.TEXT

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("Agent message text must not be empty.")
        return text


class ToolExecutionResponse(ApiBaseModel):
    id: str
    tool_name: str
    arguments_json: dict
    result_json: dict | None
    confirmation_required: bool
    confirmation_status: str
    execution_status: str
    is_simulated: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @field_serializer("created_at", "started_at", "completed_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return None if value is None else format_utc_datetime(value)


class AgentConversationMessageCreateResponse(ApiBaseModel):
    conversation_id: str
    user_message: AgentMessageResponse
    agent_message: AgentMessageResponse
    tool_execution: ToolExecutionResponse | None = None


class AgentInterventionPlanRequest(ApiRequestModel):
    channels: list[str] = Field(default_factory=lambda: ["VOICE", "VISUAL"], min_length=1)

    @field_validator("channels")
    @classmethod
    def normalize_channels(cls, channels: list[str]) -> list[str]:
        normalized = [str(channel).strip().upper() for channel in channels if str(channel).strip()]
        if not normalized:
            raise ValueError("Intervention channels must not be empty.")
        return list(dict.fromkeys(normalized))


class AgentInterventionPlanResponse(ApiBaseModel):
    id: str
    behavior_event_id: str
    conversation_id: str
    level: int
    intervention_type: str
    speech_text: str | None
    ui_text: str
    generated_by: str
    channels_json: list[str]
    status: str
    next_check_after_ms: int | None
    started_at: datetime

    @field_serializer("started_at")
    def serialize_started_at(self, value: datetime) -> str:
        return format_utc_datetime(value)


class AgentDriverResponseCreateRequest(ApiRequestModel):
    response_type: DriverResponseType
    transcript: str | None = Field(default=None, max_length=1000)
    behavior_corrected: bool | None = None
    response_latency_ms: int | None = Field(default=None, ge=0)

    @field_validator("transcript", mode="before")
    @classmethod
    def normalize_transcript(cls, value: object) -> str | None:
        if value is None:
            return None
        transcript = str(value).strip()
        return transcript or None


class AgentDriverResponseCreateResponse(ApiBaseModel):
    id: str
    intervention_id: str
    response_type: str
    transcript: str | None
    behavior_corrected: bool | None
    response_latency_ms: int | None
    responded_at: datetime

    @field_serializer("responded_at")
    def serialize_responded_at(self, value: datetime) -> str:
        return format_utc_datetime(value)
