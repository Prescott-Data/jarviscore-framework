"""
FAISS-backed vector store for RAG.
Stores vectors + metadata locally.

Optional dependency — install with: pip install jarviscore[rag]
"""
import os
import json
import logging
import numpy as np
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    import faiss
    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False
    faiss = None  # type: ignore[assignment]


class FaissVectorStore:
    def __init__(self, index_path: str, meta_path: str, dim: int):
        if not _HAS_FAISS:
            raise ImportError(
                "faiss-cpu is required for vector storage. "
                "Install with: pip install jarviscore[rag]"
            )
        self.index_path = index_path
        self.meta_path = meta_path
        self.dim = dim
        self._index = self._load_or_create_index()
        self._metadata = self._load_metadata()

    def _load_or_create_index(self):
        if os.path.exists(self.index_path):
            return faiss.read_index(self.index_path)
        return faiss.IndexFlatIP(self.dim)

    def _load_metadata(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.meta_path):
            return []
        with open(self.meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        faiss.write_index(self._index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f)

    def add(self, vectors: List[List[float]], metadatas: List[Dict[str, Any]]) -> None:
        if not vectors:
            return
        faiss_vectors = np.array(vectors, dtype="float32")
        self._index.add(faiss_vectors)
        self._metadata.extend(metadatas)
        self._persist()

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        if self._index.ntotal == 0:
            return []
        q = np.array([query_vector], dtype="float32")
        scores, indices = self._index.search(q, top_k)
        results: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = self._metadata[idx].copy()
            meta["score"] = float(score)
            results.append(meta)
        return results

    def stats(self) -> Dict[str, Any]:
        return {
            "index_path": self.index_path,
            "meta_path": self.meta_path,
            "vector_count": int(self._index.ntotal),
            "metadata_count": len(self._metadata),
            "dim": self.dim,
        }
