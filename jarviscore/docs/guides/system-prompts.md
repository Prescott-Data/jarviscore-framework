---
icon: material/text-box-edit-outline
---

# System Prompts

The system prompt is the primary control surface for a JarvisCore `AutoAgent`. The Kernel uses it to determine what the agent is, what it knows, what it should produce, and how it should handle edge cases. A well-written system prompt is the difference between an agent that needs constant supervision and one that runs autonomously with high reliability.

---

## How the System Prompt Is Used

When the Kernel starts an OODA loop turn, it assembles a full context bundle:

```
[Profile Block]          ← From agent_profile.yaml (expertise, SOPs, domain facts)
[Base System Prompt]     ← Your AutoAgent.system_prompt class attribute
---
[Task]                   ← The task string from mesh.workflow()
[Prior Step Outputs]     ← From depends_on steps, rendered automatically
[Recent Episodic Turns]  ← From the episodic ledger (last N turns)
[LTM Summary]            ← Compressed long-horizon context (if available)
[Athena Context]         ← Semantic memory from prior sessions (if configured)
```

The base system prompt sits between the profile block and the runtime context. It is the part you control at the class level. The Kernel prepends the profile block — the system prompt should never repeat what the profile block already defines (role, expertise, SOPs).

---

## The Minimum Viable System Prompt

Three things are required in every AutoAgent system prompt:

1. **What the agent is** — role identity in one sentence
2. **What `result` must contain** — exact variable name and structure
3. **What to do when something fails** — error handling instruction

```python
system_prompt = """
You are a financial data analyst specialising in public equity markets.

Your output must be stored in a variable named `result` as a dict:
  {
    "ticker":      str,   # e.g. "AAPL"
    "price":       float, # current price in USD
    "change_pct":  float, # percentage change today
    "analysis":    str    # 2-3 sentences on price action
  }

If the data request fails or the ticker is invalid, set result["error"] to a
descriptive string and leave other keys as None.
"""
```

Missing any of these three creates predictable failure modes: vague identity → wrong sub-agent routing; missing `result` shape → parser errors on output; missing error handling → silent null payloads on failure.

---

## What the Kernel Expects in `result`

The Kernel always reads from a Python variable named `result` in the sandbox. It does not infer output from print statements, return values, or side effects. The system prompt must explicitly instruct the agent to assign its output to `result`.

```python
# ✅ Correct — result is assigned
result = {"summary": "...", "items": [...]}

# ❌ Wrong — the Kernel will not find this
print(json.dumps({"summary": "..."}))

# ❌ Wrong — function return values are not captured
def get_summary():
    return {"summary": "..."}
```

If `result` is not assigned, `step["payload"]` will be `None` and `step["status"]` will still be `"success"` because the sandbox did not raise an exception.

---

## Specifying Tools and APIs

The Kernel generates code that runs in a sandbox. The sandbox has access to Python standard library and any system bundles registered in the Registry. Tell the agent exactly what is available:

```python
system_prompt = """
You are a GitHub activity analyst.

Available tools (via registered system bundle):
  github_list_prs(repo: str, state: str) -> list
  github_get_pr_diff(repo: str, pr_number: int) -> str
  github_post_comment(repo: str, pr_number: int, body: str) -> dict

Data source: github.com API via auth_manager (credentials injected automatically).

Output stored in `result` as:
  {
    "repo":     str,
    "open_prs": int,
    "reviews":  list[dict]   # [{pr_number, title, summary}]
  }

If the GitHub API rate-limits or returns 403, set result["error"] and stop.
"""
```

Named tools referenced in the system prompt are what the `CoderSubAgent` generates calls to. If a tool is not mentioned, the agent may invent an API call that fails in the sandbox.

---

## Multi-Step Goal Prompts

For agents with `goal_oriented = True`, the system prompt shapes the planning phase, not just the execution phase. The planner reads it to understand what the goal decomposition should look like.

```python
system_prompt = """
You are a market research analyst. Your goal is to produce a comprehensive
competitive analysis for a given company.

When given a goal, decompose it into these phases:
  1. Identify the company's direct competitors (3-5)
  2. Gather financial metrics for each (revenue, growth rate, margin)
  3. Identify product differentiators
  4. Synthesise findings into a structured comparison

For each research step, store intermediate findings in named variables:
  competitors_list, financial_data, differentiators

Final output stored in `result` as:
  {
    "target_company": str,
    "competitors": list[dict],
    "recommendation": str
  }

If a research step finds no data, note the gap and continue — do not abort.
"""
```

Explicitly naming the phases and intermediate variables gives the planner a clear decomposition template, which reduces replanning cycles.

---

## Communicator and Notifier Prompts

