"""Run the retrieval evaluation suite against the indexed corpus.

Reads ``tests/evals/retrieval_eval.yaml``, runs each probe through the
``FlowsimRetriever``, and prints a pass/fail table plus the aggregate
source-recall and confidence-detection scores.

Prerequisites:
    1. ``python index_docs.py`` to build the local index in ``data/``.
    2. The full RAG dependencies must be installed (chromadb,
       sentence-transformers, rank-bm25).

Usage:
    python -m tests.evals.run_evals
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EVAL_YAML = Path(__file__).with_name("retrieval_eval.yaml")


@dataclass
class ProbeResult:
    probe_id: str
    source_passed: bool
    section_passed: bool
    detail: str

    @property
    def passed(self) -> bool:
        return self.source_passed and self.section_passed


def _parse_yaml(text: str) -> dict:
    """Minimal YAML reader covering the structure of retrieval_eval.yaml.

    We avoid pulling in PyYAML so the eval can run in the fast CI lane.
    Supports: top-level scalars (``key: value``), top-level lists of
    mappings (``- key: value``), and string values with or without quotes.
    """
    lines = text.splitlines()
    root: dict = {}
    current_list: list | None = None
    current_obj: dict | None = None
    current_list_key: str | None = None

    def _strip_value(value: str) -> str:
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]
        return value

    for raw in lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)

        if indent == 0 and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                root[key] = _coerce_scalar(_strip_value(value))
                current_list = None
                current_obj = None
                current_list_key = None
            else:
                current_list = []
                root[key] = current_list
                current_list_key = key
                current_obj = None
            continue

        if indent >= 2 and stripped.startswith("- "):
            if current_list is None:
                continue
            current_obj = {}
            current_list.append(current_obj)
            rest = stripped[2:]
            if rest and ":" in rest:
                k, _, v = rest.partition(":")
                current_obj[k.strip()] = _coerce_scalar(_strip_value(v.strip()))
            continue

        if indent >= 2 and ":" in stripped and current_obj is not None:
            k, _, v = stripped.partition(":")
            current_obj[k.strip()] = _coerce_scalar(_strip_value(v.strip()))

    return root


def _coerce_scalar(value: str):
    if value.isdigit():
        return int(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _run_one(retriever, probe: dict, top_k: int) -> ProbeResult:
    query = probe["query"]
    expected_source = probe["expected_source"]
    expected_section = probe.get("expected_section_contains", "").lower()

    result = retriever.search_docs(query, top_k=top_k)
    hits = result.get("results", [])

    found_source = any(r["source_file"] == expected_source for r in hits)
    found_section = (
        not expected_section
        or any(
            expected_section in (r.get("section_path") or "").lower()
            for r in hits
        )
    )

    detail = (
        f"top: {[(r['source_file'], r['section_path']) for r in hits]}"
    )
    return ProbeResult(
        probe["id"], found_source, found_section, detail,
    )


def _run_low_confidence(retriever, probe: dict, top_k: int) -> ProbeResult:
    query = probe["query"]
    result = retriever.search_docs(query, top_k=top_k)
    confidence = result.get("confidence", "high")
    expected = probe.get("expected_confidence", "low")
    passed = confidence == expected or not result.get("results")
    return ProbeResult(
        probe["id"],
        passed,
        passed,
        f"confidence={confidence}, results={len(result.get('results', []))}",
    )


def main() -> int:
    if not EVAL_YAML.exists():
        print(f"ERROR: eval definitions not found at {EVAL_YAML}", file=sys.stderr)
        return 2

    text = EVAL_YAML.read_text(encoding="utf-8")
    spec = _parse_yaml(text)

    top_k = spec.get("top_k", 5)
    probes = spec.get("probes", [])
    low_conf_probes = spec.get("low_confidence_probes", [])

    chroma_dir = PROJECT_ROOT / "data" / "chroma_db"
    bm25_path = PROJECT_ROOT / "data" / "bm25_index.pkl"
    if not chroma_dir.exists() or not bm25_path.exists():
        print(
            "ERROR: index not found. Run `python index_docs.py` first.",
            file=sys.stderr,
        )
        return 2

    from rag.retriever import FlowsimRetriever

    retriever = FlowsimRetriever(chroma_dir=chroma_dir, bm25_path=bm25_path)

    print(f"Running {len(probes)} retrieval probes (top_k={top_k}) "
          f"+ {len(low_conf_probes)} low-confidence probes\n")

    results: list[ProbeResult] = []
    for probe in probes:
        results.append(_run_one(retriever, probe, top_k))

    low_conf_results: list[ProbeResult] = []
    for probe in low_conf_probes:
        low_conf_results.append(_run_low_confidence(retriever, probe, top_k))

    print("Retrieval probes (source+section / source-only):")
    for r in results:
        if r.source_passed and r.section_passed:
            marker = "PASS"
        elif r.source_passed:
            marker = "SRC "
        else:
            marker = "FAIL"
        print(f"  [{marker}] {r.probe_id}")
        if not r.passed:
            print(f"         {r.detail}")

    print("\nLow-confidence probes:")
    for r in low_conf_results:
        marker = "PASS" if r.source_passed else "FAIL"
        print(f"  [{marker}] {r.probe_id}   {r.detail}")

    strict_pass = sum(1 for r in results if r.passed)
    source_pass = sum(1 for r in results if r.source_passed)
    confidence_pass = sum(1 for r in low_conf_results if r.source_passed)

    print(
        f"\nResults:"
        f"\n  retrieval strict (source+section): {strict_pass}/{len(results)}"
        f"\n  retrieval source-only:             {source_pass}/{len(results)}"
        f"\n  low-confidence:                    {confidence_pass}/{len(low_conf_results)}"
    )

    all_passed = (
        source_pass == len(results)
        and confidence_pass == len(low_conf_results)
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
