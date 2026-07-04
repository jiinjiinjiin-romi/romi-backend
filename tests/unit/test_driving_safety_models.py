import pytest
from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.ai.driver_monitoring import DetectionBehaviorType, ModelActionType
from app.core.enums import (
    BehaviorEventSource,
    BehaviorEventStatus,
    BehaviorResolutionReason,
    BehaviorType,
    DriverResponseType,
    DrivingSessionStatus,
    DrivingState,
    InterventionGeneratedBy,
    InterventionStatus,
    InterventionType,
    LocationSource,
    SessionEndReason,
)
from app.models import (
    BehaviorEvent,
    DriverProfile,
    DriverResponse,
    DrivingSession,
    Intervention,
    LocationSample,
)


def constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def check_constraint_sql(model: type, name: str) -> str:
    constraint = next(
        constraint
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    )
    return str(constraint.sqltext)


def unique_constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def index_names(model: type) -> set[str]:
    return {index.name for index in model.__table__.indexes if isinstance(index, Index)}


def test_driving_session_model_columns_generated_column_and_defaults() -> None:
    table = DrivingSession.__table__

    assert table.name == "driving_sessions"
    assert set(table.columns.keys()) == {
        "id",
        "profile_id",
        "active_profile_id",
        "started_at",
        "ended_at",
        "status",
        "end_reason",
        "start_latitude",
        "start_longitude",
        "end_latitude",
        "end_longitude",
        "destination_name",
        "destination_place_id",
        "distance_meters",
        "duration_seconds",
        "average_speed_kph",
        "safety_score",
        "model_version",
        "policy_version",
        "created_at",
        "updated_at",
    }
    assert isinstance(table.c.id.type, CHAR)
    assert table.c.id.type.length == 36
    assert table.c.id.default is not None
    assert isinstance(table.c.active_profile_id.computed, Computed)
    assert table.c.active_profile_id.computed.persisted is False
    assert "status = 'ACTIVE'" in str(table.c.active_profile_id.computed.sqltext)
    assert isinstance(table.c.started_at.type, mysql.DATETIME)
    assert table.c.started_at.type.fsp == 6
    assert isinstance(table.c.status.type, String)
    assert table.c.status.default.arg == DrivingSessionStatus.ACTIVE.value
    assert isinstance(table.c.distance_meters.type, mysql.BIGINT)
    assert table.c.distance_meters.type.unsigned
    assert table.c.distance_meters.default.arg == 0
    assert isinstance(table.c.duration_seconds.type, mysql.INTEGER)
    assert table.c.duration_seconds.type.unsigned
    assert table.c.duration_seconds.default.arg == 0
    assert isinstance(table.c.average_speed_kph.type, mysql.DECIMAL)
    assert table.c.average_speed_kph.type.precision == 6
    assert table.c.average_speed_kph.type.scale == 2
    assert isinstance(table.c.safety_score.type, mysql.TINYINT)
    assert table.c.safety_score.type.unsigned
    assert isinstance(table.c.model_version.type, String)
    assert table.c.model_version.type.length == 50


def test_driving_session_constraints_indexes_fk_and_relationships() -> None:
    table = DrivingSession.__table__

    assert constraint_names(DrivingSession) == {
        "ck_driving_sessions_status",
        "ck_driving_sessions_end_reason",
        "ck_driving_sessions_ended_at_after_started_at",
        "ck_driving_sessions_status_end_state",
        "ck_driving_sessions_safety_score",
        "ck_driving_sessions_average_speed_kph",
        "ck_driving_sessions_start_latitude",
        "ck_driving_sessions_start_longitude",
        "ck_driving_sessions_end_latitude",
        "ck_driving_sessions_end_longitude",
        "ck_driving_sessions_start_coordinates_pair",
        "ck_driving_sessions_end_coordinates_pair",
    }
    assert unique_constraint_names(DrivingSession) == {"uq_driving_sessions_active_profile"}
    assert {"idx_driving_sessions_profile_time", "idx_driving_sessions_status"} <= index_names(
        DrivingSession
    )

    fk = next(iter(table.c.profile_id.foreign_keys))
    assert isinstance(fk, ForeignKey)
    assert fk.target_fullname == "driver_profiles.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert fk.constraint.name == "fk_driving_sessions_profile_id_driver_profiles"
    assert DriverProfile.driving_sessions.property.back_populates == "profile"
    assert DrivingSession.profile.property.back_populates == "driving_sessions"
    assert DrivingSession.location_samples.property.cascade.delete_orphan
    assert DrivingSession.behavior_events.property.cascade.delete_orphan