For agents that format and deliver output rather than gather it, the system prompt focuses on output format and delivery channel:

```python
class SlackReporter(AutoAgent):
    role = "reporter"
    default_kernel_role = "communicator"  # preferred fallback for communication tasks
    system_prompt = """
    You are a Slack notification agent for the engineering team.

    You receive structured data and format it as a Slack message.
    Use Slack Block Kit format where possible.
    Keep messages under 3000 characters.
    Always include a "status" emoji at the start (✅ success, ⚠️ warning, ❌ failure).

    Send via: slack_send_message(channel="#engineering", text=formatted_message)

    Store confirmation in `result`:
      {"channel": str, "sent": bool, "ts": str}
    """
```

Setting `default_kernel_role = "communicator"` tells the Kernel and Planner the agent's preferred specialist role. It does not replace task-aware routing for general work; use it only when the agent's domain is genuinely narrow enough that `communicator` is the right fallback.

---

## Using Agent Profiles for Domain Intelligence

The system prompt is for task-level instructions. Domain intelligence — who the agent is, what it knows, what its standing procedures are — belongs in an `AgentProfile` YAML file:

```yaml title="profiles/researcher.yaml"
role: "Researcher — Data Intelligence Agent"
default_kernel_role: researcher

expertise:
  - Public equity markets and fundamental analysis
  - Macroeconomic indicators and their market impact
  - Academic literature on quantitative finance

sops:
  - Always cross-reference price data from at least two sources
  - Flag any data older than 24 hours as potentially stale
  - Store methodology notes in the episodic ledger for auditability

domain_facts:
  primary_exchange: "NYSE/NASDAQ"
  currency: "USD"
  data_lag_tolerance: "15 minutes for intraday, 1 day for fundamentals"

owns:
  - Market intelligence reports
  - Data quality assessments

escalates_to:
  - "Head of Research"
```

```bash
# Point JarvisCore at your profiles directory
JARVISCORE_PROFILES_DIR=/your-app/profiles/agents
```

The profile block is prepended automatically. The system prompt only needs task-level instructions — no need to repeat the agent's role or expertise.

---

## Common Anti-Patterns

### Vague identity
```python
# ❌ Too vague — the Kernel doesn't know which sub-agent to route to
system_prompt = "You are a helpful AI assistant."

# ✅ Specific identity tells the Kernel exactly what to do
system_prompt = "You are a Python code reviewer. Analyse pull request diffs and identify bugs."
```

### Missing `result` assignment
```python
# ❌ Result not stored — step["payload"] will be None
system_prompt = "Fetch and summarise the top 5 news stories."

# ✅ Explicit output contract
system_prompt = """
Fetch and summarise the top 5 tech news stories.
Store in `result` as a list of {"title": str, "summary": str, "url": str}.
"""
```

### Injecting prior step data manually
```python
# ❌ Never do this — the WorkflowEngine injects prior steps automatically
system_prompt = """
You are an analyst. Access previous step data via context.get('fetch', {}).
"""

# ✅ Just declare depends_on — prior step outputs appear automatically
results = await mesh.workflow("pipeline", [
    {"id": "fetch", "agent": "fetcher", "task": "Fetch data"},
    {"id": "analyse", "agent": "analyst", "task": "Analyse the data", "depends_on": ["fetch"]},
])
```

### Writing the SOP in system_prompt
```python
# ❌ SOPs in system_prompt are reset on every restart and can't be updated without a deploy
system_prompt = """
SOP 1: Always verify the data source
SOP 2: Cross-reference at least two sources
...
"""

# ✅ SOPs belong in the AgentProfile YAML — hot-reloadable, versionable
```

---

## System Prompt Template

A battle-tested template for production `AutoAgent` deployments:

```python
system_prompt = """
You are a [ROLE] specialising in [DOMAIN].

[AVAILABLE TOOLS — list any system bundle methods the agent can call]

[DATA SOURCES — API endpoints, authentication notes]

Your output must be stored in `result` as:
  {
    [FIELD]: [TYPE],  # [DESCRIPTION]
    ...
  }

[EDGE CASE HANDLING — what to do when data is missing, API fails, etc.]

[QUALITY CONSTRAINTS — max length, format requirements, citation rules]
"""
```

Apply this template for every new agent. The more precisely you fill each section, the fewer autonomous repair cycles the Kernel needs.

---

## Further Reading

- [AutoAgent Guide](autoagent.md) — How the Kernel uses the system prompt in the OODA loop
- [Agent Personas](../concepts/agent-personas.md) — Full AgentProfile YAML schema and profile loading
- [Workflow DAGs](workflows.md) — How depends_on replaces manual context injection in system prompts
