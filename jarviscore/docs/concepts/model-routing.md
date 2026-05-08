---
icon: material/transit-connection-variant
---

# Model Routing

JarvisCore routes every LLM call to a capability tier rather than a specific model. A tier is an abstract label (`coding`, `browser`, `heavy`, `standard`, or `nano`) that maps to a model deployment name you configure in your environment. The framework never hardcodes model names; you choose the models that match your provider, budget, and quality requirements.

This separation means you can swap providers, upgrade models, or tune cost without touching agent code.

---

## The Five Capability Tiers

| Tier | Env var | What it is for |
|---|---|---|
| **Coding** | `CODING_MODEL` | Code generation, code review, execution debugging |
| **Browser** | `BROWSER_MODEL` | Browser automation, UI interaction, screenshot reasoning |
| **Heavy** | `TASK_MODEL_HEAVY` | Goal decomposition, multi-step planning, deep reasoning |
| **Standard** | `TASK_MODEL_STANDARD` | Web research, general analysis |
| **Nano** | `TASK_MODEL_NANO` | Step evaluation, context summarisation, short message drafting |

When a tier-specific variable is not set, the framework falls back through the following chain until it finds a configured value:

```
BROWSER_MODEL       -> TASK_MODEL_STANDARD -> TASK_MODEL -> default deployment
TASK_MODEL_NANO     -> TASK_MODEL_STANDARD -> TASK_MODEL -> default deployment
TASK_MODEL_STANDARD -> TASK_MODEL          -> default deployment
TASK_MODEL_HEAVY    -> TASK_MODEL_STANDARD -> TASK_MODEL -> default deployment
CODING_MODEL        -> default deployment (no tier-specific fallback)
```

---

## Configuration

Set tier variables in your `.env` file using your provider's deployment identifiers.

=== "Azure OpenAI"

    ```bash
    CODING_MODEL=my-codex-deployment
    BROWSER_MODEL=my-cua-deployment
    TASK_MODEL_HEAVY=my-chat-deployment
    TASK_MODEL_STANDARD=my-chat-deployment
    TASK_MODEL_NANO=my-nano-deployment
    ```

=== "OpenAI"

    ```bash
    CODING_MODEL=gpt-4o
    BROWSER_MODEL=gpt-5.4-mini
    TASK_MODEL_HEAVY=o3
    TASK_MODEL_STANDARD=gpt-4o
    TASK_MODEL_NANO=gpt-4o-mini
    ```

=== "Anthropic"

    ```bash
    CODING_MODEL=claude-sonnet-4
    BROWSER_MODEL=claude-opus-4
    TASK_MODEL_HEAVY=claude-opus-4
    TASK_MODEL_STANDARD=claude-sonnet-4
    TASK_MODEL_NANO=claude-haiku-4
    ```

=== "Gemini"

    ```bash
    GEMINI_API_KEY=...
    BROWSER_MODEL=gemini-2.5-computer-use
    TASK_MODEL_HEAVY=gemini-2.5-pro
    TASK_MODEL_STANDARD=gemini-2.5-flash
    TASK_MODEL_NANO=gemini-2.5-flash
    ```

The values are passed verbatim to the provider client as the deployment or model identifier. JarvisCore does not validate them.

---

## How Tiers Are Resolved

Tier resolution runs automatically on every agent dispatch. The chain is:

1. `Kernel._classify_task()` determines the sub-agent role for the current task: `coder`, `researcher`, `communicator`, or `browser`.
2. `ExecutionLease.for_role(role)` returns a lease for that role. Every lease carries a `model_tier` and an optional `complexity` hint.
3. `Kernel._get_model_for_tier(tier, complexity)` resolves the deployment name from your environment configuration.
4. The resolved name is passed as `model=` into the sub-agent's LLM call.

The built-in sub-agents resolve to the following tiers by default:

| Sub-agent role | Tier | Why |
|---|---|---|
| `coder` | coding | Code generation requires a specialised model |
| `researcher` | task / standard | Long-horizon reasoning and synthesis |
| `communicator` | task / nano | Short message drafting; fast tier is sufficient |
| `browser` | browser | Requires a CUA or multimodal model; see below |

### The Browser Tier

Browser automation is the only tier with a hard model requirement: the model must be capable of processing screenshots. The `BrowserSubAgent` takes a screenshot of the page on each OODA loop turn and includes it in the prompt alongside the tool output. A text-only model cannot interpret this and will produce unreliable tool calls.

There are two classes of model that work well:

**Computer Use Agent (CUA) models** are purpose-built for UI automation. They receive a screenshot and output structured action commands (click, type, scroll) rather than free-form text. They are significantly more reliable on dense, interactive pages.

| Provider | CUA model | Notes |
|---|---|---|
| Google | `gemini-2.5-computer-use` | Native CUA built on Gemini 2.5 Pro; released October 2025 |
| OpenAI | `gpt-5.4-mini` | Native computer-use capability; released March 2026 |

**Multimodal models** (vision-capable but not CUA-native) can interpret screenshots and generate reasonable tool calls via the OODA loop, but they are less reliable on complex UIs than a dedicated CUA model.

