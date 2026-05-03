---
icon: material/swap-horizontal
---

# Migration Guide

This guide covers migrating an existing multi-agent system to JarvisCore from **CrewAI** or **LangGraph**. Each section maps the source framework's concepts to their JarvisCore equivalents and provides a before/after code translation.

> [!IMPORTANT]
> This guide reflects CrewAI ≥ 0.28 and LangGraph ≥ 0.1. If you are on an earlier version, some API names may differ. Verify against your installed version's docs before migrating.

---

## Migrating from CrewAI

### Concept Mapping

| CrewAI | JarvisCore | Notes |
|---|---|---|
| `Agent` | `AutoAgent` | For autonomous reasoning agents |
| `Agent` (deterministic) | `CustomAgent` | For scripted, structured execution |
| `Task` | Workflow step dict `{"agent": ..., "task": ...}` | Steps are plain dicts, not objects |
| `Crew` | `Mesh` | The runtime host for all agents |
| `Process.sequential` | `depends_on` in each step | Dependency declared per step, not per crew |
| `Process.hierarchical` | `AutoAgent` as orchestrator with peer calls | No manager agent primitive; orchestration is explicit |
| `Tool` | Atom function in a `SystemBundle` | Atoms are plain functions registered via `Registry` |
| `LLM(model=...)` | `TASK_MODEL_STANDARD=...` in `.env` | LLM config is environment-driven, not per-agent |
| `Agent(memory=True)` | `UnifiedMemory` with `redis_store` | Four-tier memory, always on if Redis is configured |
| `Agent(verbose=True)` | Built-in OODA tracing via `TraceManager` | All reasoning is traced to Redis + JSONL by default |
| `Agent(max_iter=...)` | `KERNEL_MAX_TURNS=...` in `.env` | Environment variable, not per-agent |
| `Crew(full_output=True)` | `results = await mesh.workflow(...)` | Returns list of step result dicts |

---

### Code Translation: Simple Sequential Crew

**CrewAI:**
```python
from crewai import Agent, Task, Crew, Process

researcher = Agent(
    role="Researcher",
    goal="Find relevant information",
    backstory="You are an expert researcher.",
    verbose=True,
)

writer = Agent(
    role="Writer",
    goal="Write a compelling summary",
    backstory="You are an expert writer.",
    verbose=True,
)

research_task = Task(
    description="Research the state of AI hardware in 2026",
    agent=researcher,
    expected_output="A structured list of findings",
)

write_task = Task(
    description="Write a 3-paragraph summary of the research findings",
    agent=writer,
    context=[research_task],  # depends on research_task output
    expected_output="A 3-paragraph summary",
)

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    process=Process.sequential,
)

result = crew.kickoff()
```

**JarvisCore:**
```python
import asyncio
from jarviscore import AutoAgent, Mesh

class ResearcherAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "web-search"]
    system_prompt = """
    You are an expert researcher.
    Research the given topic thoroughly using web search.
    Store your findings in `result` as a dict with keys:
      findings (list of strings), sources (list of URLs).
    """

class WriterAgent(AutoAgent):
    role = "writer"
    capabilities = ["writing", "summarisation"]
    system_prompt = """
    You are an expert writer.
    Produce a 3-paragraph summary of the provided research findings.
    Store the summary in `result` as {"summary": str}.
    """

async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    mesh.add(WriterAgent)
    await mesh.start()

    results = await mesh.workflow("ai-hardware-report", [
        {"id": "research", "agent": "researcher",
         "task": "Research the state of AI hardware in 2026"},
        {"id": "write", "agent": "writer",
         "task": "Write a 3-paragraph summary of the research findings",
         "depends_on": ["research"]},  # prior step output injected automatically
    ])

    print(results[-1]["payload"]["summary"])
    await mesh.stop()

asyncio.run(main())
```

**Key differences:**
- `Task(context=[...])` → `"depends_on": [...]` in the step dict. Prior outputs are injected automatically — no manual context passing needed.
- `Agent(role=..., goal=..., backstory=...)` → one `system_prompt` string that covers all three. Be explicit about `result` shape.
- `Crew(process=Process.sequential)` → implicit via `depends_on`. Steps without dependencies run in parallel automatically.

---

### Code Translation: Tools

**CrewAI:**
```python
from crewai import Agent
from crewai_tools import SerperDevTool, ScrapeWebsiteTool

researcher = Agent(
    role="Researcher",
    goal="Find information",
    backstory="Expert researcher",
    tools=[SerperDevTool(), ScrapeWebsiteTool()],
)
```

**JarvisCore:**

Internet search is built in — `ResearcherSubAgent` runs multi-provider search automatically when the agent routes to it. No `tools=[]` argument needed.

For custom tools, write an atom function and register it:

