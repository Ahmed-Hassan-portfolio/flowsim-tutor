"""Indexing pipeline for FlowSim Tutor: ChromaDB vector store, BM25 keyword index, manifest.

Builds and validates dual indexes (ChromaDB + BM25) that share identical chunk
IDs in identical order, enabling RRF hybrid fusion in the retrieval layer.
"""

import hashlib
import json
import os
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import chromadb
from rank_bm25 import BM25Okapi

from rag.chunker import Chunk

COLLECTION_NAME = "flowsim_docs"

CHROMA_HNSW_PARAMS: Dict[str, Any] = {
    "hnsw:space": "cosine",
    "hnsw:M": 16,
    "hnsw:construction_ef": 200,
    "hnsw:search_ef": 100,
}

BATCH_SIZE = 500

_CHROMA_META_KEYS = [
    "source_file",
    "section_path",
    "heading_level",
    "chunk_index",
    "content_type",
    "has_steps",
    "token_count",
    "paired_with",
    "h2_header",
    "h3_header",
]


def build_chromadb_index(
    chunks: List[Chunk],
    embeddings: Any,  # numpy ndarray (N, 384)
    chroma_path: Path,
    collection_name: str = COLLECTION_NAME,
) -> Dict[str, Any]:
    """Build a persistent ChromaDB collection from pre-computed embeddings."""
    client = chromadb.PersistentClient(path=str(chroma_path.resolve()))

    try:
        client.delete_collection(collection_name)
    except Exception:
        pass  # Collection doesn't exist yet

    # create_collection (not get_or_create) — get_or_create silently ignores
    # metadata kwargs in ChromaDB 1.x.
    collection = client.create_collection(
        name=collection_name,
        metadata=CHROMA_HNSW_PARAMS,
    )

    for i in range(0, len(chunks), BATCH_SIZE):
        batch_end = min(i + BATCH_SIZE, len(chunks))
        batch_chunks = chunks[i:batch_end]

        ids = [c.id for c in batch_chunks]
        documents = [c.text for c in batch_chunks]
        metadatas = [_sanitize_metadata(c.metadata) for c in batch_chunks]
        batch_embeddings = embeddings[i:batch_end].tolist()

        collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=batch_embeddings,
        )

    stored_count = collection.count()
    assert stored_count == len(chunks), (
        f"ChromaDB count mismatch: stored {stored_count}, expected {len(chunks)}"
    )

    return {
        "collection_name": collection_name,
        "count": stored_count,
        "client": client,
    }


def _sanitize_metadata(metadata: dict) -> dict:
    """Flatten chunk metadata to ChromaDB-safe types (str/int/float/bool)."""
    safe: Dict[str, Any] = {}
    for key in _CHROMA_META_KEYS:
        value = metadata.get(key)
        if value is None:
            safe[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            safe[key] = value
        else:
            continue

    if safe.get("paired_with") is None:
        safe["paired_with"] = ""

    is_merged = metadata.get("is_merged")
    if is_merged is not None and isinstance(is_merged, bool):
        safe["is_merged"] = is_merged
    else:
        safe["is_merged"] = False

    return safe


def build_bm25_index(
    chunks: List[Chunk],
    bm25_path: Path,
) -> Dict[str, Any]:
    """Build a BM25Okapi keyword index and serialize to pickle.

    Uses the SAME chunks in the SAME order as ChromaDB for ID consistency.
    """
    corpus = [chunk.text.lower().split() for chunk in chunks]
    bm25 = BM25Okapi(corpus)

    payload = {
        "bm25": bm25,
        "chunk_ids": [chunk.id for chunk in chunks],
    }

    tmp_path = bm25_path.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(str(tmp_path), str(bm25_path))

    return {
        "count": len(chunks),
        "path": str(bm25_path),
    }


def build_manifest(
    source_dir: Path,
    chunks: List[Chunk],
    chroma_count: int,
    bm25_count: int,
    manifest_path: Path,
) -> dict:
    """Build an index consistency manifest with file hashes + count validation."""
    source_hashes = {}
    for md_file in sorted(source_dir.glob("*.md")):
        file_hash = hashlib.sha256(md_file.read_bytes()).hexdigest()
        source_hashes[md_file.name] = file_hash

    sorted_ids = sorted(c.id for c in chunks)
    ids_string = "\n".join(sorted_ids)
    ids_hash = hashlib.sha256(ids_string.encode("utf-8")).hexdigest()

    counts_match = chroma_count == bm25_count == len(chunks)

    manifest = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": "all-MiniLM-L6-v2",
        "distance_metric": "cosine",
        "source_files": {
            "count": len(source_hashes),
            "hashes": source_hashes,
        },
        "chunks": {
            "total_count": len(chunks),
            "ids_hash": ids_hash,
        },
        "stores": {
            "chromadb_count": chroma_count,
            "bm25_count": bm25_count,
            "counts_match": counts_match,
        },
    }

    tmp_path = manifest_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    os.replace(str(tmp_path), str(manifest_path))

    return manifest


def validate_manifest(
    manifest_path: Path,
    source_dir: Path,
) -> Dict[str, Any]:
    """Validate the index manifest against the current source files.

    Called at server startup to verify consistency before serving queries.
    """
    if not manifest_path.exists():
        return {"valid": False, "reason": "No manifest found"}

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"valid": False, "reason": f"Cannot read manifest: {e}"}

    errors: List[str] = []

    stores = manifest.get("stores", {})
    if not stores.get("counts_match", False):
        errors.append(
            f"Index counts do not match: "
            f"chromadb={stores.get('chromadb_count')}, "
            f"bm25={stores.get('bm25_count')}"
        )

    source_hashes = manifest.get("source_files", {}).get("hashes", {})
    for filename, expected_hash in source_hashes.items():
        file_path = source_dir / filename
        if not file_path.exists():
            errors.append(f"Source file missing: {filename}")
            continue
        current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if current_hash != expected_hash:
            errors.append(f"Source file changed: {filename}")

    current_files = {f.name for f in source_dir.glob("*.md")}
    manifest_files = set(source_hashes.keys())
    new_files = current_files - manifest_files
    if new_files:
        errors.append(f"New source files not indexed: {', '.join(sorted(new_files))}")

    return {"valid": len(errors) == 0, "errors": errors}
