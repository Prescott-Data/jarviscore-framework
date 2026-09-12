---
icon: material/text-box-edit-outline
title: "Write Effective System Prompts for AutoAgent"
description: "Define an AutoAgent's role, output contract, verification behavior, and error handling through clear, testable JarvisCore system prompts."
---

# System Prompts

The system prompt is the primary reasoning instruction for a JarvisCore
`AutoAgent`. It explains ownership, method, evidence standards, deliverable
semantics, and how to represent uncertainty. Runtime contracts separately
enforce authority, execution shape, output validity, and durable completion.
A prompt is not a substitute for those boundaries.

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

The base system prompt sits between the profile block and the runtime context. It is the part you control at the class level. The Kernel prepends the profile block: the system prompt should never repeat what the profile block already defines (role, expertise, SOPs).

## Compose Prompts from Named Sections

Avoid one long anonymous string for a production agent. Named sections make
ownership and omissions visible in review, allow focused assertions in tests,
and keep the static prefix byte-stable for provider prompt caching. JarvisCore
receives the compiled string; section composition is an application pattern,
not another agent profile.

A useful section order is:

1. **Role and ownership**: what this agent owns and what belongs to peers.
2. **Method**: how it investigates, reasons, and uses evidence.
3. **Authority**: how to interpret available tools and effect boundaries.
4. **Deliverable**: the meaning and shape of a complete result.
5. **Uncertainty**: how to report missing evidence, blocked work, and partial results.

```python title="prompts/repository_reviewer.py"
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptSection:
  name: str
  body: str


def compile_prompt(sections: tuple[PromptSection, ...]) -> str:
  names = [section.name for section in sections]
  if len(names) != len(set(names)):
    raise ValueError("prompt section names must be unique")
  return "\n\n".join(section.body.strip() for section in sections)


REVIEW_SECTIONS = (
  PromptSection(
    "ownership",
    """## Ownership
You own evidence-backed review findings. You do not merge code or invent
requirements that are absent from the repository.""",
  ),
  PromptSection(
    "method",
    """## Method
Inspect the changed behavior, its callers, and the narrowest relevant tests.
Prefer reproducible defects over stylistic preference.""",
  ),
  PromptSection(
    "deliverable",
    """## Deliverable
Return findings with severity, file location, evidence, impact, and a concrete
repair. Return an empty findings list when no defect is supported.""",
  ),
  PromptSection(
    "uncertainty",
    """## Uncertainty
Name missing evidence explicitly. Do not present an unverified suspicion as a
finding.""",
  ),
)

REPOSITORY_REVIEWER_PROMPT = compile_prompt(REVIEW_SECTIONS)
```

Use the compiled value normally:

```python
from jarviscore import AutoAgent


class RepositoryReviewer(AutoAgent):
  role = "repository_reviewer"
  capabilities = ["code_review"]
  system_prompt = REPOSITORY_REVIEWER_PROMPT
```

Keep per-request data out of the class-level prompt. Put repository state,
account data, user input, and other changing material in the task or context.
This prevents state leakage between runs and preserves a stable cacheable
prefix. Test section names, order, required headings, and critical boundary
language without snapshotting every word.

---

## The Minimum Viable System Prompt

Four questions should be answered by every production AutoAgent prompt:

1. **What does this agent own, and what does it not own?**
2. **How should it reason and what evidence is acceptable?**
3. **What makes the deliverable complete?**
4. **How should it represent missing evidence or blocked work?**

```python
system_prompt = """
You are a financial data analyst specialising in public equity markets.

For coder-sandbox work, store the output in a variable named `result` as a dict:
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

The class-level `role`, `capabilities`, `capability_descriptions`, and
`capability_contracts` carry routing and authority. The prompt supplies the
domain judgment those declarations cannot express.

---

## Choose the Output Boundary

The required completion shape depends on how the task executes:

| Execution path | Completion boundary |
|---|---|
| Normal Kernel OODA | The framework appends its `DONE` plus `RESULT` protocol. `DONE` is complete human-facing prose; `RESULT` is data for downstream work. |
| Coder sandbox | Generated Python must assign its output to `result`. Print output and function return values are not the sandbox result. |
| `single_response` | One direct completion returns visible prose; no Python `result` variable or Kernel completion protocol is involved. |
| `single_artifact` | One bounded Kernel turn may finish with a raw JSON object. Validate domain artifacts before returning them. |

For the coder path:

```python
# ✅ Correct: result is assigned
result = {"summary": "...", "items": [...]}

