from datetime import datetime

from pydantic import Field, field_serializer, field_validator
from pydantic_core import PydanticCustomError

from app.core.enums import ConversationMode
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
