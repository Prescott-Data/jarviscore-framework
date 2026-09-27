"""
FAISS-backed vector store for RAG.
Stores vectors + metadata locally.

Reads use a per-thread immutable snapshot. A writer updates the live index and
metadata while holding the state lock, then advances a generation counter.
Readers clone a new snapshot only after that counter changes and perform the
potentially expensive FAISS search without holding the lock. This allows
concurrent retrieval without sharing a mutable FAISS index between threads.

Optional dependency — install with: pip install jarviscore[rag]
"""
import copy
import json
import logging
import os
import threading
from typing import Any, Dict, List, Tuple

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

try:
    import faiss
    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False
    faiss = None  # type: ignore[assignment]


class FaissVectorStore:
    """Persistent FAISS store with concurrent read snapshots.

    ``add`` is serialized with a short state lock. ``search`` and
    ``search_many`` clone the current index once per thread and run outside
    that lock, so concurrent readers do not race on FAISS's mutable index
    object or block each other for the duration of a search.
    """

    def __init__(self, index_path: str, meta_path: str, dim: int):
        if not _HAS_FAISS or np is None:
            raise ImportError(
                "faiss-cpu is required for vector storage. "
                "Install with: pip install jarviscore[rag]"
            )
        self.index_path = index_path
        self.meta_path = meta_path
        self.dim = dim
        self._index = self._load_or_create_index()
        self._metadata = self._load_metadata()
        self._metadata_snapshot = tuple(copy.deepcopy(metadata) for metadata in self._metadata)
        self._state_lock = threading.RLock()
        self._generation = 0
        self._read_state = threading.local()

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
        with self._state_lock:
            self._index.add(faiss_vectors)
            self._metadata.extend(metadatas)
            self._metadata_snapshot = tuple(
                copy.deepcopy(metadata) for metadata in self._metadata
            )
            self._generation += 1
            self._persist()

    def _read_snapshot(self) -> Tuple[Any, Tuple[Dict[str, Any], ...]]:
        """Return a thread-local snapshot matching the current generation."""
        with self._state_lock:
            generation = self._generation
            cached_generation = getattr(self._read_state, "generation", None)
            if cached_generation != generation:
                self._read_state.index = faiss.clone_index(self._index)
                self._read_state.metadata = self._metadata_snapshot
                self._read_state.generation = generation
            return self._read_state.index, self._read_state.metadata

    @staticmethod
    def _search_results(
        scores: Any,
        indices: Any,
        metadata: Tuple[Dict[str, Any], ...],
    ) -> List[List[Dict[str, Any]]]:
        results: List[List[Dict[str, Any]]] = []
        for score_row, index_row in zip(scores, indices):
            query_results: List[Dict[str, Any]] = []
            for score, idx in zip(score_row, index_row):
                idx = int(idx)
                if idx < 0 or idx >= len(metadata):
                    continue
                meta = metadata[idx].copy()
                meta["score"] = float(score)
                query_results.append(meta)
            results.append(query_results)
        return results

    def search_many(
        self, query_vectors: List[List[float]], top_k: int = 5
    ) -> List[List[Dict[str, Any]]]:
        """Search all query vectors in one FAISS call.

        The returned outer list always follows the input query order. Empty
        stores and empty query batches return the corresponding number of
        empty result lists without invoking FAISS.
        """
        if not query_vectors:
            return []
        index, metadata = self._read_snapshot()
        if index.ntotal == 0:
            return [[] for _ in query_vectors]
        queries = np.array(query_vectors, dtype="float32")
        scores, indices = index.search(queries, top_k)
        return self._search_results(scores, indices, metadata)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        return self.search_many([query_vector], top_k=top_k)[0]

    def stats(self) -> Dict[str, Any]:
        with self._state_lock:
            return {
                "index_path": self.index_path,
                "meta_path": self.meta_path,
                "vector_count": int(self._index.ntotal),
                "metadata_count": len(self._metadata),
                "dim": self.dim,
            }
