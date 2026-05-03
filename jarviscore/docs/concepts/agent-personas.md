---
icon: material/account-circle
---

# Agent Personas

Every JarvisCore agent has a **persona** composed of two complementary layers: class-level attributes that define static capabilities, and YAML profile files that inject structured role intelligence into the system prompt at runtime.

Understanding personas is important because it is the mechanism through which the Kernel receives grounded domain knowledge. Without a well-defined persona, an agent reasons from general LLM priors. With a complete persona, the agent reasons from a specific, authoritative operational context.

> [!NOTE]
> **Coming from Anthropic's `SKILLS.md`?** JarvisCore's persona system is the equivalent — but structured, typed, and automatically wired into your agent's system prompt and peer discovery. [See the comparison below.](#skillsmd-and-the-personas-equivalent)

---

## Class-Level Persona

All agents, whether `AutoAgent` or `CustomAgent`, define their persona through class attributes.

```python title="agents/researcher.py"
from jarviscore import AutoAgent

class ResearcherAgent(AutoAgent):
    name = "Researcher"
    role = "researcher"
    description = "Conducts systematic research and synthesises findings into structured reports."
    capabilities = ["research", "synthesis", "web-search"]
    system_prompt = """
    You are a rigorous research analyst. You prioritise primary sources,
    cross-reference findings across multiple inputs, and structure outputs
    as actionable intelligence rather than raw summaries.
    """
```

| Attribute | Type | Purpose |
|---|---|---|
| `name` | `str` | Human-readable display name |
| `role` | `str` | Role slug used for peer discovery and profile loading |
| `description` | `str` | One-sentence description of the agent's purpose |
| `capabilities` | `list[str]` | Tags used by `PeerClient.discover()` for capability-based routing |
| `system_prompt` | `str` | Base system prompt injected into every LLM call |
| `default_kernel_role` | `str` | Bypasses the Kernel's role classifier; one of `"researcher"`, `"coder"`, `"communicator"` |

Setting `default_kernel_role` is a performance optimisation. The Kernel normally classifies each task at runtime to determine which reasoning mode to use. If you know the agent's role is always the same, set this attribute to eliminate the classification call.

---

## Agent Profiles

An agent profile is a YAML file that adds structured, domain-specific intelligence to the agent's persona. The Kernel prepends the rendered profile block to the system prompt before every task execution.

Profiles are loaded by `AgentProfile.load(role_name)`, which is called automatically by `AutoAgent.setup()`. The framework looks for the profile YAML at:

1. `{JARVISCORE_PROFILES_DIR}/{role_name}.yaml` — your application's profile directory (set this in your `.env`).
2. `jarviscore/profiles/agents/{role_name}.yaml` — bundled fallback profiles (example only).

Always set `JARVISCORE_PROFILES_DIR` in your application. The bundled profiles are provided as a reference template, not as production profiles.

### Profile YAML Schema

```yaml title="profiles/agents/researcher.yaml"
role: "Researcher — Market Intelligence Agent"

expertise:
  - Systematic primary and secondary source research
  - Competitive landscape analysis and benchmarking
  - Data synthesis into structured intelligence reports
  - Citation tracking and source credibility assessment

domain_facts:
  company: "Prescott Data"
  primary_market: "Enterprise SaaS analytics"
  report_format: "Executive summary followed by detailed findings with citations"

owns:
  - Research reports in the standardised company template
  - Source inventories with credibility ratings
  - Competitive intelligence dossiers

sops:
  - Always cross-reference findings across at least three independent sources before asserting a claim.
  - Flag conflicting data points explicitly rather than resolving them silently.
  - Append a confidence score (0.0 to 1.0) to every key finding.
  - Do not include information that cannot be traced to a verifiable source.

escalates_to:
  - "Head of Research"
  - "CTO"

default_kernel_role: "researcher"
```

### Schema Fields

| Field | Type | Description |
|---|---|---|
| `role` | `str` | Full role title injected as the identity header in the system prompt |
| `expertise` | `list[str]` | Domain areas in which the agent is authoritative |
| `domain_facts` | `dict[str, str]` | Static organisational context (company name, product lines, conventions) |
| `owns` | `list[str]` | Artifacts this agent is accountable for producing |
| `sops` | `list[str]` | Standing operating procedures followed autonomously, without being asked |
| `escalates_to` | `list[str]` | People or roles to contact via HITL when the agent is blocked |
| `default_kernel_role` | `str` | Kernel role override; one of `researcher`, `coder`, `communicator` |

### How the Profile Block Is Injected

