"""FlowSim Tutor MCP Server -- RAG-based tutoring for FlowSim documentation.

Stability notes:
  - All tools run sync operations via ``asyncio.to_thread()`` to avoid blocking
    the event loop.
  - Response payloads are capped at ``MAX_RESPONSE_BYTES`` to prevent stdio pipe
    buffer deadlock (Windows pipe buffers can be as small as 4-8 KB).
  - The embedding model is pre-loaded at startup to avoid a 3-5s stall on the
    first ``search_docs`` call.
"""
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# All logging to stderr + file, NEVER stdout (breaks stdio protocol).
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_DIR / "server.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("flowsim-tutor")

from mcp.server.fastmcp import FastMCP

# Stay well under Windows stdio pipe buffer size to avoid producer-consumer deadlock.
MAX_RESPONSE_BYTES = 3500


@dataclass
class AppContext:
    """Resources initialized at server startup, available to all tools."""

    rag_engine: Any  # FlowsimRetriever
    session_mgr: Any  # SessionManager
    notes_mgr: Any  # NotesManager


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Eagerly initialize all components at server startup."""
    base = Path(__file__).parent
    docs_dir = base / "data" / "docs"
    manifest_path = base / "data" / "index_manifest.json"

    logger.info("=== FlowSim Tutor Server Starting ===")

    logger.info("Validating index manifest against source files...")
    from rag.indexer import validate_manifest

    validation = validate_manifest(manifest_path, docs_dir)
    if not validation["valid"]:
        reason = validation.get("reason") or "; ".join(validation.get("errors", []))
        logger.error("Index drift detected: %s", reason)
        logger.error("Run `python index_docs.py` to rebuild the indexes before starting the server.")
        raise RuntimeError(
            f"Index manifest validation failed: {reason}. "
            "Rebuild the indexes with `python index_docs.py`."
        )
    logger.info("Index manifest OK")

    logger.info("Loading RAG engine (ChromaDB + BM25 + embeddings)...")
    from rag.retriever import FlowsimRetriever

    rag = FlowsimRetriever(
        chroma_dir=base / "data" / "chroma_db",
        bm25_path=base / "data" / "bm25_index.pkl",
    )

    logger.info("Pre-loading embedding model...")
    from rag.embedder import _get_model
    _get_model()
    logger.info("Embedding model ready")

    logger.info("Loading state managers...")
    from state.session import SessionManager
    from state.notes import NotesManager

    session_mgr = SessionManager(base / "data" / "sessions")
    notes_mgr = NotesManager(base / "data" / "notes")

    logger.info("=== Server Ready ===")
    try:
        yield AppContext(
            rag_engine=rag,
            session_mgr=session_mgr,
            notes_mgr=notes_mgr,
        )
    finally:
        logger.info("=== Server Shutting Down ===")


mcp = FastMCP("flowsim-tutor", lifespan=app_lifespan)


def truncate_response(payload: str, max_bytes: int = MAX_RESPONSE_BYTES) -> str:
    """Truncate a JSON response payload to stay under the stdio pipe buffer.

    If truncation occurs, the response is replaced with a compact summary so
    the caller knows to request a narrower query.
    """
    if len(payload.encode("utf-8", errors="replace")) <= max_bytes:
        return payload

    try:
        data = json.loads(payload)
        byte_count = len(payload.encode("utf-8", errors="replace"))
        return json.dumps({
            "truncated": True,
            "original_bytes": byte_count,
            "max_bytes": max_bytes,
            "hint": "Response too large for stdio transport. Use narrower filters or request fewer results.",
            "preview": _preview(data),
        })
    except (json.JSONDecodeError, Exception):
        return payload[:max_bytes - 100] + '\n{"truncated": true}'


def _preview(data: dict) -> str:
    if "results" in data:
        count = len(data["results"])
        ids = [r.get("chunk_id", "?") for r in data["results"][:5]]
        return f"{count} results, first IDs: {ids}"
    if "full_text" in data:
        words = len(data["full_text"].split())
        return f"Section with {words} words, {data.get('chunk_count', '?')} chunks"
    if "notes" in data:
        return f"{len(data['notes'])} notes"
    return str(data)[:200]


from tools.search_tools import register_search_tools
from tools.session_tools import register_session_tools
from tools.notes_tools import register_notes_tools

register_search_tools(mcp, truncate_response)
register_session_tools(mcp, truncate_response)
register_notes_tools(mcp, truncate_response)

logger.info("Registered all 8 tools on server 'flowsim-tutor'")

if __name__ == "__main__":
    mcp.run(transport="stdio")
