from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from app.ai.driver_monitoring import DetectionBehaviorType, ModelActionType


@dataclass(frozen=True, slots=True)
class ModelActionMetadata:
    class_index: int
    class_code: str
    class_label: str
    action_type: ModelActionType
    detection_behavior_type: DetectionBehaviorType


MODEL_ACTION_METADATA: tuple[ModelActionMetadata, ...] = (
    ModelActionMetadata(
        0,
        "AC1",
        "safe_driving",
        ModelActionType.SAFE_DRIVING,
        DetectionBehaviorType.NORMAL,
    ),
    ModelActionMetadata(
        1,
        "AC2",
        "hair_makeup",
        ModelActionType.HAIR_MAKEUP,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    ModelActionMetadata(
        2,
        "AC3",
        "adjusting_radio",
        ModelActionType.ADJUSTING_RADIO,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    ModelActionMetadata(
        3,
        "AC4",
        "gps_operating",
        ModelActionType.GPS_OPERATING,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    ModelActionMetadata(
        4,
        "AC5",
        "writing_msg_right",
        ModelActionType.WRITING_MSG_RIGHT,
        DetectionBehaviorType.PHONE_USE,
    ),
    ModelActionMetadata(
        5,
        "AC6",
        "writing_msg_left",
        ModelActionType.WRITING_MSG_LEFT,
        DetectionBehaviorType.PHONE_USE,
    ),
    ModelActionMetadata(
        6,
        "AC7",
        "talking_phone_right",
        ModelActionType.TALKING_PHONE_RIGHT,
        DetectionBehaviorType.PHONE_USE,
    ),
    ModelActionMetadata(
        7,
        "AC8",
        "talking_phone_left",
        ModelActionType.TALKING_PHONE_LEFT,
        DetectionBehaviorType.PHONE_USE,
    ),
    ModelActionMetadata(
        8,
        "AC9",
        "taking_picture",
        ModelActionType.TAKING_PICTURE,
        DetectionBehaviorType.PHONE_USE,
    ),
    ModelActionMetadata(
        9,
        "AC10",
        "talking_passenger",
        ModelActionType.TALKING_PASSENGER,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    ModelActionMetadata(
        10,
        "AC11",
        "singing_dancing",
        ModelActionType.SINGING_DANCING,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    ModelActionMetadata(
        11,
        "AC12",
        "fatigue_somnolence",
        ModelActionType.FATIGUE_SOMNOLENCE,
        DetectionBehaviorType.DROWSINESS,
    ),
    ModelActionMetadata(
        12,
        "AC13",
        "drinking_right",
        ModelActionType.DRINKING_RIGHT,
        DetectionBehaviorType.FOOD_OR_DRINK,
    ),
    ModelActionMetadata(
        13,
        "AC14",
        "drinking_left",
        ModelActionType.DRINKING_LEFT,
        DetectionBehaviorType.FOOD_OR_DRINK,
    ),
    ModelActionMetadata(
        14,
        "AC15",
        "reaching_behind",
        ModelActionType.REACHING_BEHIND,
        DetectionBehaviorType.REACHING_BEHIND,
    ),
    ModelActionMetadata(
        15,
        "AC16",
        "smoking",
        ModelActionType.SMOKING,
        DetectionBehaviorType.SMOKING,
    ),
)

_METADATA_BY_CLASS_INDEX = MappingProxyType(
    {metadata.class_index: metadata for metadata in MODEL_ACTION_METADATA}
)
_METADATA_BY_CLASS_CODE = MappingProxyType(
    {metadata.class_code: metadata for metadata in MODEL_ACTION_METADATA}
)
_METADATA_BY_CLASS_LABEL = MappingProxyType(
    {metadata.class_label: metadata for metadata in MODEL_ACTION_METADATA}
)
_METADATA_BY_ACTION_TYPE = MappingProxyType(
    {metadata.action_type: metadata for metadata in MODEL_ACTION_METADATA}
)


def metadata_from_class_index(index: int) -> ModelActionMetadata:
    try:
        return _METADATA_BY_CLASS_INDEX[index]
    except KeyError as exc:
        raise ValueError(f"Unknown model class index: {index}.") from exc


def metadata_from_class_code(class_code: str) -> ModelActionMetadata:
    try:
        return _METADATA_BY_CLASS_CODE[class_code]
    except KeyError as exc:
        raise ValueError(f"Unknown model class code: {class_code}.") from exc


def metadata_from_class_label(class_label: str) -> ModelActionMetadata:
    try:
        return _METADATA_BY_CLASS_LABEL[class_label]
    except KeyError as exc:
        raise ValueError(f"Unknown model class label: {class_label}.") from exc


def metadata_from_action_type(action_type: ModelActionType) -> ModelActionMetadata:
    try:
        return _METADATA_BY_ACTION_TYPE[action_type]
    except KeyError as exc:
        raise ValueError(f"Unknown model action type: {action_type}.") from exc


def map_action_to_detection_behavior(action_type: ModelActionType) -> DetectionBehaviorType:
    return metadata_from_action_type(action_type).detection_behavior_type