```python
from jarviscore import AutoAgent
from jarviscore.integrations import Registry, SystemBundle

def scrape_url(url: str) -> dict:
    """Fetch and return the text content of a URL."""
    import httpx
    r = httpx.get(url, timeout=10)
    return {"url": url, "content": r.text[:5000], "status": r.status_code}

class WebTools(SystemBundle):
    scrape_url = staticmethod(scrape_url)

class ResearcherAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "web-scraping"]
    system_prompt = """
    You are a web researcher. You can scrape URLs using scrape_url(url).
    Store findings in `result` as {"findings": list, "sources": list}.
    """

    async def setup(self):
        await super().setup()
        Registry.register_bundle(WebTools)
```

The `CoderSubAgent` generates code that calls `WebTools.scrape_url(...)` directly. No tool wrapper class needed.

---

### Architectural Differences from CrewAI

Some CrewAI patterns map to a different primitive in JarvisCore rather than a direct equivalent. These are intentional design choices:

| CrewAI pattern | How JarvisCore does it |
|---|---|
| `Process.hierarchical` — manager agent auto-routes tasks | An `AutoAgent` orchestrator sends peer messages with `await self._peer_client.send(...)`. You control routing logic explicitly in Python — no hidden manager. |
| `Agent(allow_delegation=True)` | All `AutoAgent` instances can delegate to peers via the mesh peer tool — delegation is on by default, not opt-in. |
| Built-in `FileReadTool`, `DirectoryReadTool` | Write an atom function — 5 lines of Python, registered once, available to all agents. No wrapper class needed. |
| `Crew(planning=True)` | Set `goal_oriented = True` on the `AutoAgent`. The Kernel runs a planning phase before execution. |

---

## Migrating from LangGraph

### Concept Mapping

| LangGraph | JarvisCore | Notes |
|---|---|---|
| `StateGraph` | `WorkflowBuilder` | DAG execution engine |
| `Node` (function) | `AutoAgent` or `CustomAgent` | Each node is a full agent |
| `Edge` / `add_edge()` | `depends_on` in step dict | Dependency declared at call time |
| `ConditionalEdge` | `CustomAgent.on_peer_request()` with conditional routing | No built-in conditional edges; routing is agent logic |
| `State` (TypedDict shared across nodes) | `TruthContext` + Redis step outputs | Typed shared facts with evidence; step outputs persisted in Redis |
| `MemorySaver` | `UnifiedMemory` with `redis_store` | Four-tier: scratchpad, episodic ledger, LTM, Athena |
| `MessagesState` | Agent mailbox (`self.mailbox`) | Redis-backed, durable message queue |
| `Annotation` schema | `TruthFact` / `TruthContext` | Evidence-backed typed facts with version tracking |
| `app = graph.compile()` | `await mesh.start()` | Mesh compiles and starts all agents |
| `app.invoke(input)` | `await mesh.workflow(id, steps)` | Returns list of step results |
| `app.stream(input)` | Chat SSE stream via `create_chat_router` | `GET /chat/stream/{workflow_id}` |
| Checkpointer | Automatic — Redis `step_output:wf:step` | Crash-safe by default when Redis is set |
| `ToolNode` | `SystemBundle` + `Registry` | Atoms are plain functions in a bundle class |
| `HumanNode` | `self.hitl.request()` in agent code | HITL escalation with async wait |

---

### Code Translation: Simple Graph

**LangGraph:**
```python
from typing import TypedDict
from langgraph.graph import StateGraph, END

class State(TypedDict):
    topic: str
    research: str
    summary: str

def research_node(state: State) -> State:
    # ... run research
    return {**state, "research": "research findings..."}

def summarise_node(state: State) -> State:
    # ... summarise
    return {**state, "summary": f"Summary of: {state['research']}"}

graph = StateGraph(State)
graph.add_node("research", research_node)
graph.add_node("summarise", summarise_node)
graph.set_entry_point("research")
graph.add_edge("research", "summarise")
graph.add_edge("summarise", END)

app = graph.compile()
result = app.invoke({"topic": "AI hardware"})
```

**JarvisCore:**
```python
import asyncio
from jarviscore import AutoAgent, Mesh

class ResearcherAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research"]
    system_prompt = """
    Research the given topic. Store findings in `result` as {"research": str}.
    """

class SummariserAgent(AutoAgent):
    role = "summariser"
    capabilities = ["summarisation"]
    system_prompt = """
    Summarise the research provided.
    Store output in `result` as {"summary": str}.
    """

async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    mesh.add(SummariserAgent)
    await mesh.start()

    results = await mesh.workflow("ai-report", [
        {"id": "research", "agent": "researcher", "task": "Research AI hardware"},
        {"id": "summarise", "agent": "summariser", "task": "Summarise the research",
         "depends_on": ["research"]},
    ])

    print(results[-1]["payload"]["summary"])
    await mesh.stop()

asyncio.run(main())
```

