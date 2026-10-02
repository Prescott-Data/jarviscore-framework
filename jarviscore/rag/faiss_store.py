"""
FAISS-backed vector store for RAG.
Stores vectors + metadata locally.

Optional dependency — install with: pip install jarviscore[rag]
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

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
            index = faiss.read_index(self.index_path)
            if index.d != self.dim:
                raise ValueError(
                    f"Index at {self.index_path} holds {index.d}-dimensional vectors but the "
                    f"embedding model produces {self.dim}; rebuild the index for this model."
                )
            return index
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

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if self._index.ntotal == 0:
            return []
        q = np.array([query_vector], dtype="float32")
        search_depth = int(self._index.ntotal) if where else top_k
        scores, indices = self._index.search(q, search_depth)
        results: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            if where and not self._matches(self._metadata[idx], where):
                continue
            meta = self._metadata[idx].copy()
            meta["score"] = float(score)
            results.append(meta)
            if len(results) >= top_k:
                break
        return results

    @staticmethod
    def _matches(entry: Dict[str, Any], where: Dict[str, Any]) -> bool:
        """Filter fields live in the caller's metadata; entry fields such as source also apply."""
        caller = entry.get("metadata") or {}
        for field, expected in where.items():
            value = caller[field] if field in caller else entry.get(field)
            if isinstance(expected, (list, tuple, set, frozenset)):
                if value not in expected:
                    return False
            elif value != expected:
                return False
        return True

    def delete(self, where: Dict[str, Any]) -> int:
        """Remove matching entries, keeping every other stored vector without re-embedding."""
        if not where:
            raise ValueError("delete requires a filter")
        keep = [
            position for position, entry in enumerate(self._metadata)
            if not self._matches(entry, where)
        ]
        removed = len(self._metadata) - len(keep)
        if not removed:
            return 0
        index = faiss.IndexFlatIP(self.dim)
        if keep:
            vectors = self._index.reconstruct_n(0, int(self._index.ntotal))
            index.add(np.ascontiguousarray(vectors[keep], dtype="float32"))
        self._index = index
        self._metadata = [self._metadata[position] for position in keep]
        self._persist()
        return removed

    def stats(self) -> Dict[str, Any]:
        return {
            "index_path": self.index_path,
            "meta_path": self.meta_path,
            "vector_count": int(self._index.ntotal),
            "metadata_count": len(self._metadata),
            "dim": self.dim,
        }
