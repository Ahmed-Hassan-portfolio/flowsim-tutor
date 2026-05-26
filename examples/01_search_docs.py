"""Example 1 -- direct retriever use.

Runs a single ``search_docs`` query against the local index without going
through MCP. Useful for quickly poking at the corpus.

Prerequisites:
    1. cd to the project root.
    2. ``python index_docs.py`` to build the index.

Then:
    python examples/01_search_docs.py "how do I set the time step"
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag.retriever import FlowsimRetriever


def main() -> None:
    query = " ".join(sys.argv[1:]) or "how do I set the time step"

    retriever = FlowsimRetriever(
        chroma_dir=PROJECT_ROOT / "data" / "chroma_db",
        bm25_path=PROJECT_ROOT / "data" / "bm25_index.pkl",
    )

    result = retriever.search_docs(query, top_k=3)

    print(f"Query:      {result['query']}")
    print(f"Confidence: {result['confidence']}")
    print(f"Candidates: {result['total_candidates']}")
    print()

    for i, r in enumerate(result["results"], 1):
        print(f"--- Result {i} ---")
        print(f"  Source:       {r['source_file']}")
        print(f"  Section:      {r['section_path']}")
        print(f"  RRF score:    {r['rrf_score']:.4f}")
        snippet = r["snippet"]
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."
        print(f"  Snippet:\n    {snippet.replace(chr(10), chr(10) + '    ')}")
        print()


if __name__ == "__main__":
    main()