---

### Code Translation: Shared State

**LangGraph** uses a `State` TypedDict that every node reads from and writes to. **JarvisCore** uses two mechanisms:

**Automatic (most workflows):** `depends_on` is sufficient. Prior step outputs are injected into the downstream agent's context window automatically.

**Typed shared facts (complex workflows):** For workflows where multiple agents need to read and write the same validated facts, use `TruthContext`:

```python
from jarviscore.context.truth import TruthContext, TruthFact, Evidence

# Initialise shared truth store for a workflow
truth = TruthContext()

# Agent A writes a fact — assign directly to truth.facts
truth.facts["competitors"] = TruthFact(
    value=["CompanyX", "CompanyY"],
    confidence=0.9,
    source="researcher",
    evidence=[Evidence(kind="doc_url", pointer="https://...", confidence=0.9)],
)

# Agent B reads it by key
fact = truth.get_fact("competitors")
if fact and fact.confidence > 0.7:
    competitors = fact.value

# Or read only the value without the metadata envelope
names = truth.get_fact_value("competitors", default=[])
```

`TruthContext` tracks mutations in a history ledger, can filter by confidence threshold (`high_confidence_facts(threshold=0.7)`), and serialises to JSON via `model_dump_json()`.

---

### Code Translation: Conditional Routing

**LangGraph:**
```python
def route(state: State) -> str:
    if state["confidence"] < 0.7:
        return "human_review"
    return "publish"

graph.add_conditional_edges("evaluate", route, {
    "human_review": "human_node",
    "publish": "publish_node",
})
```

**JarvisCore:**
```python
class EvaluatorAgent(CustomAgent):
    role = "evaluator"
    capabilities = ["evaluation"]

    async def on_peer_request(self, msg) -> dict:
        result = await self._evaluate(msg.data["content"])
        if result["confidence"] < 0.7:
            # Escalate to HITL — human reviews and responds
            await self.hitl.request(
                question="Please review this output",
                context=result,
                timeout=3600,
            )
            return {"status": "yielded", "reason": "low_confidence"}
        else:
            # Route to publisher
            await self._peer_client.send("publisher", {"content": result["output"]})
            return {"status": "routed", "target": "publisher"}
```

Conditional routing is expressed as agent logic in `on_peer_request()`. This gives you full Python expressiveness with no graph DSL to learn.

---

### Architectural Differences from LangGraph

LangGraph is a graph execution engine — JarvisCore is an agent runtime. The mental model shifts from "nodes and edges" to "agents and steps". Some patterns have direct equivalents under different names; a few reflect a genuinely different philosophy:

| LangGraph pattern | How JarvisCore does it |
|---|---|
| Typed `State` schema enforced across all nodes | `TruthContext` provides typed, evidence-backed facts shared across agents. Per-agent schema enforcement sits in the system prompt and result contract. |
| Built-in graph visualisation | No built-in DAG visualiser. The observability dashboard shows live execution traces, OODA loop thoughts, tool calls, and token usage — richer than a static graph. |
| `interrupt_before` / `interrupt_after` hooks | `CustomAgent.on_peer_request()` with pre/post logic, or HITL escalation via `self.hitl.request()`. |
| Studio (LangSmith graph UI) | JarvisCore Observability — trace events to Redis + JSONL, Prometheus metrics, and the `GET /chat/stream` SSE feed for live agent reasoning. |
| `Pregel` parallel execution model | Steps without shared `depends_on` dependencies run concurrently automatically — no explicit parallel primitives needed. |

---

## General Migration Checklist

- [ ] Replace `Agent(role=..., goal=..., backstory=...)` with an `AutoAgent` subclass with `system_prompt`
- [ ] Replace `Task(description=..., expected_output=...)` with a step dict and explicit `result` variable in the system prompt
- [ ] Replace `context=[prior_task]` / `add_edge()` with `"depends_on": ["step_id"]`
- [ ] Remove manual state passing — prior step outputs are injected automatically via `depends_on`
- [ ] Replace `Tool` classes with atom functions in a `SystemBundle`
- [ ] Set `REDIS_URL` in your environment — enables crash-safe execution, mailboxes, and memory
- [ ] Remove `LLM(model=...)` from agent constructors — configure with `TASK_MODEL_STANDARD=` in `.env`
- [ ] Add `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) to `.env`

---

## Further Reading

- [AutoAgent Guide](autoagent.md) — Full AutoAgent API
- [CustomAgent Guide](customagent.md) — For deterministic, scripted agents
- [Workflow DAGs](workflows.md) — `depends_on`, parallelism, crash recovery
- [System Prompts](system-prompts.md) — How to write effective system prompts
- [Getting Started](../getting-started.md) — Install and run your first agent in 5 minutes
