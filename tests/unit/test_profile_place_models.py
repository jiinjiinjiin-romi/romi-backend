from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.enums import AgentPersonality, PlaceType, Theme, WarningSensitivity
from app.models import Account, DriverProfile, SavedPlace, SearchHistory


def constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def unique_constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def index_names(model: type) -> set[str]:
    return {index.name for index in model.__table__.indexes if isinstance(index, Index)}


def test_driver_profile_table_columns_and_defaults() -> None:
    table = DriverProfile.__table__

    assert table.name == "driver_profiles"
    assert set(table.columns.keys()) == {
        "id",
        "account_id",
        "display_name",
        "agent_call_name",
        "profile_image_url",
        "report_email",
        "agent_personality",
        "warning_sensitivity",
        "behavior_warning_sensitivity",
        "tts_voice_id",
        "tts_speed",
        "guidance_volume",
        "theme",
        "last_used_at",
        "created_at",
        "updated_at",
    }

    assert isinstance(table.c.id.type, CHAR)
    assert table.c.id.type.length == 36
    assert table.c.id.primary_key
    assert not table.c.id.nullable
    assert table.c.id.default is not None

    assert isinstance(table.c.account_id.type, CHAR)
    assert not table.c.account_id.nullable
    assert isinstance(table.c.display_name.type, String)
    assert table.c.display_name.type.length == 50
    assert not table.c.display_name.nullable
    assert isinstance(table.c.agent_call_name.type, String)
    assert table.c.agent_call_name.type.length == 50
    assert not table.c.agent_call_name.nullable
    assert isinstance(table.c.profile_image_url.type, Text)
    assert table.c.profile_image_url.nullable
    assert isinstance(table.c.report_email.type, String)
    assert table.c.report_email.type.length == 320
    assert table.c.report_email.nullable

    assert isinstance(table.c.agent_personality.type, String)
    assert table.c.agent_personality.type.length == 20
    assert table.c.agent_personality.default.arg == AgentPersonality.FRIENDLY.value
    assert isinstance(table.c.warning_sensitivity.type, String)
    assert table.c.warning_sensitivity.type.length == 10
    assert table.c.warning_sensitivity.default.arg == WarningSensitivity.MEDIUM.value
    assert isinstance(table.c.behavior_warning_sensitivity.type, mysql.JSON)
    assert not table.c.behavior_warning_sensitivity.nullable
    assert isinstance(table.c.theme.type, String)
    assert table.c.theme.type.length == 10
    assert table.c.theme.default.arg == Theme.SYSTEM.value

    assert isinstance(table.c.tts_speed.type, mysql.DECIMAL)
    assert table.c.tts_speed.type.precision == 3
    assert table.c.tts_speed.type.scale == 2
    assert str(table.c.tts_speed.default.arg) == "1.00"
    assert isinstance(table.c.guidance_volume.type, mysql.SMALLINT)
    assert table.c.guidance_volume.type.unsigned
    assert table.c.guidance_volume.default.arg == 70
    assert isinstance(table.c.last_used_at.type, mysql.DATETIME)
    assert table.c.last_used_at.type.fsp == 6
    assert table.c.last_used_at.nullable


def test_driver_profile_constraints_indexes_and_relationships() -> None:
    table = DriverProfile.__table__

    assert constraint_names(DriverProfile) == {
        "ck_driver_profiles_agent_personality",
        "ck_driver_profiles_warning_sensitivity",
        "ck_driver_profiles_theme",
        "ck_driver_profiles_tts_speed",
        "ck_driver_profiles_guidance_volume",
        "ck_driver_profiles_display_name_not_blank",
        "ck_driver_profiles_agent_call_name_not_blank",
    }
    assert {"idx_driver_profiles_account", "idx_driver_profiles_account_last_used"} <= index_names(
        DriverProfile
    )

    fk = next(iter(table.c.account_id.foreign_keys))
    assert isinstance(fk, ForeignKey)
    assert fk.target_fullname == "accounts.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert fk.constraint.name == "fk_driver_profiles_account_id_accounts"

    assert DriverProfile.account.property.back_populates == "driver_profiles"
    assert Account.driver_profiles.property.back_populates == "account"
    assert Account.driver_profiles.property.cascade.delete_orphan
    assert DriverProfile.saved_places.property.back_populates == "profile"
    assert DriverProfile.search_histories.property.back_populates == "profile"


