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
