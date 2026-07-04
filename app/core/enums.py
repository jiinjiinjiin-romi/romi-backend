from enum import StrEnum


class AgentPersonality(StrEnum):
    FRIENDLY = "FRIENDLY"
    FORMAL = "FORMAL"
    WARM = "WARM"
    WITTY = "WITTY"


class WarningSensitivity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Theme(StrEnum):
    LIGHT = "LIGHT"
    DARK = "DARK"
    SYSTEM = "SYSTEM"


class PlaceType(StrEnum):
    HOME = "HOME"
    WORK = "WORK"
    SCHOOL = "SCHOOL"
    FAVORITE = "FAVORITE"


class DrivingSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class SessionEndReason(StrEnum):
    USER_REQUEST = "USER_REQUEST"
    CAMERA_LOST = "CAMERA_LOST"
    LOCATION_LOST = "LOCATION_LOST"
    CONNECTION_LOST = "CONNECTION_LOST"
    SERVER_ERROR = "SERVER_ERROR"
    UNKNOWN = "UNKNOWN"


class DrivingState(StrEnum):
    MOVING = "MOVING"
    TEMPORARY_STOP = "TEMPORARY_STOP"
    PARKED = "PARKED"
    UNKNOWN = "UNKNOWN"


class LocationSource(StrEnum):
    GPS = "GPS"
    SIMULATION = "SIMULATION"


class BehaviorType(StrEnum):
    DROWSINESS = "DROWSINESS"
    PHONE_USE = "PHONE_USE"
    FOOD_OR_DRINK = "FOOD_OR_DRINK"
    GAZE_AWAY = "GAZE_AWAY"
    SECONDARY_TASK = "SECONDARY_TASK"
    REACHING_BEHIND = "REACHING_BEHIND"
    SMOKING = "SMOKING"


class BehaviorEventStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class BehaviorEventSource(StrEnum):
    MODEL = "MODEL"
    SIMULATION = "SIMULATION"


class BehaviorResolutionReason(StrEnum):
    BEHAVIOR_CORRECTED = "BEHAVIOR_CORRECTED"
    SESSION_ENDED = "SESSION_ENDED"
    TIMEOUT = "TIMEOUT"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    USER_DISMISSED = "USER_DISMISSED"


class InterventionType(StrEnum):
    WARNING = "WARNING"
    RECOMMENDATION = "RECOMMENDATION"
    TOOL_OFFER = "TOOL_OFFER"


class InterventionGeneratedBy(StrEnum):
    TEMPLATE = "TEMPLATE"
    GEMINI = "GEMINI"


class InterventionStatus(StrEnum):
    CREATED = "CREATED"
    DELIVERED = "DELIVERED"
    WAITING_RESPONSE = "WAITING_RESPONSE"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DriverResponseType(StrEnum):
    BEHAVIOR_CORRECTED = "BEHAVIOR_CORRECTED"
    VOICE_ACCEPTED = "VOICE_ACCEPTED"
    VOICE_REJECTED = "VOICE_REJECTED"
    BUTTON_ACCEPTED = "BUTTON_ACCEPTED"
    BUTTON_DISMISSED = "BUTTON_DISMISSED"
    NO_RESPONSE = "NO_RESPONSE"
    BEHAVIOR_REPEATED = "BEHAVIOR_REPEATED"


class ConversationMode(StrEnum):
    SAFETY = "SAFETY"
    GENERAL_ASSISTANT = "GENERAL_ASSISTANT"


class ConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AgentMessageRole(StrEnum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class AgentInputType(StrEnum):
    VOICE = "VOICE"
    TEXT = "TEXT"
    BUTTON = "BUTTON"
    SYSTEM_EVENT = "SYSTEM_EVENT"


class ToolConfirmationStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ToolExecutionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReportPeriodType(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    CUSTOM = "CUSTOM"


class ReportExportStatus(StrEnum):
    PENDING = "PENDING"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EmailStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class FailureStage(StrEnum):
    EXPORT = "EXPORT"
    EMAIL = "EMAIL"
