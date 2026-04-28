"""
RAG pipeline: ingestion, indexing, retrieval, and evidence scoring.

Ported from integration-agent-javiscore.
Settings adapted from src.config.settings to env vars.

Install: pip install jarviscore[rag]
"""
import logging
import os
from typing import List, Dict, Any, Optional

from jarviscore.rag.embedding import EmbeddingModel
from jarviscore.rag.chunking import chunk_text
from jarviscore.rag.faiss_store import FaissVectorStore
from jarviscore.rag.evidence import build_evidence_record

logger = logging.getLogger(__name__)

# ── Defaults (env-var driven, no settings singleton) ──
_DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_CHUNK_SIZE = 1200
_DEFAULT_CHUNK_OVERLAP = 200
_DEFAULT_TOP_K = 5
_DEFAULT_INDEX_PATH = os.path.join(os.path.expanduser("~"), ".jarviscore", "rag", "faiss.index")
_DEFAULT_META_PATH = os.path.join(os.path.expanduser("~"), ".jarviscore", "rag", "faiss_meta.json")


class RagPipeline:
    def __init__(self):
        model_name = os.environ.get("RAG_EMBED_MODEL", _DEFAULT_EMBED_MODEL)
        model_path = os.environ.get("RAG_EMBED_MODEL_PATH")
        cache_dir = os.environ.get("RAG_EMBED_CACHE_DIR")

        self.embedding = EmbeddingModel(
            model_name,
            model_path=model_path,
            cache_dir=cache_dir,
        )
        self.dim = self._infer_dim()
        self.store = self._init_store()

    def _init_store(self):
        """Pick vector store backend from RAG_VECTOR_STORE env var."""
        index_path = os.environ.get("RAG_INDEX_PATH", _DEFAULT_INDEX_PATH)
        meta_path = os.environ.get("RAG_META_PATH", _DEFAULT_META_PATH)

        # Ensure directory exists
        os.makedirs(os.path.dirname(index_path), exist_ok=True)

        logger.info("RagPipeline: using FAISS vector store (%s)", index_path)
        return FaissVectorStore(index_path, meta_path, self.dim)

    def _infer_dim(self) -> int:
        vec = self.embedding.embed(["dimension_probe"])[0]
        return len(vec)

    def ingest_documents(
        self,
        documents: List[Dict[str, Any]],
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        documents: list of {source, content, metadata?}
        """
        chunk_size = chunk_size or int(os.environ.get("RAG_CHUNK_SIZE", str(_DEFAULT_CHUNK_SIZE)))
        overlap = overlap or int(os.environ.get("RAG_CHUNK_OVERLAP", str(_DEFAULT_CHUNK_OVERLAP)))
        all_chunks: List[str] = []
        all_meta: List[Dict[str, Any]] = []

        for doc in documents:
            content = doc.get("content") or ""
            source = doc.get("source") or "unknown"
            meta = doc.get("metadata") or {}
            chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)
            for idx, c in enumerate(chunks):
                all_chunks.append(c)
                all_meta.append({
                    "source": source,
                    "chunk_index": idx,
                    "text": c,
                    "metadata": meta,
                })

        if not all_chunks:
            return {"status": "error", "error": "No content to ingest"}

        vectors = self.embedding.embed(all_chunks)
        self.store.add(vectors, all_meta)
        return {
            "status": "success",
            "documents": len(documents),
            "chunks": len(all_chunks),
        }

    def retrieve(self, query: str, top_k: Optional[int] = None) -> Dict[str, Any]:
        top_k = top_k or int(os.environ.get("RAG_TOP_K", str(_DEFAULT_TOP_K)))
        q_vec = self.embedding.embed([query])[0]
        results = self.store.search(q_vec, top_k=top_k)

        evidence = []
        for r in results:
            quote = r.get("text", "")
            source = r.get("source", "unknown")
            pointer = f"{source}#chunk_{r.get('chunk_index')}"
            evidence.append(build_evidence_record(
                source=source,
                quote=quote[:500],
                pointer=pointer,
                source_reliability=0.7,
                specificity=0.7,
                corroboration=0.5,
                model_confidence=min(1.0, max(0.2, r.get("score", 0.5))),
                published_at=r.get("metadata", {}).get("published_at"),
            ))

        return {
            "status": "success",
            "query": query,
            "top_k": top_k,
            "results": results,
            "evidence": evidence,
        }

    def stats(self) -> Dict[str, Any]:
        return self.store.stats()