def test_location_sample_model_schema_constraints_and_relationship() -> None:
    table = LocationSample.__table__

    assert table.name == "location_samples"
    assert isinstance(table.c.id.type, mysql.BIGINT)
    assert table.c.id.type.unsigned
    assert table.c.id.autoincrement is True
    assert isinstance(table.c.latitude.type, mysql.DOUBLE)
    assert isinstance(table.c.longitude.type, mysql.DOUBLE)
    assert isinstance(table.c.speed_kph.type, mysql.DECIMAL)
    assert table.c.speed_kph.type.precision == 6
    assert isinstance(table.c.accuracy_meters.type, mysql.DECIMAL)
    assert table.c.accuracy_meters.type.precision == 8
    assert isinstance(table.c.source.type, String)
    assert table.c.source.default.arg == LocationSource.GPS.value
    assert isinstance(table.c.recorded_at.type, mysql.DATETIME)
    assert table.c.recorded_at.type.fsp == 6
    assert unique_constraint_names(LocationSample) == {"uq_location_samples_time"}
    assert index_names(LocationSample) == set()
    assert constraint_names(LocationSample) == {
        "ck_location_samples_latitude",
        "ck_location_samples_longitude",
        "ck_location_samples_speed_kph",
        "ck_location_samples_accuracy_meters",
        "ck_location_samples_driving_state",
        "ck_location_samples_source",
    }
    fk = next(iter(table.c.session_id.foreign_keys))
    assert fk.target_fullname == "driving_sessions.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert LocationSample.session.property.back_populates == "location_samples"


def test_behavior_event_model_schema_constraints_and_relationship() -> None:
    table = BehaviorEvent.__table__

    assert table.name == "behavior_events"
    assert isinstance(table.c.id.type, CHAR)
    assert table.c.id.default is not None
    assert isinstance(table.c.behavior_type.type, String)
    assert table.c.behavior_type.type.length == 30
    assert table.c.status.default.arg == BehaviorEventStatus.ACTIVE.value
    assert table.c.source.default.arg == BehaviorEventSource.MODEL.value
    assert isinstance(table.c.duration_ms.type, mysql.INTEGER)
    assert table.c.duration_ms.type.unsigned
    assert isinstance(table.c.average_confidence.type, mysql.DECIMAL)
    assert table.c.average_confidence.type.precision == 5
    assert table.c.average_confidence.type.scale == 4
    assert isinstance(table.c.risk_level.type, mysql.TINYINT)
    assert table.c.risk_level.type.unsigned
    assert table.c.risk_level.default.arg == 0
    assert isinstance(table.c.recurrence_count.type, mysql.SMALLINT)
    assert table.c.recurrence_count.type.unsigned
    assert table.c.recurrence_count.default.arg == 0
    assert constraint_names(BehaviorEvent) == {
        "ck_behavior_events_behavior_type",
        "ck_behavior_events_status",
        "ck_behavior_events_source",
        "ck_behavior_events_driving_state",
        "ck_behavior_events_resolution_reason",
        "ck_behavior_events_average_confidence",
        "ck_behavior_events_maximum_confidence",
        "ck_behavior_events_confidence_order",
        "ck_behavior_events_risk_level",
        "ck_behavior_events_ended_at_after_started_at",
        "ck_behavior_events_status_end_state",
        "ck_behavior_events_speed_kph",
        "ck_behavior_events_latitude",
        "ck_behavior_events_longitude",
        "ck_behavior_events_coordinates_pair",
    }
    assert {
        "idx_behavior_events_session_time",
        "idx_behavior_events_type_time",
        "idx_behavior_events_status",
    } <= index_names(BehaviorEvent)
    behavior_type_check = check_constraint_sql(
        BehaviorEvent,
        "ck_behavior_events_behavior_type",
    )
    assert all(
        behavior_type in behavior_type_check
        for behavior_type in {
            "DROWSINESS",
            "PHONE_USE",
            "FOOD_OR_DRINK",
            "GAZE_AWAY",
            "SECONDARY_TASK",
            "REACHING_BEHIND",
            "SMOKING",
        }
    )
    assert "NORMAL" not in behavior_type_check
    assert "SAFE_DRIVING" not in behavior_type_check
    fk = next(iter(table.c.session_id.foreign_keys))
    assert fk.target_fullname == "driving_sessions.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert BehaviorEvent.session.property.back_populates == "behavior_events"
    assert BehaviorEvent.interventions.property.cascade.delete_orphan


