import importlib.util
from pathlib import Path
from types import ModuleType


def load_second_revision() -> ModuleType:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0002_create_profile_and_place_tables.py"
    )
    spec = importlib.util.spec_from_file_location(
        "revision_0002_create_profile_and_place_tables",
        revision_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_second_revision_metadata() -> None:
    revision = load_second_revision()

    assert revision.revision == "0002_profile_place_tables"
    assert revision.down_revision == "0001_create_accounts"


def test_second_revision_contains_explicit_profile_place_schema() -> None:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0002_create_profile_and_place_tables.py"
    )
    source = revision_path.read_text(encoding="utf-8")

    assert '"driver_profiles"' in source
    assert '"saved_places"' in source
    assert '"search_histories"' in source
    assert 'sa.CHAR(length=36)' in source
    assert "mysql.BIGINT(unsigned=True)" in source
    assert "mysql.DECIMAL(precision=3, scale=2)" in source
    assert "mysql.SMALLINT(unsigned=True)" in source
    assert "sa.Computed(" in source
    assert "persisted=True" in source
    assert "uq_saved_places_profile_fixed_type" in source
    assert "uq_saved_places_provider_place" in source
    assert "ck_driver_profiles_tts_speed" in source
    assert "ck_search_histories_coordinates_pair" in source
    assert "ondelete=\"CASCADE\"" in source
    assert "onupdate=\"RESTRICT\"" in source
    assert "idx_driver_profiles_account_last_used" in source
    assert "idx_search_histories_profile_time" in source
    assert "op.drop_table(\"search_histories\")" in source
    assert "op.drop_table(\"saved_places\")" in source
    assert "op.drop_table(\"driver_profiles\")" in source
