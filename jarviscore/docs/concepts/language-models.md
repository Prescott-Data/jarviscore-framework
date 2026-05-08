---
icon: material/chip
---

# Language Models

JarvisCore is built for a world where no single model does everything well. A model that excels at code generation tends to be overkill for classifying a yes/no decision. A model capable of deep multi-step reasoning is too slow and expensive for summarising a conversation. A model that drives a browser needs to see screenshots; a model writing a Slack message does not.

Rather than exposing this complexity to developers, JarvisCore assigns every LLM call to a **role** — a named capability that determines how the model is prompted, what it returns, and which model tier it runs on.

---

## The Four LLM Roles

### Reasoning

The reasoning role handles open-ended thinking: decomposing goals into plans, evaluating options, synthesising research, and generating structured analysis. Prompts are long and the expected output is prose or structured JSON. This is where your most capable model earns its cost.

The `Planner` and `ResearcherSubAgent` use the reasoning role by default.

### Coding

The coding role generates, reviews, and repairs executable code. It is given explicit tool schemas, a working scratchpad, and structured feedback on execution failures. The expected output is always code or a structured tool call — never free-form prose.

`CoderSubAgent` owns this role. It is the only role with no generic fallback tier: if `CODING_MODEL` is unset, it inherits the provider default deployment.

### Computer Use (CUA)

The computer use role drives the browser. On each OODA loop turn, `BrowserSubAgent` takes a screenshot of the active page and includes it alongside the tool output in the prompt. The model must reason about what it sees and produce structured action commands: click, type, scroll, extract.

Two model classes work here. **CUA-native models** (Google `gemini-2.5-computer-use`, OpenAI `gpt-5.4-mini`) output structured action commands directly and are significantly more reliable on complex UIs. **Multimodal models** (vision-capable, not CUA-native) can interpret screenshots through the standard chat interface; they work well on simple, well-structured pages but degrade on dense interactive UIs.

A text-only model assigned to the browser role will run but cannot interpret screenshots. Set `BROWSER_MODEL` explicitly whenever `BROWSER_ENABLED=true`.

### Nano / Fast

The nano role handles classification, short message drafting, and context compression — tasks where low latency and cost matter more than depth. Prompts are short, outputs are small, and the expected result is a verdict or a brief string.

`CommunicatorSubAgent`, `StepEvaluator`, and the auto-summariser run on the nano role.

---

## The Completion Interface

All four roles go through a single client — `UnifiedLLMClient` — which normalises provider differences before the call and after the response.

**Before the call**, the client handles parameter incompatibilities automatically:

- `gpt-5.x` rejects `max_tokens` → substituted with `max_completion_tokens`
- `gpt-5.x` rejects non-default `temperature` → parameter is stripped
- Providers that do not support `response_format: json_object` → parameter is silently omitted

**After the call**, every response — regardless of provider — arrives in the same shape:

```python
{
    "content":          str,    # the model's output, always a string
    "provider":         str,    # "azure" | "claude" | "gemini" | "vllm"
    "model":            str,    # the exact deployment name used
    "tokens":           {"input": int, "output": int, "total": int},
    "cost_usd":         float,
    "duration_seconds": float,
}
```

Structured output (JSON mode) is requested by passing `response_format={"type": "json_object"}` to `llm.generate()`. The client forwards this when the provider supports it. If the returned content is not valid JSON, the Kernel retries the call with an explicit repair prompt before surfacing a failure — you do not handle JSON parse errors in agent code.

**Provider fallback** runs automatically when a provider is unavailable or returns a 5xx. The order is: Azure OpenAI → Claude → vLLM → Gemini. Rate limit responses (HTTP 429) trigger exponential backoff before the fallback chain is tried.

---

## Embedding

Embedding calls — used by `UnifiedMemory` for semantic search and RAG retrieval — run outside the four roles above. They are handled by a dedicated embedding client and are not routed through `UnifiedLLMClient`. Configure the embedding model separately if you are using Athena MemOS or a custom retrieval layer.

---

## What Comes Next

Each of the four roles maps to a **capability tier** — a named slot in your environment configuration that you point at a specific deployment. That mapping, the fallback chain between tiers, and how to override complexity per task are covered in the next section.

**[Model Routing →](model-routing.md)**