`AgentProfile.to_prompt_block()` renders the YAML fields into a structured markdown section:

```
## ROLE INTELLIGENCE: RESEARCHER — MARKET INTELLIGENCE AGENT

### Expertise
- Systematic primary and secondary source research
- Competitive landscape analysis and benchmarking
...

### Context
- **company**: Prescott Data
- **primary_market**: Enterprise SaaS analytics
...

### What You Own
- Research reports in the standardised company template
...

### Standing Operating Procedures (follow autonomously — do not wait to be asked)
1. Always cross-reference findings across at least three independent sources before asserting a claim.
2. Flag conflicting data points explicitly rather than resolving them silently.
...

### Escalation
When blocked for more than 48 hours or facing a decision outside your authority,
escalate to: **Head of Research, CTO** via HITL.
```

This block is prepended to the agent's `system_prompt` before every LLM call. The LLM receives both the role intelligence and the base system prompt as a unified system context.

---

## Graceful Degradation

If `AgentProfile.load()` cannot find the YAML file (for example, `JARVISCORE_PROFILES_DIR` is not set, or the file does not exist for a given role), it returns `None` and logs a debug message. The agent continues to function using only its class-level `system_prompt`.

If `PyYAML` is not installed, profile loading is disabled entirely and a warning is logged. Install it with:

```bash
pip install pyyaml
```

PyYAML is a light dependency with no transitive requirements; there is no practical reason to omit it from a production environment.

---

## Configuring the Profile Directory

```bash title=".env"
JARVISCORE_PROFILES_DIR=/path/to/your/app/profiles/agents
```

The path should point to a directory where each file is named `{role_slug}.yaml`, matching the `role` attribute on the corresponding agent class.

```
your-app/
  profiles/
    agents/
      researcher.yaml
      analyst.yaml
      reporter.yaml
  agents/
    researcher.py
    analyst.py
    reporter.py
```

This separation keeps profile intelligence in version-controlled YAML files that can be updated without modifying Python source code.

---

## Using Personas in Multi-Agent Workflows

When agents communicate via the P2P mesh, persona attributes drive discovery and routing. The `role` attribute on an agent class is the primary key for peer lookup:

```python
# In a CustomAgent's run() method:
analyst = self.peers.get_peer(role="analyst")
if analyst:
    await self.peers.notify("analyst", {"event": "research_complete", "data": summary})
```

The `capabilities` list supports more flexible discovery when you want to find any agent that can perform a particular function, regardless of its specific role:

```python
# Find any agent with the "data-analysis" capability
analysts = self.peers.discover(capability="data-analysis", strategy="round_robin")
```

The combination of `role` and `capabilities` gives you both exact-match and capability-based routing without requiring a centralised registry.

---

## SKILLS.md and the Personas Equivalent

Anthropic popularised `SKILLS.md` — a markdown file that describes what an agent can do, what tools it has access to, and how it should behave. It's a simple, portable convention for grounding an LLM in a specific context.

JarvisCore's persona system covers the same ground, with more structure:

| `SKILLS.md` (Anthropic pattern) | JarvisCore Agent Persona |
|---|---|
| Freeform markdown | Typed YAML schema with enforced fields |
| Written once, manually maintained | Per-role YAML, loaded automatically by the framework |
| No enforcement — LLM reads it as instructions | `sops:` rendered as numbered SOPs; `escalates_to:` wired into HITL |
| Separate from code | `capabilities:` drives live P2P peer discovery |
| Tool descriptions are free text | System Bundles provide typed, versioned atoms (see [System Bundles](system-bundles.md)) |

The key difference is that a `SKILLS.md` describes what an agent *might* do. A JarvisCore persona shapes what the agent *is* — and the `capabilities` list directly controls how other agents discover and route to it at runtime.

**The migration pattern** for teams coming from `SKILLS.md` is straightforward:

```yaml title="profiles/agents/analyst.yaml"
# Your SKILLS.md content maps to:
role: "Analyst — Financial Intelligence"       # was: # Role: Financial Analyst

expertise:                                      # was: ## Skills\n- Financial modelling
  - Financial modelling and DCF analysis
  - Earnings report parsing

domain_facts:                                   # was: ## Context\nCompany: Acme Corp
  company: "Acme Corp"
  reporting_currency: "USD"

sops:                                           # was: ## Instructions\n- Always...
  - Always cite the source filing for every data point.
  - Flag data older than 90 days as potentially stale.

owns:                                           # was: ## Outputs\n- Earnings summaries
  - Earnings analysis reports
  - DCF model outputs
```
