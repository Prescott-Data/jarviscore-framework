---
icon: material/book-search
---

# Knowledge Base (RAG)

JarvisCore includes a built-in Retrieval-Augmented Generation pipeline called `RagPipeline` that lets you give agents access to your own documents, wikis, and internal knowledge. When the `rag` extra is installed and a FAISS index exists, the `ResearcherSubAgent` gains a `rag_query` tool it can call during its OODA loop to retrieve relevant passages before or instead of web search.

The integration is tool-driven, not automatic injection. The Researcher decides when to call `rag_query` based on the task, exactly as it decides when to call `search_internet_batch`. This means the Researcher can blend local knowledge with live web results on the same query.

---

## How It Works

```
Your documents (PDFs, markdown, text, APIs)
         ↓
    RagPipeline.ingest_documents()
         ↓
    Chunk by paragraph  →  Embed with sentence-transformers
         ↓
    FAISS index  (~/.jarviscore/rag/faiss.index)
         ↓
    ResearcherSubAgent.retrieve(query)
         ↓
    Top-K chunks ranked by cosine similarity
         ↓
    Injected as Evidence into agent context window
```

The agent doesn't change. You don't modify system prompts. The RAG layer is plumbed into the `ResearcherSubAgent` at the framework level.

---

## Installation

RAG dependencies are optional — install the `rag` extra:

```bash
pip install "jarviscore[rag]"
```

This installs:
- `sentence-transformers` — local embedding generation (no API key required)
- `faiss-cpu` — FAISS vector store

---

## Ingesting Documents

`RagPipeline.ingest_documents()` accepts a list of document dicts. Each dict must have a `content` key and a `source` key.

```python
from jarviscore.rag import RagPipeline

rag = RagPipeline()

result = rag.ingest_documents([
    {
        "source": "llm-intro",
        "content": open("docs/llm-introduction.md").read(),
        "metadata": {"author": "Karpathy", "topic": "LLMs"},
    },
    {
        "source": "transformer-notes",
        "content": open("docs/transformers.md").read(),
        "metadata": {"topic": "architecture"},
    },
])

print(result)
# {"status": "success", "documents": 2, "chunks": 47}
```

`ingest_documents()` chunks each document into overlapping segments, embeds them, and adds them to the FAISS index. The index is persisted to disk immediately — you only need to ingest once.

### Document format

| Key | Required | Description |
|---|---|---|
| `content` | Yes | The document text (markdown, plain text, extracted PDF, etc.) |
| `source` | Yes | A stable identifier — used for citation and deduplication |
| `metadata` | No | Arbitrary dict stored alongside each chunk (author, date, topic, etc.) |

---

## Retrieving Context

To use the RAG pipeline directly without going through an agent:

```python
rag = RagPipeline()

result = rag.retrieve("How does attention work in transformers?", top_k=5)

for chunk in result["results"]:
    print(f"Source: {chunk['source']}")
    print(f"Score:  {chunk['score']:.3f}")
    print(f"Text:   {chunk['text'][:200]}\n")
```

The `result["evidence"]` key contains a list of `Evidence` records, each with a confidence score derived from the cosine similarity, ready to be passed to a `TruthContext` or logged to the episodic ledger.

---

## Automatic Integration with ResearcherSubAgent

When `jarviscore[rag]` is installed, the `ResearcherSubAgent` registers a `rag_query` tool in its OODA loop. During research, the Researcher will call this tool when it has established context that local documentation may already cover, then uses the retrieved passages as evidence alongside web search results.

The Researcher also auto-ingests content it fetches from the web during a session so that later steps can retrieve it via `rag_query`. This behaviour is controlled by the `RAG_AUTO_INGEST` environment variable:

```bash title=".env"
# Default: enabled. Set to false to prevent automatic ingestion of fetched pages.
RAG_AUTO_INGEST=true
```

This means any `AutoAgent` that routes to `researcher` gets local knowledge augmentation with zero additional code, as long as you have ingested your documents beforehand and have `RAG_EMBED_MODEL` and the FAISS index configured.

```python
class LLMResearchAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "llm-knowledge"]
    system_prompt = """
    You are an LLM research specialist with access to curated technical documents.
    Use rag_query to retrieve established concepts from local knowledge.
    Use search_internet_batch for recent or breaking developments.
    Always store your final output in `result`.
    """
```

Just ingest your documents before starting the Mesh. The Researcher will call `rag_query` when appropriate.

---

## Ingesting from a URL (Karpathy-style LLM wikis)

To ingest from online sources like Karpathy's LLM intro, fetch the content and pass it directly:

```python
import httpx
from jarviscore.rag import RagPipeline

rag = RagPipeline()

# Fetch markdown from any public URL
response = httpx.get("https://raw.githubusercontent.com/karpathy/LLM101n/main/README.md")
response.raise_for_status()

rag.ingest_documents([
    {
        "source": "karpathy-llm101n",
        "content": response.text,
        "metadata": {"author": "Karpathy", "topic": "LLMs", "url": response.url},
    }
])
```

For large wikis, split by page and ingest each page as a separate document. The chunker handles the size boundaries automatically.

---

## Keeping the Index Fresh

The FAISS index accumulates documents — there is no automatic deduplication by `source`. If you re-ingest the same source, you get duplicate chunks. Manage this by deleting and rebuilding the index when your source documents change:

```bash
rm ~/.jarviscore/rag/faiss.index
rm ~/.jarviscore/rag/faiss_meta.json
# Re-run your ingest script
python scripts/ingest_knowledge.py
```

Check index stats at any time:

```python
rag = RagPipeline()
print(rag.stats())
# {"index_path": "...", "meta_path": "...", "vector_count": 247, "metadata_count": 247, "dim": 384}
```

---

## Configuration

```bash title=".env"
# Embedding model (default: all-MiniLM-L6-v2 — fast, 384-dim)
RAG_EMBED_MODEL=all-MiniLM-L6-v2

# Use a larger model for higher recall quality (slower)
# RAG_EMBED_MODEL=all-mpnet-base-v2

# Custom model path (use a local sentence-transformers model)
# RAG_EMBED_MODEL_PATH=/models/my-embedder

# FAISS index location (default: ~/.jarviscore/rag/)
RAG_INDEX_PATH=/data/rag/faiss.index
RAG_META_PATH=/data/rag/faiss_meta.json

# Retrieval settings
RAG_TOP_K=5
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=200
```

| Variable | Default | Description |
|---|---|---|
| `RAG_EMBED_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model name or HuggingFace ID |
| `RAG_EMBED_MODEL_PATH` | — | Path to a local model directory |
| `RAG_INDEX_PATH` | `~/.jarviscore/rag/faiss.index` | FAISS index file location |
| `RAG_META_PATH` | `~/.jarviscore/rag/faiss_meta.json` | Chunk metadata sidecar |
| `RAG_TOP_K` | `5` | Number of chunks returned per query |
| `RAG_CHUNK_SIZE` | `1200` | Max characters per chunk |
| `RAG_CHUNK_OVERLAP` | `200` | Overlap between consecutive chunks |

---

## Further Reading

- [Internet Search](internet-search.md) — Web search providers that ResearcherSubAgent runs alongside RAG
- [AutoAgent Guide](autoagent.md) — How ResearcherSubAgent fits into the OODA loop
- [Integrations](integrations.md) — Atoms and system bundles that extend what agents can do
