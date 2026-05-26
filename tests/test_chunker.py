"""Tests for the Markdown chunker."""

from rag.chunker import chunk_all, chunk_file


def test_chunks_produced_from_both_files(chunks_from_synthetic):
    """Chunker produces chunks from each source file."""
    chunks = chunks_from_synthetic
    sources = {c.metadata["source_file"] for c in chunks}
    assert "SampleA.md" in sources
    assert "SampleB.md" in sources


def test_separator_splits_top_level_sections(chunks_from_synthetic):
    """The --- separator creates distinct top-level sections."""
    chunks = chunks_from_synthetic
    section_paths = {c.metadata["section_path"] for c in chunks}
    assert any("Setup" in p for p in section_paths)
    assert any("Numerics" in p for p in section_paths)


def test_table_of_contents_is_skipped(chunks_from_synthetic):
    """Sections with heading 'Table of Contents' are not emitted as chunks."""
    chunks = chunks_from_synthetic
    for c in chunks:
        assert "Table of Contents" not in c.metadata["section_path"]


def test_model_description_and_how_to_use_are_merged(chunks_from_synthetic):
    """Adjacent Model description + How to use pairs are merged into one chunk."""
    chunks = chunks_from_synthetic
    merged = [c for c in chunks if c.metadata.get("content_type") == "merged"]
    assert len(merged) == 1
    text = merged[0].text
    assert "Model description" in text
    assert "How to use" in text
    assert "MAXDT" in text
    assert "MINDT" in text


def test_numbered_steps_flagged_in_metadata(chunks_from_synthetic):
    """Chunks with numbered step sequences set has_steps=True."""
    chunks = chunks_from_synthetic
    with_steps = [c for c in chunks if c.metadata.get("has_steps")]
    assert with_steps, "expected at least one chunk with numbered steps"
    valve_chunks = [c for c in with_steps if "Valve" in c.metadata["section_path"]]
    assert valve_chunks


def test_section_path_includes_file_stem_and_hierarchy(chunks_from_synthetic):
    """section_path follows the pattern '<file_stem> > h2 > h3 > ...'."""
    chunks = chunks_from_synthetic
    paths = [c.metadata["section_path"] for c in chunks]
    sample_a_paths = [p for p in paths if p.startswith("SampleA")]
    assert sample_a_paths
    setup_paths = [p for p in sample_a_paths if "Setup" in p]
    assert setup_paths
    # First segment is always the file stem.
    for p in paths:
        assert " > " in p
        head = p.split(" > ")[0]
        assert head in {"SampleA", "SampleB"}


def test_chunk_ids_are_unique(chunks_from_synthetic):
    """Every chunk has a unique ID, even when sections share a heading."""
    chunks = chunks_from_synthetic
    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), f"duplicate IDs: {ids}"


def test_chunk_file_reads_a_single_path(tmp_path):
    """chunk_file works on a single Markdown path."""
    p = tmp_path / "Mini.md"
    p.write_text("# Mini\n\n## A\n\nbody of A.\n", encoding="utf-8")
    chunks = chunk_file(p)
    assert chunks
    assert chunks[0].metadata["source_file"] == "Mini.md"
