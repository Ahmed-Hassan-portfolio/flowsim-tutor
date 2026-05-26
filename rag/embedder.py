"""Singleton embedding model for the FlowSim Tutor RAG pipeline.

Uses ``all-MiniLM-L6-v2`` (384-dim) loaded once via ``lru_cache``.
"""

import os
from functools import lru_cache
from typing import List

import numpy as np

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model():
    """Load model once, cache forever."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def encode_texts(texts: List[str], normalize: bool = True) -> np.ndarray:
    """Encode texts to (N, 384) embeddings; normalize for cosine by default."""
    model = _get_model()
    embeddings = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=normalize,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embeddings


def encode_query(query: str, normalize: bool = True) -> np.ndarray:
    """Encode a single query. Returns shape (384,)."""
    return encode_texts([query], normalize=normalize)[0]
