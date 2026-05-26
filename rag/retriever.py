"""Hybrid retrieval engine for the FlowSim Tutor RAG pipeline.

Combines ChromaDB vector search with BM25 keyword search via Reciprocal Rank
Fusion (RRF). Returns query-aware snippets with confidence scoring.
"""

import pickle
import re
from collections import defaultdict
from pathlib import Path
from typing import List, Optional

import chromadb

from rag.embedder import encode_query

RRF_K = 60
RETRIEVER_TOP_N = 20
SNIPPET_MAX_TOKENS = 300
CONFIDENCE_MIN_RRF = 0.025
CONFIDENCE_MAX_DISTANCE = 0.85


class FlowsimRetriever:
    """Hybrid retrieval engine combining vector and keyword search.

    Implements:
        - RRF fusion (k=60) over ChromaDB (vector) and BM25 (keyword)
        - Query-aware snippet extraction with keyword overlap scoring
        - Step sequence preservation during snippet extraction
        - Section-level deduplication
        - Low-confidence detection
        - Source file filtering
    """

    def __init__(self, chroma_dir: Path, bm25_path: Path, collection_name: str = "flowsim_docs"):
        client = chromadb.PersistentClient(path=str(chroma_dir.resolve()))
        self._collection = client.get_collection(collection_name)

        with open(bm25_path, "rb") as f:
            data = pickle.load(f)
        self._bm25 = data["bm25"]
        self._bm25_chunk_ids = data["chunk_ids"]

    def search_docs(
        self,
        query: str,
        top_k: int = 10,
        source_filter: Optional[str] = None,
    ) -> dict:
        """Search documents using hybrid retrieval with RRF fusion."""
        query_emb = encode_query(query)
        where_filter = {"source_file": source_filter} if source_filter else None

        chroma_results = self._collection.query(
            query_embeddings=[query_emb.tolist()],
            n_results=RETRIEVER_TOP_N,
            include=["documents", "metadatas", "distances"],
            where=where_filter,
        )

        chroma_ranked = chroma_results["ids"][0] if chroma_results["ids"] else []
        chroma_distances = {}
        if chroma_results["distances"] and chroma_results["distances"][0]:
            for i, chunk_id in enumerate(chroma_ranked):
                chroma_distances[chunk_id] = chroma_results["distances"][0][i]

        tokens = re.findall(r"[a-z0-9_]+", query.lower())
        scores = self._bm25.get_scores(tokens)

        top_indices = scores.argsort()[-RETRIEVER_TOP_N:][::-1]
        bm25_ranked = [
            self._bm25_chunk_ids[i] for i in top_indices if scores[i] > 0
        ]

        if source_filter and bm25_ranked:
            bm25_ranked = self._filter_by_source(bm25_ranked, source_filter)

        fused = defaultdict(float)
        for ranked_list in [chroma_ranked, bm25_ranked]:
            for rank, chunk_id in enumerate(ranked_list, start=1):
                fused[chunk_id] += 1.0 / (RRF_K + rank)

        sorted_results = sorted(fused.items(), key=lambda x: x[1], reverse=True)

        all_chunk_ids = [chunk_id for chunk_id, _ in sorted_results]
        if not all_chunk_ids:
            return {
                "results": [],
                "confidence": "low",
                "query": query,
                "total_candidates": 0,
            }

        batch_data = self._collection.get(
            ids=all_chunk_ids,
            include=["documents", "metadatas"],
        )

        id_to_doc = {}
        id_to_meta = {}
        for i, chunk_id in enumerate(batch_data["ids"]):
            id_to_doc[chunk_id] = batch_data["documents"][i]
            id_to_meta[chunk_id] = batch_data["metadatas"][i]

        seen_sections = set()
        deduped_results = []
        for chunk_id, rrf_score in sorted_results:
            meta = id_to_meta.get(chunk_id, {})
            section_path = meta.get("section_path", chunk_id)

            if section_path in seen_sections:
                continue
            seen_sections.add(section_path)

            doc_text = id_to_doc.get(chunk_id, "")
            snippet = self._extract_snippet(doc_text, query)

            deduped_results.append({
                "chunk_id": chunk_id,
                "section_path": section_path,
                "source_file": meta.get("source_file", ""),
                "snippet": snippet,
                "rrf_score": float(rrf_score),
                "heading": meta.get("h2_header", "") or meta.get("section_path", ""),
            })

            if len(deduped_results) >= top_k:
                break

        best_rrf_score = sorted_results[0][1] if sorted_results else 0
        best_chroma_distance = (
            min(chroma_distances.values()) if chroma_distances else 2.0
        )
        low_confidence = (
            best_rrf_score < CONFIDENCE_MIN_RRF
            or best_chroma_distance > CONFIDENCE_MAX_DISTANCE
        )

        return {
            "results": deduped_results,
            "confidence": "low" if low_confidence else "high",
            "query": query,
            "total_candidates": len(fused),
        }

    def get_full_section(self, section_id: str) -> dict:
        """Get complete text for a section by ID, joining all sub-chunks."""
        result = self._collection.get(
            ids=[section_id],
            include=["documents", "metadatas"],
        )

        if not result["ids"]:
            return {"error": f"Section '{section_id}' not found"}

        meta = result["metadatas"][0]
        section_path = meta.get("section_path", section_id)
        source_file = meta.get("source_file", "")

        all_chunks = self._collection.get(
            where={"section_path": section_path},
            include=["documents", "metadatas"],
        )

        if not all_chunks["ids"]:
            full_text = result["documents"][0]
            return {
                "section_id": section_id,
                "section_path": section_path,
                "source_file": source_file,
                "full_text": full_text,
                "chunk_count": 1,
                "token_count": len(full_text.split()),
            }

        chunk_data = list(
            zip(
                all_chunks["ids"],
                all_chunks["documents"],
                all_chunks["metadatas"],
            )
        )
        chunk_data.sort(key=lambda x: x[2].get("chunk_index", 0))

        full_text = "\n\n".join(doc for _, doc, _ in chunk_data)

        return {
            "section_id": section_id,
            "section_path": section_path,
            "source_file": source_file,
            "full_text": full_text,
            "chunk_count": len(chunk_data),
            "token_count": len(full_text.split()),
        }

    def _filter_by_source(
        self, chunk_ids: List[str], source_filter: str
    ) -> List[str]:
        if not chunk_ids:
            return []

        result = self._collection.get(ids=chunk_ids, include=["metadatas"])

        filtered = []
        for i, chunk_id in enumerate(result["ids"]):
            meta = result["metadatas"][i]
            if meta.get("source_file") == source_filter:
                filtered.append(chunk_id)

        return filtered

    def _extract_snippet(
        self, text: str, query: str, max_tokens: int = SNIPPET_MAX_TOKENS
    ) -> str:
        """Extract a query-aware snippet from text."""
        tokens = text.split()
        if len(tokens) <= max_tokens:
            return text

        paragraphs = re.split(r"\n\n+", text.strip())
        if not paragraphs:
            return text[:max_tokens * 5]

        merged_paragraphs = self._merge_step_sequences(paragraphs)

        query_terms = set(re.findall(r"[a-z0-9_]+", query.lower()))
        scored = []
        for i, para in enumerate(merged_paragraphs):
            para_terms = set(re.findall(r"[a-z0-9_]+", para.lower()))
            overlap = len(query_terms & para_terms)
            score = overlap / max(len(query_terms), 1)
            scored.append((i, para, score, len(para.split())))

        scored.sort(key=lambda x: x[2], reverse=True)

        if not scored:
            return text[:max_tokens * 5]

        best_idx = scored[0][0]
        selected_indices = {best_idx}
        current_tokens = scored[0][3]

        neighbors = []
        if best_idx > 0:
            neighbors.append(best_idx - 1)
        if best_idx < len(merged_paragraphs) - 1:
            neighbors.append(best_idx + 1)

        for neighbor_idx in neighbors:
            neighbor_tokens = len(merged_paragraphs[neighbor_idx].split())
            if current_tokens + neighbor_tokens <= max_tokens:
                selected_indices.add(neighbor_idx)
                current_tokens += neighbor_tokens

        result_paragraphs = [
            merged_paragraphs[i]
            for i in sorted(selected_indices)
        ]
        return "\n\n".join(result_paragraphs)

    def _merge_step_sequences(self, paragraphs: List[str]) -> List[str]:
        """Merge consecutive numbered step paragraphs into single blocks."""
        step_pattern = re.compile(r"^\s*\d+[\.\)]\s")
        merged = []
        current_step_block = []

        for para in paragraphs:
            if step_pattern.match(para):
                current_step_block.append(para)
            else:
                if current_step_block:
                    merged.append("\n".join(current_step_block))
                    current_step_block = []
                merged.append(para)

        if current_step_block:
            merged.append("\n".join(current_step_block))

        return merged