def test_saved_place_table_columns_generated_column_and_constraints() -> None:
    table = SavedPlace.__table__

    assert table.name == "saved_places"
    assert set(table.columns.keys()) == {
        "id",
        "profile_id",
        "place_type",
        "fixed_place_type",
        "label",
        "provider",
        "provider_place_id",
        "address",
        "latitude",
        "longitude",
        "created_at",
        "updated_at",
    }

    assert isinstance(table.c.id.type, CHAR)
    assert table.c.id.type.length == 36
    assert table.c.id.default is not None
    assert isinstance(table.c.place_type.type, String)
    assert table.c.place_type.type.length == 20
    assert isinstance(table.c.fixed_place_type.type, String)
    assert isinstance(table.c.fixed_place_type.computed, Computed)
    assert table.c.fixed_place_type.computed.persisted is True
    assert "place_type IN ('HOME', 'WORK', 'SCHOOL')" in str(
        table.c.fixed_place_type.computed.sqltext
    )
    assert isinstance(table.c.label.type, String)
    assert table.c.label.type.length == 100
    assert isinstance(table.c.provider.type, String)
    assert table.c.provider.default.arg == "KAKAO"
    assert isinstance(table.c.address.type, Text)
    assert isinstance(table.c.latitude.type, mysql.DOUBLE)
    assert isinstance(table.c.longitude.type, mysql.DOUBLE)

    assert constraint_names(SavedPlace) == {
        "ck_saved_places_place_type",
        "ck_saved_places_latitude",
        "ck_saved_places_longitude",
        "ck_saved_places_label_not_blank",
        "ck_saved_places_address_not_blank",
    }
    assert unique_constraint_names(SavedPlace) == {
        "uq_saved_places_profile_fixed_type",
        "uq_saved_places_provider_place",
    }
    assert "idx_saved_places_profile" in index_names(SavedPlace)
    assert {item.value for item in PlaceType} == {"HOME", "WORK", "SCHOOL", "FAVORITE"}


def test_saved_place_fk_and_relationship() -> None:
    table = SavedPlace.__table__
    fk = next(iter(table.c.profile_id.foreign_keys))

    assert fk.target_fullname == "driver_profiles.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert fk.constraint.name == "fk_saved_places_profile_id_driver_profiles"
    assert SavedPlace.profile.property.back_populates == "saved_places"
    assert DriverProfile.saved_places.property.cascade.delete_orphan


def test_search_history_table_columns_constraints_and_relationship() -> None:
    table = SearchHistory.__table__

    assert table.name == "search_histories"
    assert set(table.columns.keys()) == {
        "id",
        "profile_id",
        "query",
        "provider",
        "provider_place_id",
        "place_name",
        "address",
        "latitude",
        "longitude",
        "searched_at",
    }

    assert isinstance(table.c.id.type, mysql.BIGINT)
    assert table.c.id.type.unsigned
    assert table.c.id.autoincrement is True
    assert table.c.id.primary_key
    assert isinstance(table.c.query.type, String)
    assert table.c.query.type.length == 200
    assert isinstance(table.c.provider.type, String)
    assert table.c.provider.default.arg == "KAKAO"
    assert isinstance(table.c.provider_place_id.type, String)
    assert table.c.provider_place_id.type.length == 255
    assert isinstance(table.c.place_name.type, String)
    assert table.c.place_name.type.length == 200
    assert isinstance(table.c.address.type, Text)
    assert isinstance(table.c.latitude.type, mysql.DOUBLE)
    assert table.c.latitude.nullable
    assert isinstance(table.c.longitude.type, mysql.DOUBLE)
    assert table.c.longitude.nullable
    assert isinstance(table.c.searched_at.type, mysql.DATETIME)
    assert table.c.searched_at.type.fsp == 6
    assert not table.c.searched_at.nullable

    assert constraint_names(SearchHistory) == {
        "ck_search_histories_query_not_blank",
        "ck_search_histories_latitude",
        "ck_search_histories_longitude",
        "ck_search_histories_coordinates_pair",
    }
    assert "idx_search_histories_profile_time" in index_names(SearchHistory)

    fk = next(iter(table.c.profile_id.foreign_keys))
    assert fk.target_fullname == "driver_profiles.id"
    assert fk.ondelete == "CASCADE"
    assert fk.onupdate == "RESTRICT"
    assert fk.constraint.name == "fk_search_histories_profile_id_driver_profiles"
    assert SearchHistory.profile.property.back_populates == "search_histories"
    assert DriverProfile.search_histories.property.cascade.delete_orphan
