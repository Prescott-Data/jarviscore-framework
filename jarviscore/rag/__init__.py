"""
jarviscore.rag — Retrieval-Augmented Generation pipeline.

Provides evidence-backed retrieval using local FAISS vector indices
and sentence-transformer embeddings.

Components:
    - RagPipeline: orchestrator (ingest, retrieve, stats)
    - EmbeddingModel: sentence-transformers wrapper
    - FaissVectorStore: local vector persistence
    - chunk_text: paragraph-aware text chunking
    - evidence scoring: freshness-weighted confidence

Usage:
    from jarviscore.rag import RagPipeline

    pipeline = RagPipeline()
    pipeline.ingest_documents([{"source": "docs.md", "content": "..."}])
    results = pipeline.retrieve("how to authenticate")

Install:
    pip install jarviscore[rag]  # adds faiss-cpu + sentence-transformers
"""

# Lazy imports — everything fails gracefully without [rag] deps
try:
    from .pipeline import RagPipeline
except ImportError:
    RagPipeline = None  # type: ignore[assignment,misc]

try:
    from .embedding import EmbeddingModel
except ImportError:
    EmbeddingModel = None  # type: ignore[assignment,misc]

try:
    from .faiss_store import FaissVectorStore
except ImportError:
    FaissVectorStore = None  # type: ignore[assignment,misc]

from .chunking import chunk_text
from .evidence import build_evidence_record, score_evidence

__all__ = [
    "RagPipeline",
    "EmbeddingModel",
    "FaissVectorStore",
    "chunk_text",
    "build_evidence_record",
    "score_evidence",
]
