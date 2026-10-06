---
icon: material/book-search
title: "Build an AI Agent Knowledge Base with RAG"
description: "Ingest PDF, Markdown, and text documents into FAISS so JarvisCore research agents can combine internal knowledge with live web results."
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

RAG dependencies are optional: install the `rag` extra:

```bash
pip install "jarviscore[rag]"
```

This installs:
- `sentence-transformers`: local embedding generation (no API key required)
- `faiss-cpu`: FAISS vector store

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

`ingest_documents()` chunks each document into overlapping segments, embeds them, and adds them to the FAISS index. The index is persisted to disk immediately: you only need to ingest once.

### Document format

| Key | Required | Description |
|---|---|---|
| `content` | Yes | The document text (markdown, plain text, extracted PDF, etc.) |
| `source` | Yes | A stable identifier: used for citation and deduplication |
| `metadata` | No | Arbitrary dict stored alongside each chunk (author, date, topic, etc.) |
| `units` | No | Exact spans of `content` to index instead of chunking it, such as table rows or clauses. Each must appear verbatim in `content`. |
| `context` | No | Text that situates every unit in its document, such as the document title. It is embedded and reranked with each unit but never returned as quoted text. |
| `citation_atoms` | No | Exact quotes with source locators (`{"quote": ..., "locator": {...}}`). Each quote must appear in `content`; a result carries only the atoms whose quote is inside it. |

### Index units and context

Chunking splits text by length, so a table row can be cut in half or merged
with its neighbours. Declare the units instead when the document has a natural
grain, and situate each unit with `context` so a row from one company's filing
cannot answer for another:

```python
rows = [
    "Total revenues | Q2 2025 $ 407,344 | Q2 2024 $ 400,615",
    "Net loss | Q2 2025 $ (3,300) | Q2 2024 $ (5,220)",
]
rag.ingest_documents([{
    "source": "10q-2025q2:table-3",
    "content": "Condensed statement of operations\n" + "\n".join(rows),
    "units": rows,
    "context": "Informatica Inc. Q2 2025 Form 10-Q",
    "metadata": {"upload_id": "10q-v1"},
}])
```

Each row is retrieved on its own, and the result's `text` is the row exactly as
it appears in the document.

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

The `result["evidence"]` key contains a list of `Evidence` records, each with a confidence score derived from the cosine similarity, ready to be passed to a `TruthContext` or logged to the episodic ledger. Evidence quotes are the complete passage and carry the passage's citation atoms.

### Retrieval quality: query instructions and reranking

Asymmetric retrieval models such as `BAAI/bge-base-en-v1.5` expect an
instruction in front of queries but not passages. A cross-encoder reranker then
reads each query and passage together and reorders the vector shortlist:

```python
rag = RagPipeline(
    embed_model="BAAI/bge-base-en-v1.5",
    query_instruction="Represent this sentence for searching relevant passages: ",
    rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
    rerank_candidates=50,
)
result = rag.retrieve("What were total revenues in Q2 2025?", top_k=10)
print(result["results"][0]["rerank_score"])
```

The vector store returns `rerank_candidates` passages, the reranker scores them
in one batched pass, and the best `top_k` are returned with a `rerank_score`.
Pass `apply_reranker=False` to get the native dense ranking. The defaults are
unchanged: `all-MiniLM-L6-v2`, no instruction, no reranker.

Index and query with the same embedding model. Changing `embed_model` changes
the vector dimension, so rebuild the index after switching.

### Filtering and scoping

`where` restricts retrieval to entries whose metadata (or entry fields such as
`source`) match. A list, tuple or set value matches any of its members:

```python
rag.retrieve("revenue", top_k=5, where={"upload_id": ("10q-v1", "10k-v2")})
```

Filtering happens before the shortlist is cut and reranked, so a scoped query is
never starved by matches outside its scope.

### One passage per source

By default several passages from one document can be returned. When each
`source` is one citable unit (a page, a segment) and you want breadth across
sources, pass `one_per_source=True`: only each source's best passage is kept,
and the store is searched deep enough to still fill `top_k`.

