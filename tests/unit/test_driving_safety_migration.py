import importlib.util
from pathlib import Path
from types import ModuleType


def load_third_revision() -> ModuleType:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0003_create_driving_and_safety_tables.py"
    )
    spec = importlib.util.spec_from_file_location(
        "revision_0003_create_driving_and_safety_tables",
        revision_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_third_revision_metadata() -> None:
    revision = load_third_revision()

    assert revision.revision == "0003_driving_safety_tables"
    assert revision.down_revision == "0002_profile_place_tables"


def test_third_revision_contains_explicit_driving_and_safety_schema() -> None:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0003_create_driving_and_safety_tables.py"
    )
    source = revision_path.read_text(encoding="utf-8")

    assert '"driving_sessions"' in source
    assert '"location_samples"' in source
    assert '"behavior_events"' in source
    assert '"interventions"' in source
    assert '"driver_responses"' in source
    assert "mysql.BIGINT(unsigned=True)" in source
    assert "mysql.INTEGER(unsigned=True)" in source
    assert "mysql.SMALLINT(unsigned=True)" in source
    assert "mysql.TINYINT(unsigned=True)" in source
    assert "mysql.DATETIME(fsp=6)" in source
    assert "mysql.JSON()" in source
    assert "sa.Computed(" in source
    assert "uq_driving_sessions_active_profile" in source
    assert "uq_location_samples_time" in source
    assert "ck_behavior_events_behavior_type" in source
    assert "ck_interventions_level" in source
    assert "ck_driver_responses_response_type" in source
    assert "ondelete=\"CASCADE\"" in source
    assert "onupdate=\"RESTRICT\"" in source
    assert "idx_driving_sessions_profile_time" in source
    assert "idx_behavior_events_type_time" in source
    assert "op.drop_table(\"driver_responses\")" in source
    assert "op.drop_table(\"interventions\")" in source
    assert "op.drop_table(\"behavior_events\")" in source
    assert "op.drop_table(\"location_samples\")" in source
    assert "op.drop_table(\"driving_sessions\")" in source
