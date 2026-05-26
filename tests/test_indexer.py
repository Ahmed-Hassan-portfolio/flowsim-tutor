"""Tests for the indexer: ChromaDB + BM25 + manifest consistency.

These tests touch the embedding model and ChromaDB. They are slower than the
chunker/state tests but still complete in a few seconds after the model is
loaded.
"""

import hashlib
import json

from rag.indexer import validate_manifest


def test_counts_match_across_stores(shared_indexed_corpus):
    """ChromaDB, BM25, and chunk count all match."""
    manifest = shared_indexed_corpus["manifest"]
    stores = manifest["stores"]
    assert stores["counts_match"] is True
    assert stores["chromadb_count"] == stores["bm25_count"]
    assert stores["chromadb_count"] == len(shared_indexed_corpus["chunks"])


def test_manifest_records_source_file_hashes(shared_indexed_corpus):
    manifest = shared_indexed_corpus["manifest"]
    hashes = manifest["source_files"]["hashes"]
    assert "SampleA.md" in hashes
    assert "SampleB.md" in hashes
    # Hash matches file content.
    docs_dir = shared_indexed_corpus["docs_dir"]
    actual = hashlib.sha256((docs_dir / "SampleA.md").read_bytes()).hexdigest()
    assert hashes["SampleA.md"] == actual


def test_manifest_validation_passes_initially(shared_indexed_corpus):
    result = validate_manifest(
        shared_indexed_corpus["manifest_path"],
        shared_indexed_corpus["docs_dir"],
    )
    assert result["valid"] is True
    assert result.get("errors", []) == []


def test_manifest_validation_detects_modified_source(
    shared_indexed_corpus, tmp_path
):
    """Mutating a source file invalidates the manifest."""
    docs_dir = tmp_path / "docs_dirty"
    docs_dir.mkdir()
    for src in shared_indexed_corpus["docs_dir"].glob("*.md"):
        (docs_dir / src.name).write_text(src.read_text())

    # Mutate one file.
    target = docs_dir / "SampleA.md"
    target.write_text(target.read_text() + "\n\n## NewSection\n\nadded\n")

    result = validate_manifest(shared_indexed_corpus["manifest_path"], docs_dir)
    assert result["valid"] is False
    assert any("SampleA.md" in e for e in result["errors"])


def test_manifest_validation_detects_new_file(
    shared_indexed_corpus, tmp_path
):
    docs_dir = tmp_path / "docs_extra"
    docs_dir.mkdir()
    for src in shared_indexed_corpus["docs_dir"].glob("*.md"):
        (docs_dir / src.name).write_text(src.read_text())
    (docs_dir / "Extra.md").write_text("# Extra\n\n## X\n\nnew file\n")

    result = validate_manifest(shared_indexed_corpus["manifest_path"], docs_dir)
    assert result["valid"] is False
    assert any("Extra.md" in e for e in result["errors"])
