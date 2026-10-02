"""
Embedding model wrapper for RAG.

Uses sentence-transformers for local embedding generation.
Optional dependency — install with: pip install jarviscore[rag]
"""
import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from sentence_transformers import SentenceTransformer
    _HAS_ST = True
except ImportError:
    _HAS_ST = False
    SentenceTransformer = None  # type: ignore[assignment,misc]


class EmbeddingModel:
    def __init__(
        self,
        model_name: str,
        model_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        query_instruction: str = "",
    ):
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
        self.query_instruction = query_instruction

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    def embed_query(self, query: str) -> List[float]:
        """Asymmetric retrieval models expect their query instruction on queries only."""
        return self.embed([self.query_instruction + query])[0]


class Reranker:
    """Cross-encoder that reads each (query, passage) pair together."""

    def __init__(self, model_name: str, cache_dir: Optional[str] = None, max_length: int = 512):
        if not _HAS_ST:
            raise ImportError(
                "sentence-transformers is required for reranking. "
                "Install with: pip install jarviscore[rag]"
            )
        from sentence_transformers import CrossEncoder

        kwargs = {"max_length": max_length}
        if cache_dir:
            kwargs["cache_folder"] = cache_dir
        self.model = CrossEncoder(model_name, **kwargs)

    def score(self, query: str, passages: List[str]) -> List[float]:
        return self.score_pairs([(query, p) for p in passages])

    def score_pairs(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Score many (query, passage) pairs in one batched pass."""
        if not pairs:
            return []
        return [float(s) for s in self.model.predict(pairs, batch_size=128)]
