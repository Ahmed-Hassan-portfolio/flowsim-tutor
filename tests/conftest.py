"""Shared pytest fixtures: tiny synthetic corpus, indexed temp directories."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the project root is importable so `rag`, `state`, `tools` resolve.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SAMPLE_DOC_A = """# SampleA

Some intro text.

## Table of Contents

- skipped TOC content

---

## Setup

Setup intro paragraph that should be the body of the Setup section.

---

## Numerics

Numerics text introduces the section.

---

### Time step control

Time step control intro paragraph.

---

#### Model description

Adaptive time-stepping bounded by MAXDT and MINDT.

---

#### How to use

1. Set MAXDT in the INTEGRATION block.
2. Set MINDT to a value at least 100x smaller than MAXDT.
3. Run the case and inspect the time-step log.

---

### Restart

Restart text. No paired heading here.
"""


SAMPLE_DOC_B = """# SampleB

## Equipment

Equipment intro.

---

### Valve

Valve description.

1. Step one for opening.
2. Step two for closing.
3. Step three for verification.
"""


@pytest.fixture
def synthetic_docs_dir(tmp_path: Path) -> Path:
    """Create a tmp dir with two small synthetic FlowSim-style docs."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "SampleA.md").write_text(SAMPLE_DOC_A, encoding="utf-8")
    (docs / "SampleB.md").write_text(SAMPLE_DOC_B, encoding="utf-8")
    return docs


@pytest.fixture
def chunks_from_synthetic(synthetic_docs_dir: Path):
    """Pre-computed chunks from the synthetic corpus."""
    from rag.chunker import chunk_all

    return chunk_all(synthetic_docs_dir)


@pytest.fixture(scope="session")
def shared_indexed_corpus(tmp_path_factory):
    """Build a session-scoped index against the synthetic corpus.

    Slow on first call (loads the embedding model) but reused across tests.
    """
    from rag.chunker import chunk_all
    from rag.embedder import encode_texts
    from rag.indexer import build_chromadb_index, build_bm25_index, build_manifest

    work = tmp_path_factory.mktemp("indexed_corpus")
    docs = work / "docs"
    docs.mkdir()
    (docs / "SampleA.md").write_text(SAMPLE_DOC_A, encoding="utf-8")
    (docs / "SampleB.md").write_text(SAMPLE_DOC_B, encoding="utf-8")

    chunks = chunk_all(docs)
    texts = [c.text for c in chunks]
    embeddings = encode_texts(texts)

    chroma_dir = work / "chroma_db"
    bm25_path = work / "bm25_index.pkl"
    manifest_path = work / "index_manifest.json"

    chroma_result = build_chromadb_index(chunks, embeddings, chroma_dir)
    bm25_result = build_bm25_index(chunks, bm25_path)
    manifest = build_manifest(
        docs, chunks, chroma_result["count"], bm25_result["count"], manifest_path
    )

    return {
        "docs_dir": docs,
        "chroma_dir": chroma_dir,
        "bm25_path": bm25_path,
        "manifest_path": manifest_path,
        "chunks": chunks,
        "manifest": manifest,
    }