def test_intervention_model_schema_constraints_json_and_relationship() -> None:
    table = Intervention.__table__

    assert table.name == "interventions"
    assert isinstance(table.c.level.type, mysql.TINYINT)
    assert table.c.level.type.unsigned
    assert isinstance(table.c.speech_text.type, Text)
    assert table.c.speech_text.nullable
    assert isinstance(table.c.ui_text.type, Text)
    assert not table.c.ui_text.nullable
    assert table.c.generated_by.default.arg == InterventionGeneratedBy.TEMPLATE.value
    assert isinstance(table.c.channels_json.type, mysql.JSON)
    assert table.c.channels_json.default is None
    assert not table.c.channels_json.nullable
    assert table.c.status.default.arg == InterventionStatus.CREATED.value
    assert isinstance(table.c.next_check_after_ms.type, mysql.INTEGER)
    assert table.c.next_check_after_ms.type.unsigned
    assert constraint_names(Intervention) == {
        "ck_interventions_level",
        "ck_interventions_intervention_type",
        "ck_interventions_generated_by",
        "ck_interventions_status",
        "ck_interventions_ended_at_after_started_at",
    }
    assert {"idx_interventions_event_time", "idx_interventions_status"} <= index_names(
        Intervention
    )
    fk = next(iter(table.c.behavior_event_id.foreign_keys))
    assert fk.target_fullname == "behavior_events.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert Intervention.behavior_event.property.back_populates == "interventions"
    assert Intervention.driver_responses.property.cascade.delete_orphan


def test_driver_response_model_schema_constraints_and_relationship() -> None:
    table = DriverResponse.__table__

    assert table.name == "driver_responses"
    assert isinstance(table.c.id.type, CHAR)
    assert table.c.id.default is not None
    assert isinstance(table.c.response_type.type, String)
    assert table.c.response_type.type.length == 30
    assert isinstance(table.c.transcript.type, Text)
    assert table.c.transcript.nullable
    assert isinstance(table.c.behavior_corrected.type, Boolean)
    assert table.c.behavior_corrected.nullable
    assert isinstance(table.c.response_latency_ms.type, mysql.INTEGER)
    assert table.c.response_latency_ms.type.unsigned
    assert isinstance(table.c.responded_at.type, mysql.DATETIME)
    assert table.c.responded_at.type.fsp == 6
    assert constraint_names(DriverResponse) == {"ck_driver_responses_response_type"}
    assert "idx_driver_responses_intervention_time" in index_names(DriverResponse)
    fk = next(iter(table.c.intervention_id.foreign_keys))
    assert fk.target_fullname == "interventions.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert DriverResponse.intervention.property.back_populates == "driver_responses"


def test_driving_and_safety_enum_values() -> None:
    assert {item.value for item in DrivingSessionStatus} == {"ACTIVE", "COMPLETED", "ABORTED"}
    assert {item.value for item in SessionEndReason} == {
        "USER_REQUEST",
        "CAMERA_LOST",
        "LOCATION_LOST",
        "CONNECTION_LOST",
        "SERVER_ERROR",
        "UNKNOWN",
    }
    assert {item.value for item in DrivingState} == {
        "MOVING",
        "TEMPORARY_STOP",
        "PARKED",
        "UNKNOWN",
    }
    assert {item.value for item in BehaviorType} == {
        "DROWSINESS",
        "PHONE_USE",
        "FOOD_OR_DRINK",
        "GAZE_AWAY",
        "SECONDARY_TASK",
        "REACHING_BEHIND",
        "SMOKING",
    }
    assert "NORMAL" not in {item.value for item in BehaviorType}
    with pytest.raises(ValueError):
        BehaviorType("NORMAL")
    assert DetectionBehaviorType.NORMAL.value == "NORMAL"
    with pytest.raises(ValueError):
        BehaviorType(ModelActionType.SAFE_DRIVING.value)
    assert {item.value for item in BehaviorResolutionReason} == {
        "BEHAVIOR_CORRECTED",
        "SESSION_ENDED",
        "TIMEOUT",
        "FALSE_POSITIVE",
        "USER_DISMISSED",
    }
    assert {item.value for item in InterventionType} == {
        "WARNING",
        "RECOMMENDATION",
        "TOOL_OFFER",
    }
    assert {item.value for item in DriverResponseType} == {
        "BEHAVIOR_CORRECTED",
        "VOICE_ACCEPTED",
        "VOICE_REJECTED",
        "BUTTON_ACCEPTED",
        "BUTTON_DISMISSED",
        "NO_RESPONSE",
        "BEHAVIOR_REPEATED",
    }
