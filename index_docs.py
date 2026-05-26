"""One-time indexing CLI for FlowSim Tutor documentation.

Builds the dual ChromaDB + BM25 indexes that the MCP server reads at runtime.

Pipeline:
    1. Chunk all Markdown documents in data/docs/
    2. Compute embeddings with all-MiniLM-L6-v2
    3. Build the ChromaDB vector index (cosine distance, HNSW)
    4. Build the BM25 keyword index (rank-bm25)
    5. Generate the consistency manifest and self-validate

Usage:
    python index_docs.py
"""

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parent
DOCS_DIR = BASE_PATH / "data" / "docs"
CHROMA_DIR = BASE_PATH / "data" / "chroma_db"
BM25_PATH = BASE_PATH / "data" / "bm25_index.pkl"
MANIFEST_PATH = BASE_PATH / "data" / "index_manifest.json"


def main() -> None:
    print("=" * 60)
    print("FlowSim Tutor -- Document Indexing Pipeline")
    print("=" * 60)

    sqlite_version = sqlite3.sqlite_version
    sqlite_parts = tuple(int(x) for x in sqlite_version.split("."))
    print(f"\nSQLite version: {sqlite_version}")
    if sqlite_parts < (3, 35):
        print(f"ERROR: SQLite >= 3.35 required, got {sqlite_version}")
        sys.exit(1)
    print("  SQLite version OK")

    md_files = sorted(DOCS_DIR.glob("*.md"))
    if not md_files:
        print(f"\nERROR: No Markdown files found in {DOCS_DIR}")
        print("Add .md files to data/docs/ before indexing.")
        sys.exit(1)

    print(f"\nSource files: {len(md_files)} Markdown files in {DOCS_DIR.name}/")
    for f in md_files:
        print(f"  - {f.name}")

    print("\n--- Chunking ---")
    from rag.chunker import chunk_all

    chunks = chunk_all(DOCS_DIR)
    print(f"Total chunks: {len(chunks)}")

    print("\n--- Embedding ---")
    from rag.embedder import encode_texts

    texts = [c.text for c in chunks]
    embeddings = encode_texts(texts)
    print(f"Embeddings: {embeddings.shape[0]} vectors, dimension {embeddings.shape[1]}")

    print("\n--- ChromaDB Index ---")
    from rag.indexer import build_chromadb_index, build_bm25_index, build_manifest

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    chroma_result = build_chromadb_index(chunks, embeddings, CHROMA_DIR)
    print(f"ChromaDB: {chroma_result['count']} items in '{chroma_result['collection_name']}'")

    print("\n--- BM25 Index ---")
    BM25_PATH.parent.mkdir(parents=True, exist_ok=True)
    bm25_result = build_bm25_index(chunks, BM25_PATH)
    print(f"BM25: {bm25_result['count']} items -> {Path(bm25_result['path']).name}")

    print("\n--- Manifest ---")
    manifest = build_manifest(
        DOCS_DIR, chunks, chroma_result["count"], bm25_result["count"], MANIFEST_PATH
    )
    print(f"Manifest: counts_match = {manifest['stores']['counts_match']}")
    print(f"  ChromaDB: {manifest['stores']['chromadb_count']}")
    print(f"  BM25:     {manifest['stores']['bm25_count']}")
    print(f"  Chunks:   {manifest['chunks']['total_count']}")

    print("\n--- Per-File Stats ---")
    file_counts: dict = defaultdict(int)
    for c in chunks:
        file_counts[c.metadata["source_file"]] += 1

    for filename in sorted(file_counts.keys()):
        print(f"  {filename:.<40} {file_counts[filename]:>4} chunks")
    print(f"  {'TOTAL':.<40} {len(chunks):>4} chunks")

    print("\n--- Validation ---")
    from rag.indexer import validate_manifest

    validation = validate_manifest(MANIFEST_PATH, DOCS_DIR)
    if validation["valid"]:
        print("Validation passed: manifest is consistent with source files")
    else:
        errors = validation.get("errors", [])
        reason = validation.get("reason", "")
        print(f"Validation FAILED: {reason or '; '.join(errors)}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Indexing complete!")
    print(f"  ChromaDB: {CHROMA_DIR}")
    print(f"  BM25:     {BM25_PATH}")
    print(f"  Manifest: {MANIFEST_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
