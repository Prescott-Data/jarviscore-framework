"""
Embedding model wrapper for RAG.

Uses sentence-transformers for local embedding generation.
Optional dependency — install with: pip install jarviscore[rag]
"""
from typing import List, Optional
import os
import logging

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except ImportError:
    _HAS_ST = False
    SentenceTransformer = None  # type: ignore[assignment,misc]


class EmbeddingModel:
    def __init__(self, model_name: str, model_path: Optional[str] = None, cache_dir: Optional[str] = None):
        if not _HAS_ST:
            raise ImportError(
                "sentence-transformers is required for embeddings. "
                "Install with: pip install jarviscore[rag]"
            )
        resolved = None
        if model_path:
            candidate = os.path.abspath(model_path)
            if os.path.exists(candidate):
                resolved = candidate
        model_id = resolved or model_name
        if cache_dir:
            self.model = SentenceTransformer(model_id, cache_folder=cache_dir)
        else:
            self.model = SentenceTransformer(model_id)

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()