```python
rag.retrieve("How did the acquisition close?", top_k=10, one_per_source=True)
```

### TypeSafe passage classification

With the `rag` and `typesafe` extras installed, add an async decision stage
after retrieval:

```python
rag = RagPipeline(decision_client=agent.decisions)
result = await rag.retrieve_with_decisions("How do sessions expire?", top_k=8)

for passage in result["accepted_results"]:
    print(passage["source"], passage["decision"]["answers"])
```

For `ResearcherSubAgent`, enable the same path with
`RAG_DECISION_PROVIDER=typesafe`. FAISS still builds the shortlist. Jev then
scores each query-passage pair for relevance, usable evidence, premise
contradiction, and prompt injection. The complete shortlist remains in
`results` on the direct pipeline API; accepted, conflicting, and excluded
subsets are additional views. The Researcher tool removes excluded passage text
from its model observation while retaining source and decision metadata.

Injection classification reduces exposure but is not a security boundary.
Every retrieved passage must still be handled as untrusted source text.

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

Ingestion does not deduplicate: re-ingesting the same source adds its chunks
again. Remove a document's entries first with `delete`, which takes the same
filter as `where` and keeps every other vector without re-embedding:

```python
rag = RagPipeline()
removed = rag.store.delete({"source": "llm-intro"})
rag.ingest_documents([{"source": "llm-intro", "content": updated_text}])
```

To start over, delete the index files and re-ingest:

```bash
rm ~/.jarviscore/rag/faiss.index
rm ~/.jarviscore/rag/faiss_meta.json
python scripts/ingest_knowledge.py
```

The default store opens on first use, so an application that binds its own
store (for example one index per tenant, `rag.store = FaissVectorStore(...)`)
never opens the default index.

Check index stats at any time:

```python
rag = RagPipeline()
print(rag.stats())
# {"index_path": "...", "meta_path": "...", "vector_count": 247, "metadata_count": 247, "dim": 384}
```

---

## Configuration

```bash title=".env"
# Embedding model (default: all-MiniLM-L6-v2: fast, 384-dim)
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

# Optional asymmetric query instruction and cross-encoder reranking
# RAG_QUERY_INSTRUCTION="Represent this sentence for searching relevant passages: "
# RAG_RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
# RAG_RERANK_CANDIDATES=50

# Optional Jev classification after vector retrieval
# RAG_DECISION_PROVIDER=typesafe
# RAG_TYPESAFE_MAX_CONCURRENT=4
```

| Variable | Default | Description |
|---|---|---|
| `RAG_EMBED_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model name or HuggingFace ID |
| `RAG_EMBED_MODEL_PATH` |: | Path to a local model directory |
| `RAG_INDEX_PATH` | `~/.jarviscore/rag/faiss.index` | FAISS index file location |
| `RAG_META_PATH` | `~/.jarviscore/rag/faiss_meta.json` | Chunk metadata sidecar |
| `RAG_TOP_K` | `5` | Number of chunks returned per query |
| `RAG_CHUNK_SIZE` | `1200` | Max characters per chunk |
| `RAG_CHUNK_OVERLAP` | `200` | Overlap between consecutive chunks |
| `RAG_QUERY_INSTRUCTION` | (empty) | Text prepended to queries only, for asymmetric retrieval models |
| `RAG_RERANK_MODEL` | (none) | Cross-encoder model that reranks the vector shortlist |
| `RAG_RERANK_CANDIDATES` | `50` | Shortlist size the reranker scores |

Constructor arguments `embed_model`, `query_instruction`, `rerank_model` and
`rerank_candidates` override these variables for one pipeline.

---

## Further Reading

- [Internet Search](internet-search.md): Web search providers that ResearcherSubAgent runs alongside RAG
- [AutoAgent Guide](autoagent.md): How ResearcherSubAgent fits into the OODA loop
- [Integrations](integrations.md): Atoms and system bundles that extend what agents can do
