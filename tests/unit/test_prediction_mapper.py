import pytest

from app.ai.driver_monitoring import DetectionBehaviorType, ModelActionType
from app.ai.prediction_mapper import (
    MODEL_ACTION_METADATA,
    map_action_to_detection_behavior,
    metadata_from_action_type,
    metadata_from_class_code,
    metadata_from_class_index,
    metadata_from_class_label,
)

EXPECTED_3MDAD_MAPPING = [
    (0, "AC1", "safe_driving", ModelActionType.SAFE_DRIVING, DetectionBehaviorType.NORMAL),
    (1, "AC2", "hair_makeup", ModelActionType.HAIR_MAKEUP, DetectionBehaviorType.SECONDARY_TASK),
    (
        2,
        "AC3",
        "adjusting_radio",
        ModelActionType.ADJUSTING_RADIO,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    (
        3,
        "AC4",
        "gps_operating",
        ModelActionType.GPS_OPERATING,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    (
        4,
        "AC5",
        "writing_msg_right",
        ModelActionType.WRITING_MSG_RIGHT,
        DetectionBehaviorType.PHONE_USE,
    ),
    (
        5,
        "AC6",
        "writing_msg_left",
        ModelActionType.WRITING_MSG_LEFT,
        DetectionBehaviorType.PHONE_USE,
    ),
    (
        6,
        "AC7",
        "talking_phone_right",
        ModelActionType.TALKING_PHONE_RIGHT,
        DetectionBehaviorType.PHONE_USE,
    ),
    (
        7,
        "AC8",
        "talking_phone_left",
        ModelActionType.TALKING_PHONE_LEFT,
        DetectionBehaviorType.PHONE_USE,
    ),
    (
        8,
        "AC9",
        "taking_picture",
        ModelActionType.TAKING_PICTURE,
        DetectionBehaviorType.PHONE_USE,
    ),
    (
        9,
        "AC10",
        "talking_passenger",
        ModelActionType.TALKING_PASSENGER,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    (
        10,
        "AC11",
        "singing_dancing",
        ModelActionType.SINGING_DANCING,
        DetectionBehaviorType.SECONDARY_TASK,
    ),
    (
        11,
        "AC12",
        "fatigue_somnolence",
        ModelActionType.FATIGUE_SOMNOLENCE,
        DetectionBehaviorType.DROWSINESS,
    ),
    (
        12,
        "AC13",
        "drinking_right",
        ModelActionType.DRINKING_RIGHT,
        DetectionBehaviorType.FOOD_OR_DRINK,
    ),
    (
        13,
        "AC14",
        "drinking_left",
        ModelActionType.DRINKING_LEFT,
        DetectionBehaviorType.FOOD_OR_DRINK,
    ),
    (
        14,
        "AC15",
        "reaching_behind",
        ModelActionType.REACHING_BEHIND,
        DetectionBehaviorType.REACHING_BEHIND,
    ),
    (15, "AC16", "smoking", ModelActionType.SMOKING, DetectionBehaviorType.SMOKING),
]


def test_detection_behavior_type_includes_runtime_detection_categories() -> None:
    assert {item.value for item in DetectionBehaviorType} == {
        "NORMAL",
        "DROWSINESS",
        "PHONE_USE",
        "FOOD_OR_DRINK",
        "GAZE_AWAY",
        "SECONDARY_TASK",
        "REACHING_BEHIND",
        "SMOKING",
    }


def test_model_action_type_matches_3mdad_16_class_actions() -> None:
    assert [item for item in ModelActionType] == [row[3] for row in EXPECTED_3MDAD_MAPPING]


def test_3mdad_metadata_mapping_is_complete_and_unique() -> None:
    rows = [
        (
            metadata.class_index,
            metadata.class_code,
            metadata.class_label,
            metadata.action_type,
            metadata.detection_behavior_type,
        )
        for metadata in MODEL_ACTION_METADATA
    ]

    assert rows == EXPECTED_3MDAD_MAPPING
    assert [metadata.class_index for metadata in MODEL_ACTION_METADATA] == list(range(16))
    assert [metadata.class_code for metadata in MODEL_ACTION_METADATA] == [
        f"AC{number}" for number in range(1, 17)
    ]
    assert len({metadata.class_code for metadata in MODEL_ACTION_METADATA}) == 16
    assert len({metadata.class_label for metadata in MODEL_ACTION_METADATA}) == 16
    assert len({metadata.action_type for metadata in MODEL_ACTION_METADATA}) == 16
    assert DetectionBehaviorType.GAZE_AWAY not in {
        metadata.detection_behavior_type for metadata in MODEL_ACTION_METADATA
    }


@pytest.mark.parametrize(
    ("index", "action_type", "behavior_type"),
    [
        (0, ModelActionType.SAFE_DRIVING, DetectionBehaviorType.NORMAL),
        (4, ModelActionType.WRITING_MSG_RIGHT, DetectionBehaviorType.PHONE_USE),
        (11, ModelActionType.FATIGUE_SOMNOLENCE, DetectionBehaviorType.DROWSINESS),
        (14, ModelActionType.REACHING_BEHIND, DetectionBehaviorType.REACHING_BEHIND),
        (15, ModelActionType.SMOKING, DetectionBehaviorType.SMOKING),
    ],
)
def test_metadata_from_class_index_maps_expected_examples(
    index: int,
    action_type: ModelActionType,
    behavior_type: DetectionBehaviorType,
) -> None:
    metadata = metadata_from_class_index(index)

    assert metadata.action_type == action_type
    assert metadata.detection_behavior_type == behavior_type


def test_metadata_lookup_by_code_label_and_action_type() -> None:
    by_code = metadata_from_class_code("AC5")
    by_label = metadata_from_class_label("writing_msg_right")
    by_action = metadata_from_action_type(ModelActionType.WRITING_MSG_RIGHT)

    assert by_code is by_label
    assert by_code is by_action
    assert by_code.class_index == 4
    assert by_code.action_type == ModelActionType.WRITING_MSG_RIGHT
    assert map_action_to_detection_behavior(ModelActionType.WRITING_MSG_RIGHT) == (
        DetectionBehaviorType.PHONE_USE
    )


@pytest.mark.parametrize("index", [-1, 16])
def test_unknown_class_index_is_rejected(index: int) -> None:
    with pytest.raises(ValueError):
        metadata_from_class_index(index)


@pytest.mark.parametrize("class_code", ["", "AC0", "AC17", "ac5"])
def test_unknown_class_code_is_rejected(class_code: str) -> None:
    with pytest.raises(ValueError):
        metadata_from_class_code(class_code)


@pytest.mark.parametrize("class_label", ["", "safe-driving", "unknown"])
def test_unknown_class_label_is_rejected(class_label: str) -> None:
    with pytest.raises(ValueError):
        metadata_from_class_label(class_label)
