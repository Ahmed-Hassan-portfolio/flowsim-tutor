"""Tests for the server-side response truncation logic."""

import json

from server import truncate_response, MAX_RESPONSE_BYTES


def test_small_payload_passes_through():
    payload = json.dumps({"ok": True, "x": 1})
    assert truncate_response(payload) == payload


def test_large_payload_is_summarized():
    big_results = [
        {"chunk_id": f"id_{i}", "snippet": "x" * 200, "rrf_score": 0.1}
        for i in range(100)
    ]
    payload = json.dumps({"results": big_results})
    assert len(payload.encode("utf-8")) > MAX_RESPONSE_BYTES

    truncated = truncate_response(payload)
    assert len(truncated.encode("utf-8")) <= MAX_RESPONSE_BYTES
    data = json.loads(truncated)
    assert data["truncated"] is True
    assert "preview" in data
    assert "100 results" in data["preview"]


def test_truncation_handles_invalid_json_gracefully():
    payload = "not json at all " * 1000
    out = truncate_response(payload)
    assert len(out.encode("utf-8")) <= MAX_RESPONSE_BYTES
