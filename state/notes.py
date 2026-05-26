"""Categorized notes persistence for cross-session memory.

Stores notes (preferences, decisions, issues, general observations) in a single
JSON file on disk. Notes survive session ends and conversation resets.

Design:
  - Single flat JSON array in ``{notes_dir}/notes.json``
  - Atomic writes via temp file + ``os.replace`` (crash-safe)
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

VALID_CATEGORIES: tuple[str, ...] = (
    "general",
    "preferences",
    "decisions",
    "issues",
)


class NotesManager:
    """Persistent categorized notes store."""

    _FILENAME = "notes.json"
    _TMPNAME = "notes.tmp"

    def __init__(self, notes_dir: Path) -> None:
        self._dir = Path(notes_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / self._FILENAME
        self._tmp = self._dir / self._TMPNAME
        self._notes: list[dict] = self._load()

    def save_note(self, content: str, category: str = "general") -> dict:
        """Create and persist a new note. Raises ValueError on invalid category."""
        self._validate_category(category)

        note: dict = {
            "id": uuid.uuid4().hex,
            "content": content,
            "category": category,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self._notes.append(note)
        self._save()
        return note

    def get_notes(self, category: Optional[str] = None) -> list[dict]:
        """Return notes, optionally filtered by category. Sorted newest first."""
        if category is not None:
            self._validate_category(category)
            filtered = [n for n in self._notes if n["category"] == category]
        else:
            filtered = list(self._notes)

        filtered.sort(key=lambda n: n["created_at"], reverse=True)
        return filtered

    def delete_note(self, note_id: str) -> bool:
        """Remove a note by ID. Returns True if found and removed."""
        for idx, note in enumerate(self._notes):
            if note["id"] == note_id:
                self._notes.pop(idx)
                self._save()
                return True
        return False

    def _save(self) -> None:
        data = json.dumps(self._notes, indent=2, ensure_ascii=False)
        self._tmp.write_text(data, encoding="utf-8")
        os.replace(str(self._tmp), str(self._file))

    def _load(self) -> list[dict]:
        if not self._file.exists():
            return []
        try:
            text = self._file.read_text(encoding="utf-8")
            notes = json.loads(text)
            if not isinstance(notes, list):
                logger.warning(
                    "Notes file %s has unexpected root type %s; starting fresh",
                    self._file,
                    type(notes).__name__,
                )
                return []
            return notes
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Could not read notes from %s (%s); starting fresh",
                self._file,
                exc,
            )
            return []

    @staticmethod
    def _validate_category(category: str) -> None:
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category {category!r}. "
                f"Must be one of: {', '.join(VALID_CATEGORIES)}"
            )

    def __repr__(self) -> str:
        return f"NotesManager(notes_dir={self._dir!r}, count={len(self._notes)})"
