"""Tests for NotesManager."""

import pytest

from state.notes import NotesManager, VALID_CATEGORIES


def test_save_and_get_notes_roundtrip(tmp_path):
    mgr = NotesManager(tmp_path)
    a = mgr.save_note("first note", category="general")
    b = mgr.save_note("second note", category="decisions")

    all_notes = mgr.get_notes()
    assert len(all_notes) == 2
    # Sorted newest first; b was saved after a.
    assert all_notes[0]["id"] == b["id"]
    assert all_notes[1]["id"] == a["id"]


def test_filter_by_category(tmp_path):
    mgr = NotesManager(tmp_path)
    mgr.save_note("g", category="general")
    mgr.save_note("d", category="decisions")
    mgr.save_note("p", category="preferences")

    decisions = mgr.get_notes(category="decisions")
    assert len(decisions) == 1
    assert decisions[0]["content"] == "d"


def test_invalid_category_raises(tmp_path):
    mgr = NotesManager(tmp_path)
    with pytest.raises(ValueError):
        mgr.save_note("bad", category="not-a-category")
    with pytest.raises(ValueError):
        mgr.get_notes(category="also-bad")


def test_delete_note_returns_true_on_success(tmp_path):
    mgr = NotesManager(tmp_path)
    note = mgr.save_note("removable", category="general")
    assert mgr.delete_note(note["id"]) is True
    assert mgr.delete_note(note["id"]) is False
    assert mgr.get_notes() == []


def test_notes_persist_across_instances(tmp_path):
    mgr1 = NotesManager(tmp_path)
    mgr1.save_note("survive me", category="issues")

    mgr2 = NotesManager(tmp_path)
    notes = mgr2.get_notes()
    assert len(notes) == 1
    assert notes[0]["content"] == "survive me"


def test_valid_categories_constant_is_complete():
    assert set(VALID_CATEGORIES) == {"general", "preferences", "decisions", "issues"}
