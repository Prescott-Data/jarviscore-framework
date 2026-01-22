# CustomAgent Guide

CustomAgent is for users who **already have working code** and want to integrate with JarvisCore.

You keep your execution logic. Framework provides:
- Agent discovery and communication
- Workflow orchestration (distributed mode)
- P2P peer tools (ask_peer, broadcast, etc.)

---

## Quick Reference

| Mode | Use Case | Agent Method |
|------|----------|--------------|
| **P2P** | Direct agent communication | `run()` loop |
| **Distributed** | Multi-node workflows | `execute_task()` |

---

## P2P Mode: Standalone → Framework

### Your Standalone Agents (Before)

You have two agents that communicate directly:

```python
# standalone_researcher.py
class StandaloneResearcher:
    """Your existing researcher agent."""

    def __init__(self):
        self.llm = MyLLMClient()

    def research(self, query: str) -> str:
        """Your existing research logic."""
        return self.llm.chat(f"Research: {query}")


# standalone_assistant.py
class StandaloneAssistant:
    """Your existing assistant that needs researcher help."""

    def __init__(self, researcher: StandaloneResearcher):
        self.researcher = researcher  # Direct reference
        self.llm = MyLLMClient()

    def help(self, question: str) -> str:
        # Directly calls researcher
        research = self.researcher.research(question)
        return self.llm.chat(f"Based on: {research}\nAnswer: {question}")
```

**Problem**: Agents are tightly coupled. Can't run on different machines.

---

### With JarvisCore P2P Mode (After)

**Step 1: Create `agents.py`** - Convert to CustomAgent

```python
# agents.py
from jarviscore.profiles import CustomAgent

class ResearcherAgent(CustomAgent):
    """Same logic, now framework-integrated."""
    role = "researcher"
    capabilities = ["research", "analysis"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your existing LLM

    async def run(self):
        """REQUIRED for P2P: Listen for peer requests."""
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("question", "")
                    # Your existing logic
                    result = self.llm.chat(f"Research: {query}")
                    await self.peers.respond(msg, {"response": result})
            else:
                await asyncio.sleep(0.1)

    async def execute_task(self, task):
        return {"status": "success"}  # Required but unused in P2P


class AssistantAgent(CustomAgent):
    """Same logic, now uses peer tools instead of direct reference."""
    role = "assistant"
    capabilities = ["help", "coordination"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def ask_researcher(self, question: str) -> str:
        """Replaces direct self.researcher reference."""
        if self.peers:
            return await self.peers.as_tool().execute(
                "ask_peer",
                {"role": "researcher", "question": question}
            )
        return "No researcher available"

    async def help(self, question: str) -> str:
        """Your existing logic, now uses peer communication."""
        research = await self.ask_researcher(question)
        return self.llm.chat(f"Based on: {research}\nAnswer: {question}")

    async def run(self):
        """Listen for requests or external triggers."""
        while not self.shutdown_requested:
            # Your run loop - could listen for HTTP, websocket, etc.
            await asyncio.sleep(0.1)

    async def execute_task(self, task):
        return {"status": "success"}
```

**Step 2: Create `main.py`** - Run with mesh

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, AssistantAgent

async def main():
    mesh = Mesh(
        mode="p2p",
        config={
            'bind_port': 7950,
            'node_name': 'my-agents',
        }
    )

    mesh.add(ResearcherAgent)
    mesh.add(AssistantAgent)

    await mesh.start()

    # Option 1: Run forever (agents handle their own work)
    # await mesh.run_forever()

    # Option 2: Manual interaction
    assistant = mesh.get_agent("assistant")
    result = await assistant.help("What is quantum computing?")
    print(result)

    await mesh.stop()

asyncio.run(main())
```

### What Changed

| Before | After |
|--------|-------|
| Direct object reference | `self.peers.as_tool().execute("ask_peer", ...)` |
| Tightly coupled | Loosely coupled via peer discovery |
| Same process only | Can run on different machines |
| No discovery | Automatic agent discovery |

### Key Additions

1. **Inherit from `CustomAgent`** instead of plain class
2. **Add `role` and `capabilities`** class attributes
3. **Implement `run()`** method for continuous listening
4. **Use `self.peers`** for communication instead of direct references

---

## Distributed Mode: Standalone → Framework

### Your Standalone Pipeline (Before)

You have agents that execute in a pipeline:

```python
# standalone_pipeline.py
class StandaloneResearcher:
    def __init__(self):
        self.llm = MyLLMClient()

    def execute(self, task: str) -> dict:
        result = self.llm.chat(f"Research: {task}")
        return {"output": result}


