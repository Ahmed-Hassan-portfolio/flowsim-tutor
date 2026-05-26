"""Session lifecycle management for FlowSim Tutor workflow tracking.

Provides a ``SessionManager`` class that persists multi-step workflow sessions
as individual JSON files on disk. Each session tracks goal, phases, steps,
indices, and timestamps -- enabling the LLM to resume a user's workflow across
messages and detect stale sessions.

Design:
  - One JSON file per session in ``{sessions_dir}/{id}.json``
  - Atomic writes via temp file + ``os.replace`` (crash-safe on POSIX and Windows)
  - Pure stdlib: json, pathlib, os, uuid, datetime
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_STALE_THRESHOLD = datetime.timedelta(hours=24)


class SessionManager:
    """Persistent session lifecycle manager."""

    def __init__(self, sessions_dir: Path) -> None:
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, goal: str, phases: list[dict]) -> dict:
        """Create and persist a new active session."""
        now = _utc_now_iso()
        session: dict = {
            "id": uuid.uuid4().hex,
            "goal": goal,
            "phases": phases,
            "current_phase_index": 0,
            "current_step_index": 0,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self._save_session(session)
        logger.info("Created session %s: %s", session["id"], goal)
        return session

    def get_current(self) -> Optional[dict]:
        """Return progress summary for the most recent active session.

        If the session has been inactive for 24+ hours the returned summary
        will show ``status="stale"`` -- the on-disk file is NOT modified.
        Caller decides whether to continue or start fresh.
        """
        active_sessions: list[dict] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping corrupt session file %s: %s", path, exc)
                continue
            if data.get("status") == "active":
                active_sessions.append(data)

        if not active_sessions:
            return None

        active_sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        session = active_sessions[0]

        status = session["status"]
        updated_at = datetime.datetime.fromisoformat(session["updated_at"])
        now = datetime.datetime.now(datetime.timezone.utc)
        if now - updated_at >= _STALE_THRESHOLD:
            status = "stale"

        return self._build_progress_summary(session, status_override=status)

    def get_session(self, session_id: str) -> Optional[dict]:
        """Load a specific session by ID."""
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read session %s: %s", session_id, exc)
            return None

    def advance_step(self, step_id: str) -> dict:
        """Mark a step completed and advance session indices.

        Raises ValueError if there is no active session or step_id is not found.
        """
        session = self._find_active_session()

        found = False
        for phase in session["phases"]:
            for step in phase["steps"]:
                if step["id"] == step_id:
                    step["completed"] = True
                    found = True
                    break
            if found:
                break

        if not found:
            raise ValueError(
                f"Step {step_id!r} not found in session {session['id']}"
            )

        self._advance_indices(session)
        session["updated_at"] = _utc_now_iso()
        self._save_session(session)
        logger.info("Advanced step %s in session %s", step_id, session["id"])
        return self._build_progress_summary(session)

    def end_session(self, completed: bool) -> dict:
        """End the active session as completed or abandoned."""
        session = self._find_active_session()
        session["status"] = "completed" if completed else "abandoned"
        session["updated_at"] = _utc_now_iso()
        self._save_session(session)
        logger.info(
            "Ended session %s as %s", session["id"], session["status"]
        )
        return self._build_progress_summary(session)

    def _save_session(self, session: dict) -> None:
        final_path = self._dir / f"{session['id']}.json"
        tmp_path = self._dir / f"{session['id']}.tmp"
        data = json.dumps(session, indent=2, ensure_ascii=False)
        tmp_path.write_text(data, encoding="utf-8")
        os.replace(str(tmp_path), str(final_path))

    def _find_active_session(self) -> dict:
        active_sessions: list[dict] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping corrupt session file %s: %s", path, exc)
                continue
            if data.get("status") == "active":
                active_sessions.append(data)

        if not active_sessions:
            raise ValueError("No active session found")

        active_sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return active_sessions[0]

    @staticmethod
    def _advance_indices(session: dict) -> None:
        phases = session["phases"]
        for pi in range(len(phases)):
            steps = phases[pi]["steps"]
            for si in range(len(steps)):
                if not steps[si]["completed"]:
                    session["current_phase_index"] = pi
                    session["current_step_index"] = si
                    return
        session["current_phase_index"] = len(phases) - 1
        session["current_step_index"] = len(phases[-1]["steps"])

    @staticmethod
    def _build_progress_summary(
        session: dict, status_override: Optional[str] = None
    ) -> dict:
        status = status_override or session["status"]
        phases = session["phases"]
        pi = session["current_phase_index"]
        si = session["current_step_index"]

        total_phases = len(phases)
        current_phase_name = phases[pi]["name"] if pi < total_phases else "Done"
        current_phase_steps = phases[pi]["steps"] if pi < total_phases else []
        total_steps_in_phase = len(current_phase_steps)

        phases_summary: list[dict] = []
        for phase in phases:
            completed_steps = sum(1 for s in phase["steps"] if s["completed"])
            phases_summary.append({
                "name": phase["name"],
                "completed_steps": completed_steps,
                "total_steps": len(phase["steps"]),
            })

        progress = (
            f"Phase {pi + 1}/{total_phases} - "
            f"Step {si + 1}/{total_steps_in_phase}"
        )

        current_step_desc = ""
        if pi < total_phases and si < total_steps_in_phase:
            current_step_desc = current_phase_steps[si]["description"]

        return {
            "id": session["id"],
            "goal": session["goal"],
            "status": status,
            "current_phase": current_phase_name,
            "current_step": current_step_desc,
            "progress": progress,
            "phases_summary": phases_summary,
        }

    def __repr__(self) -> str:
        return f"SessionManager(sessions_dir={self._dir!r})"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
