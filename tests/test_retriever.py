"""Tests for FlowsimRetriever hybrid search and section retrieval."""

import pytest

from rag.retriever import FlowsimRetriever


@pytest.fixture
def retriever(shared_indexed_corpus) -> FlowsimRetriever:
    return FlowsimRetriever(
        chroma_dir=shared_indexed_corpus["chroma_dir"],
        bm25_path=shared_indexed_corpus["bm25_path"],
    )


def test_search_returns_results_with_metadata(retriever):
    result = retriever.search_docs("time step control MAXDT MINDT", top_k=5)
    assert result["query"]
    assert result["results"], "expected at least one result"
    first = result["results"][0]
    for key in ("chunk_id", "section_path", "source_file", "snippet", "rrf_score"):
        assert key in first


def test_search_finds_merged_model_description_pair(retriever):
    """The merged Model description + How to use chunk should rank highly for related queries."""
    result = retriever.search_docs("set MAXDT in the INTEGRATION block", top_k=5)
    top_paths = [r["section_path"] for r in result["results"]]
    assert any("Time step control" in p for p in top_paths)


def test_source_filter_restricts_to_one_file(retriever):
    result = retriever.search_docs("valve opening", top_k=10, source_filter="SampleB.md")
    assert result["results"]
    for r in result["results"]:
        assert r["source_file"] == "SampleB.md"


def test_low_confidence_for_off_topic_query(retriever):
    result = retriever.search_docs("xylophone marsupial photosynthesis", top_k=5)
    # Either no results, or low confidence -- we accept both as "the retriever
    # isn't pretending to know."
    assert result["confidence"] == "low" or not result["results"]


def test_get_full_section_returns_text(retriever, shared_indexed_corpus):
    """Round-trip: pick a chunk_id from search, fetch the full section."""
    search = retriever.search_docs("valve steps opening closing", top_k=3)
    assert search["results"]
    chunk_id = search["results"][0]["chunk_id"]

    full = retriever.get_full_section(chunk_id)
    assert "error" not in full
    assert full["full_text"]
    assert full["chunk_count"] >= 1


def test_get_full_section_returns_error_for_unknown_id(retriever):
    result = retriever.get_full_section("does-not-exist-id-123")
    assert "error" in result