class StandaloneWriter:
    def __init__(self):
        self.llm = MyLLMClient()

    def execute(self, task: str, context: dict = None) -> dict:
        prompt = task
        if context:
            prompt = f"Based on: {context}\n\n{task}"
        result = self.llm.chat(prompt)
        return {"output": result}


# Manual orchestration
def run_pipeline():
    researcher = StandaloneResearcher()
    writer = StandaloneWriter()

    # Step 1
    research = researcher.execute("Research AI trends")

    # Step 2 - manually pass context
    article = writer.execute("Write article", context=research["output"])

    return article
```

**Problem**: Manual orchestration. No dependency management. Single machine.

---

### With JarvisCore Distributed Mode (After)

**Step 1: Create `agents.py`** - Convert to CustomAgent

```python
# agents.py
from jarviscore.profiles import CustomAgent

class ResearcherAgent(CustomAgent):
    role = "researcher"
    capabilities = ["research"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def execute_task(self, task):
        """REQUIRED for Distributed: Called by workflow engine."""
        task_desc = task.get("task", "")
        # Your existing logic
        result = self.llm.chat(f"Research: {task_desc}")
        return {
            "status": "success",
            "output": result
        }


class WriterAgent(CustomAgent):
    role = "writer"
    capabilities = ["writing"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def execute_task(self, task):
        """Context from previous steps is automatically passed."""
        task_desc = task.get("task", "")
        context = task.get("context", {})  # From depends_on steps

        prompt = task_desc
        if context:
            prompt = f"Based on: {context}\n\n{task_desc}"

        result = self.llm.chat(prompt)
        return {
            "status": "success",
            "output": result
        }
```

**Step 2: Create `main.py`** - Run with mesh

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, WriterAgent

async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            'bind_port': 7950,
            'node_name': 'content-node',
        }
    )

    mesh.add(ResearcherAgent)
    mesh.add(WriterAgent)

    await mesh.start()

    # Workflow engine handles orchestration
    results = await mesh.workflow("content-pipeline", [
        {
            "id": "research",
            "agent": "researcher",
            "task": "Research AI trends"
        },
        {
            "id": "write",
            "agent": "writer",
            "task": "Write article about the research",
            "depends_on": ["research"]  # Auto-injects context
        }
    ])

    print(results[0]["output"])  # Research
    print(results[1]["output"])  # Article

    await mesh.stop()

asyncio.run(main())
```

### What Changed

| Before | After |
|--------|-------|
| Manual `context` passing | `depends_on` + automatic injection |
| Manual orchestration | `mesh.workflow()` handles it |
| Same process only | Can span multiple machines |
| No retries | Framework handles failures |

### Key Additions

1. **Inherit from `CustomAgent`**
2. **Add `role` and `capabilities`**
3. **Implement `execute_task(task)`** - receives `task` dict with `context`
4. **Use `mesh.workflow()`** with `depends_on` for dependencies

---

## Multi-Node Distributed

Same agents, different machines:

**Machine 1:**
```python
mesh = Mesh(mode="distributed", config={
    'bind_host': '0.0.0.0',
    'bind_port': 7950,
    'node_name': 'research-node',
})
mesh.add(ResearcherAgent)
await mesh.start()
await mesh.serve_forever()
```

**Machine 2:**
```python
mesh = Mesh(mode="distributed", config={
    'bind_host': '0.0.0.0',
    'bind_port': 7950,
    'node_name': 'writer-node',
    'seed_nodes': '192.168.1.10:7950',  # Machine 1
})
mesh.add(WriterAgent)
await mesh.start()
await mesh.serve_forever()
```

Workflows automatically route to the right machine.

---

## P2P vs Distributed: Which to Use?

| Scenario | Mode |
|----------|------|
| Agents run continuously, self-coordinate | **P2P** |
| Chatbot with specialist agents | **P2P** |
| Task pipelines with dependencies | **Distributed** |
| Need workflow orchestration | **Distributed** |
| Both continuous + workflows | **Distributed** (supports both) |

---

## Summary

### P2P Mode
```python
class MyAgent(CustomAgent):
    role = "my_role"
    capabilities = ["my_cap"]

    async def run(self):  # Required
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            # Handle messages

mesh = Mesh(mode="p2p", config={'bind_port': 7950})
await mesh.run_forever()
```

### Distributed Mode
```python
class MyAgent(CustomAgent):
    role = "my_role"
    capabilities = ["my_cap"]

    async def execute_task(self, task):  # Required
        # Your logic
        return {"status": "success", "output": result}

mesh = Mesh(mode="distributed", config={'bind_port': 7950})
results = await mesh.workflow("my-workflow", [...])
```

See `examples/customagent_p2p_example.py` and `examples/customagent_distributed_example.py` for complete examples.