| Provider | Multimodal model | Notes |
|---|---|---|
| Google | `gemini-2.5-flash` | Vision-capable; good for simple, well-structured pages |
| OpenAI | `gpt-4o` | Vision-capable; adequate for straightforward automation |
| Anthropic | `claude-opus-4` | Vision-capable; use when running an Anthropic-primary stack |

If `BROWSER_MODEL` is not set, the framework falls back to `TASK_MODEL_STANDARD` and then `TASK_MODEL`. If those happen to be text-only models, the browser sub-agent will still run but screenshot interpretation will fail silently. Set `BROWSER_MODEL` explicitly whenever you use `BROWSER_ENABLED=true`.

Two framework components also make LLM calls outside the sub-agent loop:

| Component | Tier used | Why |
|---|---|---|
| `Planner` | heavy | Decomposes a goal into an ordered step plan |
| `StepEvaluator` | nano | A four-choice verdict (pass / partial / fail / hitl), classification not reasoning |
| Auto-summariser | nano | Compresses conversation history when the context window grows large |

---

## Overriding Complexity Per Task

The `complexity` hint in a workflow step overrides the role-level default for that dispatch. Explicit overrides always take precedence.

```python title="Per-step complexity override"
results = await mesh.workflow("report-001", [
    {
        "agent": "analyst",
        "task": "Is the word 'quarterly' in this text?",
        "complexity": "nano",    # simple lookup — use the fast tier
    },
    {
        "agent": "analyst",
        "task": "Model the 5-year cashflow impact of our pricing change across all segments.",
        "complexity": "heavy",   # deep reasoning — use the most capable tier
    },
])
```

Valid values are `"nano"`, `"standard"`, and `"heavy"`. Any other value is ignored and the role-level default applies.

When `complexity` is not provided, the framework reads the role's built-in complexity hint from the lease profile. This means `communicator` tasks automatically resolve to `TASK_MODEL_NANO` and `researcher` tasks automatically resolve to `TASK_MODEL_STANDARD`, without any action from the developer.

---

## Provider Compatibility

The LLM client handles provider-specific parameter differences automatically.

| Behaviour | How it is handled |
|---|---|
| GPT-5.x rejects `max_tokens` | Automatically substituted with `max_completion_tokens` for `gpt-5.*` deployments |
| GPT-5.x rejects non-default `temperature` | Temperature parameter is stripped for `gpt-5.*` deployments |
| JSON mode (`response_format`) | Forwarded to the provider API when specified; silently omitted on providers that do not support it |
| Azure content filter false positives | Two-pass retry: raw prompt first; sanitised preamble on filter hit |
| Rate limiting (HTTP 429) | Exponential backoff with configurable retries before falling over to the next provider |
| Multi-provider fallback order | Azure → Claude → vLLM → Gemini |

Provider setup is automatic. `UnifiedLLMClient` probes each provider at startup using the keys present in your environment and logs which are available:

```
✓ Azure OpenAI provider available (primary): https://...
✓ Claude provider available (fallback)
LLM Client initialized with providers: ['azure', 'claude']
```

---

## Accessing Tier Models in Custom Code

If you are building a `CustomAgent` or writing a custom planning layer, you can access the resolved model names from the LLM client directly.

```python
from jarviscore.execution.llm import UnifiedLLMClient

llm = UnifiedLLMClient()

# Resolves TASK_MODEL_NANO → TASK_MODEL_STANDARD → default deployment
fast_model = llm.nano_model

# Resolves TASK_MODEL_HEAVY → TASK_MODEL_STANDARD → default deployment
reasoning_model = llm.planner_model
```

Both properties return `None` if no relevant tier variable is configured, in which case the client uses the provider default deployment. Pass the resolved name into any `generate()` call:

```python
response = await llm.generate(
    messages=[{"role": "user", "content": prompt}],
    model=llm.nano_model,
    response_format={"type": "json_object"},
)
```

---

## Adding a Provider

To add a model from a provider not built into `UnifiedLLMClient`:

1. Add an entry to the `LLMProvider` enum.
2. Implement a `_call_<provider>()` method. It receives `messages`, `temperature`, `max_tokens`, and `**kwargs` (which contains `model=` and optionally `response_format=`). It must return the standard response dict:

    ```python
    {
        "content":          str,
        "provider":         str,
        "tokens":           {"input": int, "output": int, "total": int},
        "cost_usd":         float,
        "model":            str,
        "duration_seconds": float,
    }
    ```

3. Register the provider in `_setup_providers()` and append to `self.provider_order`.

The tier system works with any provider that implements this interface. Complexity hints, per-step overrides, and role-level defaults all resolve to a model name string before reaching `_call_<provider>()`.

---

## Further Reading

- [Language Models](./language-models.md) — LLM roles, the completion interface, and CUA vs multimodal for browser automation
- [Architecture Overview](./architecture.md) — how the Kernel, sub-agents, and ExecutionLease fit together
- [AutoAgent Guide](../guides/autoagent.md) — `complexity` overrides and execution budgets
- [Configuration Reference](../reference/configuration.md) — all environment variables including LLM tier keys
- [Observability](../guides/observability.md) — tracing which model and provider handled each LLM call
