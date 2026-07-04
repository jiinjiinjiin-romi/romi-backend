import importlib.util
from pathlib import Path
from types import ModuleType


def load_fifth_revision() -> ModuleType:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0005_expand_behavior_event_taxonomy.py"
    )
    spec = importlib.util.spec_from_file_location(
        "revision_0005_expand_behavior_event_taxonomy",
        revision_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fifth_revision_metadata() -> None:
    revision = load_fifth_revision()

    assert revision.revision == "0005_behavior_event_taxonomy"
    assert revision.down_revision == "0004_agent_report_tables"


def test_fifth_revision_updates_behavior_event_check_constraint() -> None:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0005_expand_behavior_event_taxonomy.py"
    )
    source = revision_path.read_text(encoding="utf-8")

    assert "op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_=\"check\")" in source
    assert "op.create_check_constraint(" in source
    assert "ck_behavior_events_behavior_type" in source
    assert "SECONDARY_TASK" in source
    assert "REACHING_BEHIND" in source
    assert "SMOKING" in source
    assert "NORMAL" not in source
    assert "SAFE_DRIVING" not in source
    assert revision_path.name.startswith("0005_")
