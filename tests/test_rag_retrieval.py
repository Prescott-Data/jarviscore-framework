"""Regression tests for batched and concurrent RAG retrieval."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from jarviscore.rag.faiss_store import FaissVectorStore
from jarviscore.rag.pipeline import RagPipeline


class _RecordingEmbedding:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(sum(ord(char) for char in text))] for text in texts]


class _RecordingStore:
    def __init__(self):
        self.calls = []

    def search_many(self, vectors, top_k):
        self.calls.append((vectors, top_k))
        return [
            [
                {
                    "source": f"source-{int(vector[0])}",
                    "chunk_index": 0,
                    "text": f"passage-{int(vector[0])}",
                    "metadata": {},
                    "score": 0.8,
                }
            ]
            for vector in vectors
        ]


def _pipeline_for_test():
    pipeline = RagPipeline.__new__(RagPipeline)
    pipeline.embedding = _RecordingEmbedding()
    pipeline.store = _RecordingStore()
    return pipeline


def test_retrieve_many_matches_single_query_results_and_batches_io():
    queries = ["first query", "second query", "third query"]
    batch_pipeline = _pipeline_for_test()
    batch = batch_pipeline.retrieve_many(queries, top_k=2)

    single_pipeline = _pipeline_for_test()
    singles = [single_pipeline.retrieve(query, top_k=2) for query in queries]

    assert batch == singles
    assert batch_pipeline.embedding.calls == [queries]
    assert len(batch_pipeline.store.calls) == 1
    assert batch_pipeline.store.calls[0][1] == 2
    assert len(single_pipeline.embedding.calls) == len(queries)
    assert len(single_pipeline.store.calls) == len(queries)


def test_retrieve_many_empty_batch_does_not_touch_dependencies():
    pipeline = _pipeline_for_test()

    assert pipeline.retrieve_many([]) == []
    assert pipeline.embedding.calls == []
    assert pipeline.store.calls == []


def test_retrieve_many_rejects_non_string_queries_before_embedding():
    pipeline = _pipeline_for_test()

    with pytest.raises(TypeError, match="only strings"):
        pipeline.retrieve_many(["valid", 42])

    assert pipeline.embedding.calls == []
    assert pipeline.store.calls == []


class _SearchTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.search_batches = []
        self.clone_count = 0


class _FakeNumpy:
    @staticmethod
    def array(value, dtype=None):
        return value


class _ConcurrentFakeIndex:
    """A fake index that fails if one mutable instance is searched concurrently."""

    def __init__(self, tracker, *, clone=False):
        self.tracker = tracker
        self.ntotal = 2
        self._active = 0
        if clone:
            tracker.clone_count += 1

    def clone(self):
        return _ConcurrentFakeIndex(self.tracker, clone=True)

    def search(self, queries, top_k):
        with self.tracker.lock:
            self._active += 1
            self.tracker.active += 1
            self.tracker.max_active = max(self.tracker.max_active, self.tracker.active)
            if self._active > 1:
                raise AssertionError("a mutable FAISS index was searched concurrently")
            self.tracker.search_batches.append(len(queries))
        try:
            time.sleep(0.03)
            scores = [[0.9, 0.5] for _ in queries]
            indices = [[0, 1] for _ in queries]
            return [row[:top_k] for row in scores], [row[:top_k] for row in indices]
        finally:
            with self.tracker.lock:
                self._active -= 1
                self.tracker.active -= 1


def test_faiss_batch_search_and_concurrent_reads_use_private_snapshots(monkeypatch):
    tracker = _SearchTracker()
    root_index = _ConcurrentFakeIndex(tracker)
    fake_faiss = SimpleNamespace(clone_index=lambda index: index.clone())
    monkeypatch.setattr("jarviscore.rag.faiss_store.faiss", fake_faiss)
    monkeypatch.setattr("jarviscore.rag.faiss_store.np", _FakeNumpy())

    store = FaissVectorStore.__new__(FaissVectorStore)
    store._index = root_index
    store._metadata = [
        {"source": "alpha", "text": "A"},
        {"source": "beta", "text": "B"},
    ]
    store._metadata_snapshot = tuple(store._metadata)
    store._state_lock = threading.RLock()
    store._generation = 0
    store._read_state = threading.local()

    batch = store.search_many([[1.0], [2.0]], top_k=2)
    assert [[item["source"] for item in results] for results in batch] == [
        ["alpha", "beta"],
        ["alpha", "beta"],
    ]
    assert tracker.search_batches == [2]

    serial_start = time.perf_counter()
    for _ in range(4):
        store.search([1.0], 1)
    serial_elapsed = time.perf_counter() - serial_start

    concurrent_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(store.search, [1.0], 1) for _ in range(4)]
        results = [future.result(timeout=2) for future in futures]
    concurrent_elapsed = time.perf_counter() - concurrent_start

    assert all(result[0]["source"] == "alpha" for result in results)
    assert tracker.clone_count >= 2
    assert tracker.max_active >= 2
    assert concurrent_elapsed < serial_elapsed * 0.8
