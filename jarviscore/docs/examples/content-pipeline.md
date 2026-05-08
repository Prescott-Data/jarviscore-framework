---
icon: material/text-box-edit
---

# Content Production Pipeline

[:fontawesome-brands-github: View full source](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/content_pipeline.py){ .md-button }

| | |
|---|---|
| **Profile** | `CustomAgent` |
| **Infra required** | Redis (auto-detected from `REDIS_URL`) |
| **Workflow** | `research → write → seo → publish` |
| **Run** | `python examples/content_pipeline.py` |

---

## What it does

Four `CustomAgent` specialists run a content production pipeline. Unlike the Financial Pipeline (which uses `AutoAgent` with LLM code generation), these agents implement `execute_task()` directly in pure Python — deterministic, testable, no LLM required.

Cross-step data flows via `RedisMemoryAccessor`: each subsequent agent reads the previous step's output from Redis rather than receiving it as a function argument.

```
ResearchAgent  →  WriterAgent  →  SEOAgent  →  PublisherAgent
  research          write           seo           publish
  (gather notes)  (draft article)  (metadata)    (assemble + save)
                                                    ↓ mailbox
                                              ResearcherAgent ← "published" event
```

---

## Key pattern: mesh setup (no mode needed)

```python
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent

mesh = Mesh(config={"redis_url": REDIS_URL})  # (1)!
mesh.add(ResearchAgent)
mesh.add(WriterAgent)
mesh.add(SEOAgent)
mesh.add(PublisherAgent)
await mesh.start()

# Verify what was detected
print(mesh.has_capability("redis"))   # True when Redis is up
print(mesh.has_capability("blob"))    # True — LocalBlobStorage always available
```

1. No `mode=` argument. The Mesh detects Redis from `REDIS_URL` (or the config dict) at `start()` time and activates the workflow engine with Redis persistence automatically.

---

## Key pattern: cross-step Redis memory

```python
class WriterAgent(CustomAgent):

    async def execute_task(self, task: dict) -> dict:
        # Read the output from the previous "research" step via Redis.
        # No function argument needed.
        accessor = RedisMemoryAccessor(self._redis_store, WORKFLOW_ID)  # (1)!
        raw = accessor.get("research")                                   # (2)!
        research = raw.get("output", raw) if isinstance(raw, dict) else {}

        themes = research.get("key_themes", [])
        # ... build draft from themes ...
```

1. `RedisMemoryAccessor` wraps the `RedisMemoryStore` with workflow-scoped key lookups.
2. `accessor.get("research")` reads `step_output:{workflow_id}:research` from Redis — written by `WorkflowEngine` immediately after the research step completes.

---

## Key pattern: LTM persistence across runs

```python
class PublisherAgent(CustomAgent):

    async def execute_task(self, task: dict) -> dict:
        # ... publish article ...

        # Save style notes to LTM for the next run.
        if self.memory.ltm:
            style_summary = (
                f"Article on '{TOPIC}' published {time.strftime('%Y-%m-%d')}. "
                f"Style: informative, forward-looking, developer-audience."
            )
            await self.memory.ltm.save_summary(style_summary)  # (1)!
```

1. On the next run, `WriterAgent.setup()` loads this via `self.memory.ltm.load_summary()` and injects it into the draft — the pipeline gets progressively smarter across runs without any code changes.

---

## Key pattern: pure Python `execute_task`

`CustomAgent` gives you full control over step logic. No LLM needed:

```python
class SEOAgent(CustomAgent):
    role = "seo"
    capabilities = ["seo", "content_optimization"]

    async def execute_task(self, task: dict) -> dict:
        accessor = RedisMemoryAccessor(self._redis_store, WORKFLOW_ID)
        draft_output = accessor.get("write").get("output", {})
        draft = draft_output.get("draft", "")
        word_count = draft_output.get("word_count", 0)

        target_keywords = ["AI agents", "autonomous AI", "multi-agent systems"]
        keyword_density = {
            kw: round(draft.lower().count(kw.lower()) / max(word_count, 1) * 100, 2)
            for kw in target_keywords
        }
        return {"status": "success", "output": {"seo_score": 85, "keyword_density": keyword_density}}
```

---

## Success criteria

- [ ] All 4 steps complete: `research → write → seo → publish`
- [ ] Draft at `blob_storage/content/drafts/`
- [ ] SEO metadata at `blob_storage/content/seo/content-pipeline-metadata.json`
- [ ] Final article at `blob_storage/content/published/`
- [ ] LTM key set: `redis-cli get ltm:content-pipeline`
- [ ] Researcher receives mailbox notification from Publisher