# ❌ Wrong: the Kernel will not find this
print(json.dumps({"summary": "..."}))

# ❌ Wrong: function return values are not captured
def get_summary():
    return {"summary": "..."}
```

Do not repeat the raw `DONE`/`RESULT` parser syntax in every application prompt;
the execution harness already supplies it. Describe what the answer and data
mean. A shared application subclass may reinforce the `RESULT` schema when it
validates a domain work product. See [Contracts and Boundaries](../concepts/contracts.md).

---

## Specifying Tools and APIs

The Kernel appends live tool descriptions from the Registry. Use the system
prompt to explain when and why the agent should use its authorized tools; do not
copy provider credentials or invent signatures that are not registered.

```python
system_prompt = """
You are a GitHub activity analyst.

Use the available Nexus-backed GitHub tools to inspect pull requests and diffs.
Treat a proposed review comment separately from a posted comment. Never request,
print, or store provider credentials.

Output stored in `result` as:
  {
    "repo":     str,
    "open_prs": int,
    "reviews":  list[dict]   # [{pr_number, title, summary}]
  }

If the provider cannot complete an operation, preserve its exact evidence and
report the work as blocked or incomplete. Do not infer the cause from an HTTP
status code alone.
"""
```

Tool schemas come from the live registry. Keep the prompt focused on domain
behavior and let registered schemas define callable names and arguments.

---

## Multi-Step Goal Prompts

For `agent.execute_goal()` and complex tasks on an agent with
`goal_oriented = True`, the system prompt shapes that agent's planning phase as
well as execution. This is separate from `Mesh.execute_goal()`, whose temporary
planner builds a capability-addressed DAG from the human objective and the Mesh
capability catalog.

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

If a research step finds no data, note the gap and continue. Do not abort.
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

The system prompt is for task-level instructions. Domain intelligence (who the agent is, what it knows, what its standing procedures are) belongs in an `AgentProfile` YAML file:

```yaml title="profiles/researcher.yaml"
role: "Researcher, Data Intelligence Agent"
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

The profile block is prepended automatically. The system prompt only needs task-level instructions: no need to repeat the agent's role or expertise.

---

## Common Anti-Patterns

### Vague identity
```python
# ❌ Too vague: the Kernel doesn't know which sub-agent to route to
system_prompt = "You are a helpful AI assistant."

# ✅ Specific identity tells the Kernel exactly what to do
system_prompt = "You are a Python code reviewer. Analyse pull request diffs and identify bugs."
```

### Missing `result` assignment
```python
# ❌ Result not stored: step["payload"] will be None
system_prompt = "Fetch and summarise the top 5 news stories."

# ✅ Explicit output contract
system_prompt = """
Fetch and summarise the top 5 tech news stories.
Store in `result` as a list of {"title": str, "summary": str, "url": str}.
"""
```

### Injecting prior step data manually
```python
# ❌ Never do this: the WorkflowEngine injects prior steps automatically
system_prompt = """
You are an analyst. Access previous step data via context.get('fetch', {}).
"""

# ✅ Just declare depends_on: prior step outputs appear automatically
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

# ✅ SOPs belong in the AgentProfile YAML: hot-reloadable, versionable
```

---

## System Prompt Template

A battle-tested template for production `AutoAgent` deployments:

```python
system_prompt = """
You are a [ROLE] specialising in [DOMAIN].

[AVAILABLE TOOLS: list any system bundle methods the agent can call]

[DATA SOURCES: API endpoints, authentication notes]

Your output must be stored in `result` as:
  {
    [FIELD]: [TYPE],  # [DESCRIPTION]
    ...
  }

[EDGE CASE HANDLING: what to do when data is missing, API fails, etc.]

[QUALITY CONSTRAINTS: max length, format requirements, citation rules]
"""
```

Use these as named sections rather than one anonymous block. Precise sections
make omissions testable; runtime contracts still enforce the boundaries that
downstream code must trust.

---

## Further Reading

- [AutoAgent Guide](autoagent.md): How the Kernel uses the system prompt in the OODA loop
- [Contracts and Boundaries](../concepts/contracts.md): What prompts instruct versus what the runtime enforces
- [Agent Personas](../concepts/agent-personas.md): Full AgentProfile YAML schema and profile loading
- [Workflow DAGs](workflows.md): How depends_on replaces manual context injection in system prompts
