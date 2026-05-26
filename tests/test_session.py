"""Tests for SessionManager."""

import datetime
import json
from pathlib import Path

import pytest

from state.session import SessionManager


def _phases() -> list[dict]:
    return [
        {
            "name": "Setup",
            "description": "Initial setup",
            "steps": [
                {"id": "s1", "description": "Open project", "completed": False},
                {"id": "s2", "description": "Configure options", "completed": False},
            ],
        },
        {
            "name": "Run",
            "description": "Run the case",
            "steps": [
                {"id": "s3", "description": "Verify case", "completed": False},
            ],
        },
    ]


def test_create_session_returns_active_with_unique_id(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s1 = mgr.create_session(goal="Goal A", phases=_phases())
    s2 = mgr.create_session(goal="Goal B", phases=_phases())
    assert s1["id"] != s2["id"]
    assert s1["status"] == "active"
    assert (tmp_path / f"{s1['id']}.json").exists()


def test_get_current_returns_most_recent_active(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    mgr.create_session(goal="First", phases=_phases())
    second = mgr.create_session(goal="Second", phases=_phases())

    current = mgr.get_current()
    assert current is not None
    assert current["id"] == second["id"]
    assert current["status"] == "active"
    assert current["progress"] == "Phase 1/2 - Step 1/2"


def test_advance_step_marks_completed_and_moves_indices(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    mgr.create_session(goal="Walk through", phases=_phases())

    summary = mgr.advance_step("s1")
    assert summary["progress"] == "Phase 1/2 - Step 2/2"

    summary = mgr.advance_step("s2")
    assert summary["progress"] == "Phase 2/2 - Step 1/1"
    assert summary["current_phase"] == "Run"


def test_advance_step_raises_on_unknown_id(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    mgr.create_session(goal="x", phases=_phases())
    with pytest.raises(ValueError):
        mgr.advance_step("does-not-exist")


def test_end_session_sets_terminal_status(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s = mgr.create_session(goal="x", phases=_phases())
    summary = mgr.end_session(completed=True)
    assert summary["status"] == "completed"

    raw = json.loads((tmp_path / f"{s['id']}.json").read_text())
    assert raw["status"] == "completed"


def test_stale_session_is_flagged_but_not_modified(tmp_path: Path):
    mgr = SessionManager(tmp_path)
    s = mgr.create_session(goal="old", phases=_phases())

    raw_path = tmp_path / f"{s['id']}.json"
    raw = json.loads(raw_path.read_text())
    old_time = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=2)
    ).isoformat()
    raw["updated_at"] = old_time
    raw_path.write_text(json.dumps(raw))

    current = mgr.get_current()
    assert current is not None
    assert current["status"] == "stale"

    # On-disk status is still active -- staleness is presentation-only.
    assert json.loads(raw_path.read_text())["status"] == "active"
