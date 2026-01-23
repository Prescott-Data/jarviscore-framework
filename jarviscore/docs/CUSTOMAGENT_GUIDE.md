# CustomAgent Guide

CustomAgent lets you integrate your **existing agent code** with JarvisCore's networking and orchestration capabilities.

**You keep**: Your execution logic, LLM calls, and business logic.
**Framework provides**: Agent discovery, peer communication, workflow orchestration, and multi-node deployment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Choose Your Mode](#choose-your-mode)
3. [P2P Mode](#p2p-mode)
4. [Distributed Mode](#distributed-mode)
5. [API Reference](#api-reference)
6. [Multi-Node Deployment](#multi-node-deployment)
7. [Error Handling](#error-handling)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Installation

```bash
pip install jarviscore-framework
```

### Your LLM Client

Throughout this guide, we use `MyLLMClient()` as a placeholder for your LLM. Replace it with your actual client:

```python
# Example: OpenAI
from openai import OpenAI
client = OpenAI()

def chat(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# Example: Anthropic
from anthropic import Anthropic
client = Anthropic()

def chat(prompt: str) -> str:
    response = client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

# Example: Local/Custom
class MyLLMClient:
    def chat(self, prompt: str) -> str:
        # Your implementation
        return "response"
```

---

## Choose Your Mode

```
┌─────────────────────────────────────────────────────────────┐
│                  Which mode should I use?                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │ Do agents need to coordinate  │
              │ continuously in real-time?    │
              └───────────────────────────────┘
                     │                │
                    YES              NO
                     │                │
                     ▼                ▼
              ┌──────────┐    ┌───────────────────────┐
              │ P2P Mode │    │ Do you have task      │
              └──────────┘    │ pipelines with        │
                              │ dependencies?         │
                              └───────────────────────┘
                                   │           │
                                  YES         NO
                                   │           │
                                   ▼           ▼
                            ┌────────────┐  ┌──────────┐
                            │Distributed │  │ P2P Mode │
                            │   Mode     │  └──────────┘
                            └────────────┘
```

### Quick Comparison

| Feature | P2P Mode | Distributed Mode |
|---------|----------|------------------|
| **Primary method** | `run()` - continuous loop | `execute_task()` - on-demand |
| **Communication** | Direct peer messaging | Workflow orchestration |
| **Best for** | Chatbots, real-time agents | Pipelines, batch processing |
| **Coordination** | Agents self-coordinate | Framework coordinates |
| **Supports workflows** | No | Yes |

---

## P2P Mode

P2P mode is for agents that run continuously and communicate directly with each other.

### Migration Overview

```
YOUR PROJECT STRUCTURE
──────────────────────────────────────────────────────────────────

BEFORE (standalone):          AFTER (with JarvisCore):
├── my_agent.py              ├── agents.py        ← Modified agent code
└── (run directly)           └── main.py          ← NEW entry point
                                  ▲
                                  │
                         This is now how you
                         start your agents
```

### Step 1: Install the Framework

```bash
pip install jarviscore-framework
```

### Step 2: Your Existing Code (Before)

Let's say you have a standalone agent like this:

```python
# my_agent.py (YOUR EXISTING CODE)
class MyResearcher:
    """Your existing agent - runs standalone."""

    def __init__(self):
        self.llm = MyLLMClient()

    def research(self, query: str) -> str:
        return self.llm.chat(f"Research: {query}")

# You currently run it directly:
if __name__ == "__main__":
    agent = MyResearcher()
    result = agent.research("What is AI?")
    print(result)
```

### Step 3: Modify Your Agent Code → `agents.py`

Convert your existing class to inherit from `CustomAgent`:

```python
# agents.py (MODIFIED VERSION OF YOUR CODE)
import asyncio
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Your agent, now framework-integrated."""

    # NEW: Required class attributes for discovery
    role = "researcher"
    capabilities = ["research", "analysis"]

    async def setup(self):
        """NEW: Called once on startup. Move your __init__ logic here."""
        await super().setup()
        self.llm = MyLLMClient()  # Your existing initialization

    async def run(self):
        """NEW: Main loop - replaces your if __name__ == '__main__' block."""
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("question", "")
                    # YOUR EXISTING LOGIC:
                    result = self.llm.chat(f"Research: {query}")
                    await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        """
        Required by base Agent class (@abstractmethod).

        In P2P mode, your main logic lives in run(), not here.
        This must exist because Python requires all abstract methods
        to be implemented, or you get TypeError on instantiation.
        """
        return {"status": "success", "note": "This agent uses run() for P2P mode"}
```

**What changed:**

| Before | After |
|--------|-------|
| `class MyResearcher:` | `class ResearcherAgent(CustomAgent):` |
| `def __init__(self):` | `async def setup(self):` + `await super().setup()` |
| `if __name__ == "__main__":` | `async def run(self):` loop |
| Direct method calls | Peer message handling |

### Step 4: Create New Entry Point → `main.py`

**This is your NEW main file.** Instead of running `python my_agent.py`, you'll run `python main.py`.

```python
# main.py (NEW FILE - YOUR NEW ENTRY POINT)
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent


async def main():
    # Create the mesh network
    mesh = Mesh(
        mode="p2p",
        config={
            "bind_port": 7950,      # Port for P2P communication
            "node_name": "my-node", # Identifies this node in the network
        }
    )

    # Register your agent(s)
    mesh.add(ResearcherAgent)

    # Start the mesh (calls setup() on all agents)
    await mesh.start()

    # Run forever - agents handle their own work in run() loops
    await mesh.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

**Why a new entry file?**

| Reason | Explanation |
|--------|-------------|
| **Mesh setup** | The Mesh handles networking, discovery, and lifecycle |
| **Multiple agents** | You can add many agents to one mesh |
| **Clean separation** | Agent logic in `agents.py`, orchestration in `main.py` |
| **Standard pattern** | Consistent entry point across all JarvisCore projects |

### Step 5: Run Your Agents

```bash
# OLD WAY (no longer used):
# python my_agent.py

# NEW WAY:
python main.py
```

---

### Complete Example: Two Agents Communicating

This example shows an assistant that delegates research to a researcher agent.

```python
# agents.py
import asyncio
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Agent that performs research when asked by peers."""

    role = "researcher"
    capabilities = ["research", "analysis"]

    async def setup(self):
        await super().setup()
        # Initialize your LLM client here
        # self.llm = MyLLMClient()

    async def run(self):
        """Listen for research requests from peers."""
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("question", "")

                    # Your research logic here
                    result = f"Research results for: {query}"
                    # result = self.llm.chat(f"Research: {query}")

                    await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        return {"status": "success"}


class AssistantAgent(CustomAgent):
    """Agent that helps users and delegates research to ResearcherAgent."""

    role = "assistant"
    capabilities = ["help", "coordination"]

    async def setup(self):
        await super().setup()
        # self.llm = MyLLMClient()

    async def ask_researcher(self, question: str) -> str:
        """Send a question to the researcher agent and wait for response."""
        if not self.peers:
            return "Peer system not available"

        try:
            response = await self.peers.as_tool().execute(
                "ask_peer",
                {"role": "researcher", "question": question}
            )
            return response.get("response", "No response received")
        except Exception as e:
            return f"Failed to reach researcher: {e}"

    async def help(self, question: str) -> str:
        """Public method - answer a question using research."""
        research = await self.ask_researcher(question)

        # Your logic to combine research with answer
        answer = f"Based on research: {research}\nAnswer: {question}"
        # answer = self.llm.chat(f"Based on: {research}\nAnswer: {question}")

        return answer

    async def run(self):
        """Main loop - could listen for HTTP requests, websockets, etc."""
        while not self.shutdown_requested:
            await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        return {"status": "success"}
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, AssistantAgent


async def main():
    mesh = Mesh(
        mode="p2p",
        config={
            "bind_port": 7950,
            "node_name": "assistant-node",
        }
    )

    mesh.add(ResearcherAgent)
    mesh.add(AssistantAgent)

    await mesh.start()

    # Get the assistant agent instance to interact with it
    assistant = mesh.get_agent("assistant")

    # Ask a question
    result = await assistant.help("What is quantum computing?")
    print(result)

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Concepts for P2P Mode

#### The `run()` Method

This is your agent's main loop. It runs continuously until shutdown.

```python
async def run(self):
    while not self.shutdown_requested:  # Framework sets this on shutdown
        # Your continuous logic here
        await asyncio.sleep(0.1)  # Prevent CPU spinning
```

#### The `self.peers` Object

Available after `setup()` completes. Provides peer communication:

```python
# Check if peers system is available
if self.peers:
    # Receive messages (non-blocking with timeout)
    msg = await self.peers.receive(timeout=0.5)

    # Respond to a request
    await self.peers.respond(msg, {"key": "value"})

    # Use peer tools
    result = await self.peers.as_tool().execute("ask_peer", {...})
```

#### The `self.shutdown_requested` Flag

Set to `True` by the framework when `mesh.stop()` is called. Always check this in your `run()` loop.

---

## Distributed Mode

Distributed mode is for task pipelines where the framework orchestrates execution order and passes data between steps.

### Migration Overview

```
YOUR PROJECT STRUCTURE
──────────────────────────────────────────────────────────────────

BEFORE (standalone):          AFTER (with JarvisCore):
├── pipeline.py              ├── agents.py        ← Modified agent code
└── (manual orchestration)   └── main.py          ← NEW entry point
                                  ▲
                                  │
                         This is now how you
                         start your pipeline
```

### Step 1: Install the Framework

```bash
pip install jarviscore-framework
```

### Step 2: Your Existing Code (Before)

Let's say you have a manual pipeline like this:

```python
# pipeline.py (YOUR EXISTING CODE)
class Researcher:
    def execute(self, task: str) -> dict:
        return {"output": f"Research on: {task}"}

class Writer:
    def execute(self, task: str, context: dict = None) -> dict:
        return {"output": f"Article based on: {context}"}

# Manual orchestration - you pass data between steps yourself:
if __name__ == "__main__":
    researcher = Researcher()
    writer = Writer()

    research = researcher.execute("AI trends")
    article = writer.execute("Write article", context=research)  # Manual!
    print(article)
```

**Problems with this approach:**
- You manually pass context between steps
- No dependency management
- Hard to run on multiple machines
- No automatic retries on failure

### Step 3: Modify Your Agent Code → `agents.py`

Convert your existing classes to inherit from `CustomAgent`:

```python
# agents.py (MODIFIED VERSION OF YOUR CODE)
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Your researcher, now framework-integrated."""

    # NEW: Required class attributes
    role = "researcher"
    capabilities = ["research"]

    async def setup(self):
        """NEW: Called once on startup."""
        await super().setup()
        # Your initialization here (DB connections, LLM clients, etc.)

    async def execute_task(self, task: dict) -> dict:
        """
        MODIFIED: Now receives a task dict, returns a result dict.

        The framework calls this method - you don't call it manually.
        """
        task_desc = task.get("task", "")

        # YOUR EXISTING LOGIC:
        result = f"Research on: {task_desc}"

        # NEW: Return format for framework
        return {
            "status": "success",
            "output": result
        }


class WriterAgent(CustomAgent):
    """Your writer, now framework-integrated."""

    role = "writer"
    capabilities = ["writing"]

    async def setup(self):
        await super().setup()

    async def execute_task(self, task: dict) -> dict:
        """
        Context from previous steps is AUTOMATICALLY injected.
        No more manual passing!
        """
        task_desc = task.get("task", "")
        context = task.get("context", {})  # ← Framework injects this!

        # YOUR EXISTING LOGIC:
        research_output = context.get("research", {}).get("output", "")
        result = f"Article based on: {research_output}"

        return {
            "status": "success",
            "output": result
        }
```

**What changed:**

| Before | After |
|--------|-------|
| `class Researcher:` | `class ResearcherAgent(CustomAgent):` |
| `def execute(self, task):` | `async def execute_task(self, task: dict):` |
| Return anything | Return `{"status": "...", "output": ...}` |
| Manual `context=research` | Framework auto-injects via `depends_on` |

### Step 4: Create New Entry Point → `main.py`

**This is your NEW main file.** Instead of running `python pipeline.py`, you'll run `python main.py`.

```python
# main.py (NEW FILE - YOUR NEW ENTRY POINT)
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, WriterAgent


async def main():
    # Create the mesh network
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_port": 7950,
            "node_name": "pipeline-node",
        }
    )

    # Register your agents
    mesh.add(ResearcherAgent)
    mesh.add(WriterAgent)

    # Start the mesh (calls setup() on all agents)
    await mesh.start()

    # Define your workflow - framework handles orchestration!
    results = await mesh.workflow("content-pipeline", [
        {
            "id": "research",           # Step identifier
            "agent": "researcher",      # Which agent handles this
            "task": "AI trends 2024"    # Task description
        },
        {
            "id": "write",
            "agent": "writer",
            "task": "Write a blog post",
            "depends_on": ["research"]  # ← Framework auto-injects research output!
        }
    ])

    # Results in workflow order
    print("Research:", results[0]["output"])
    print("Article:", results[1]["output"])

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

**Why a new entry file?**

| Reason | Explanation |
|--------|-------------|
| **Workflow orchestration** | `mesh.workflow()` handles dependencies, ordering, retries |
| **No manual context passing** | `depends_on` automatically injects previous step outputs |
| **Multiple agents** | Register all agents in one place |
| **Multi-node ready** | Same code works across machines with `seed_nodes` config |
| **Clean separation** | Agent logic in `agents.py`, orchestration in `main.py` |

### Step 5: Run Your Pipeline

```bash
# OLD WAY (no longer used):
# python pipeline.py

# NEW WAY:
python main.py
```

---

### Complete Example: Three-Stage Content Pipeline

This example shows a research → write → review pipeline.

```python
# agents.py
from jarviscore.profiles import CustomAgent


class ResearcherAgent(CustomAgent):
    """Researches topics and returns findings."""

    role = "researcher"
    capabilities = ["research"]

    async def setup(self):
        await super().setup()
        # self.llm = MyLLMClient()

    async def execute_task(self, task: dict) -> dict:
        topic = task.get("task", "")

        # Your research logic
        findings = f"Research findings on: {topic}"
        # findings = self.llm.chat(f"Research: {topic}")

        return {
            "status": "success",
            "output": findings
        }


class WriterAgent(CustomAgent):
    """Writes content based on research."""

    role = "writer"
    capabilities = ["writing"]

    async def setup(self):
        await super().setup()
        # self.llm = MyLLMClient()

    async def execute_task(self, task: dict) -> dict:
        instruction = task.get("task", "")
        context = task.get("context", {})  # Output from depends_on steps

        # Combine context from previous steps
        research = context.get("research", {}).get("output", "")

        # Your writing logic
        article = f"Article based on: {research}\nTopic: {instruction}"
        # article = self.llm.chat(f"Based on: {research}\nWrite: {instruction}")

        return {
            "status": "success",
            "output": article
        }


class EditorAgent(CustomAgent):
    """Reviews and polishes content."""

    role = "editor"
    capabilities = ["editing", "review"]

    async def setup(self):
        await super().setup()

    async def execute_task(self, task: dict) -> dict:
        instruction = task.get("task", "")
        context = task.get("context", {})

        # Get output from the writing step
        draft = context.get("write", {}).get("output", "")

        # Your editing logic
        polished = f"[EDITED] {draft}"

        return {
            "status": "success",
            "output": polished
        }
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent, WriterAgent, EditorAgent


async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_port": 7950,
            "node_name": "content-node",
        }
    )

    mesh.add(ResearcherAgent)
    mesh.add(WriterAgent)
    mesh.add(EditorAgent)

    await mesh.start()

    # Define a multi-step workflow with dependencies
    results = await mesh.workflow("content-pipeline", [
        {
            "id": "research",           # Unique step identifier
            "agent": "researcher",      # Which agent handles this
            "task": "AI trends in 2024" # Task description
        },
        {
            "id": "write",
            "agent": "writer",
            "task": "Write a blog post about the research",
            "depends_on": ["research"]  # Wait for research, inject its output
        },
        {
            "id": "edit",
            "agent": "editor",
            "task": "Polish and improve the article",
            "depends_on": ["write"]     # Wait for writing step
        }
    ])

    # Results are in workflow order
    print("Research:", results[0]["output"])
    print("Draft:", results[1]["output"])
    print("Final:", results[2]["output"])

    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Concepts for Distributed Mode

#### The `execute_task()` Method

Called by the workflow engine when a task is assigned to your agent.

```python
async def execute_task(self, task: dict) -> dict:
    # task dict contains:
    # - "id": str - the step ID from the workflow
    # - "task": str - the task description
    # - "context": dict - outputs from depends_on steps (keyed by step ID)

    return {
        "status": "success",  # or "error"
        "output": result,     # your result data
        # "error": "message"  # if status is "error"
    }
```

#### The `task` Dictionary Structure

```python
{
    "id": "step_id",              # Step identifier from workflow
    "task": "task description",   # What to do
    "context": {                  # Outputs from dependencies
        "previous_step_id": {
            "status": "success",
            "output": "..."       # Whatever previous step returned
        }
    }
}
```

#### Workflow Step Definition

```python
{
    "id": "unique_step_id",       # Required: unique identifier
    "agent": "agent_role",        # Required: which agent handles this
    "task": "description",        # Required: task description
    "depends_on": ["step1", ...]  # Optional: steps that must complete first
}
```

#### Parallel Execution

Steps without `depends_on` or with satisfied dependencies run in parallel:

```python
results = await mesh.workflow("parallel-example", [
    {"id": "a", "agent": "worker", "task": "Task A"},          # Runs immediately
    {"id": "b", "agent": "worker", "task": "Task B"},          # Runs in parallel with A
    {"id": "c", "agent": "worker", "task": "Task C",
     "depends_on": ["a", "b"]},                                 # Waits for A and B
])
```

---

## API Reference

### CustomAgent Class Attributes

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `role` | `str` | Yes | Unique identifier for this agent type (e.g., `"researcher"`) |
| `capabilities` | `list[str]` | Yes | List of capabilities for discovery (e.g., `["research", "analysis"]`) |

### CustomAgent Methods

| Method | Mode | Description |
|--------|------|-------------|
| `setup()` | Both | Called once on startup. Initialize resources here. Always call `await super().setup()` |
| `run()` | P2P | Main loop for continuous operation. Required for P2P mode |
| `execute_task(task)` | Distributed | Handle a workflow task. Required for Distributed mode |

### Why `execute_task()` is Required in P2P Mode

You may notice that P2P agents must implement `execute_task()` even though they primarily use `run()`. Here's why:

```
Agent (base class)
    │
    ├── @abstractmethod execute_task()  ← Python REQUIRES this to be implemented
    │
    └── run()  ← Optional, default does nothing
```

**The technical reason:**

1. `Agent.execute_task()` is declared as `@abstractmethod` in `core/agent.py`
2. Python's ABC (Abstract Base Class) requires ALL abstract methods to be implemented
3. If you don't implement it, Python raises:
   ```
   TypeError: Can't instantiate abstract class MyAgent with abstract method execute_task
   ```

**The design reason:**

- **Unified interface**: All agents can be called via `execute_task()`, regardless of mode
- **Flexibility**: A P2P agent can still participate in workflows if needed
- **Testing**: You can test any agent by calling `execute_task()` directly

**What to put in it for P2P mode:**

```python
async def execute_task(self, task: dict) -> dict:
    """Minimal implementation - main logic is in run()."""
    return {"status": "success", "note": "This agent uses run() for P2P mode"}
```

### Peer Tools (P2P Mode)

Access via `self.peers.as_tool().execute(tool_name, params)`:

| Tool | Parameters | Description |
|------|------------|-------------|
| `ask_peer` | `{"role": str, "question": str}` | Send a request to a peer by role and wait for response |
| `broadcast` | `{"message": str}` | Send a message to all connected peers |
| `list_peers` | `{}` | Get list of available peers and their capabilities |

### Mesh Configuration

```python
mesh = Mesh(
    mode="p2p" | "distributed",
    config={
        "bind_host": "0.0.0.0",          # IP to bind to (default: "127.0.0.1")
        "bind_port": 7950,                # Port to listen on
        "node_name": "my-node",           # Human-readable node name
        "seed_nodes": "ip:port,ip:port",  # Comma-separated list of known nodes
    }
)
```

### Mesh Methods

| Method | Description |
|--------|-------------|
| `mesh.add(AgentClass)` | Register an agent class |
| `mesh.start()` | Initialize and start all agents |
| `mesh.stop()` | Gracefully shut down all agents |
| `mesh.run_forever()` | Block until shutdown signal |
| `mesh.serve_forever()` | Same as `run_forever()` |
| `mesh.get_agent(role)` | Get agent instance by role |
| `mesh.workflow(name, steps)` | Run a workflow (Distributed mode) |

---

## Multi-Node Deployment

Run agents across multiple machines. Nodes discover each other via seed nodes.

### Machine 1: Research Node

```python
# research_node.py
import asyncio
from jarviscore import Mesh
from agents import ResearcherAgent


async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_host": "0.0.0.0",        # Accept connections from any IP
            "bind_port": 7950,
            "node_name": "research-node",
        }
    )

    mesh.add(ResearcherAgent)
    await mesh.start()

    print("Research node running on port 7950...")
    await mesh.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

### Machine 2: Writer Node + Orchestrator

```python
# writer_node.py
import asyncio
from jarviscore import Mesh
from agents import WriterAgent


async def main():
    mesh = Mesh(
        mode="distributed",
        config={
            "bind_host": "0.0.0.0",
            "bind_port": 7950,
            "node_name": "writer-node",
            "seed_nodes": "192.168.1.10:7950",  # IP of research node
        }
    )

    mesh.add(WriterAgent)
    await mesh.start()

    # Wait for nodes to discover each other
    await asyncio.sleep(2)

    # Run workflow - tasks automatically route to correct nodes
    results = await mesh.workflow("cross-node-pipeline", [
        {"id": "research", "agent": "researcher", "task": "AI trends"},
        {"id": "write", "agent": "writer", "task": "Write article",
         "depends_on": ["research"]},
    ])

    print(results)
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### How Node Discovery Works

1. On startup, nodes connect to seed nodes
2. Seed nodes share their known peers
3. Nodes exchange agent capability information
4. Workflows automatically route tasks to nodes with matching agents

---

## Error Handling

### In P2P Mode

```python
async def run(self):
    while not self.shutdown_requested:
        try:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    try:
                        result = await self.process(msg.data)
                        await self.peers.respond(msg, {"response": result})
                    except Exception as e:
                        await self.peers.respond(msg, {
                            "error": str(e),
                            "status": "failed"
                        })
        except Exception as e:
            print(f"Error in run loop: {e}")

        await asyncio.sleep(0.1)
```

### In Distributed Mode

```python
async def execute_task(self, task: dict) -> dict:
    try:
        result = await self.do_work(task)
        return {
            "status": "success",
            "output": result
        }
    except ValueError as e:
        return {
            "status": "error",
            "error": f"Invalid input: {e}"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Unexpected error: {e}"
        }
```

### Handling Missing Peers

```python
async def ask_researcher(self, question: str) -> str:
    if not self.peers:
        raise RuntimeError("Peer system not initialized")

    try:
        response = await asyncio.wait_for(
            self.peers.as_tool().execute(
                "ask_peer",
                {"role": "researcher", "question": question}
            ),
            timeout=30.0  # 30 second timeout
        )
        return response.get("response", "")
    except asyncio.TimeoutError:
        raise RuntimeError("Researcher did not respond in time")
    except Exception as e:
        raise RuntimeError(f"Failed to contact researcher: {e}")
```

---

## Troubleshooting

### Agent not receiving messages

**Problem**: `self.peers.receive()` always returns `None`

**Solutions**:
1. Ensure the sending agent is using the correct `role` in `ask_peer`
2. Check that both agents are registered with the mesh
3. Verify `await super().setup()` is called in your `setup()` method
4. Add logging to confirm your `run()` loop is executing

### Workflow tasks not executing

**Problem**: `mesh.workflow()` hangs or returns empty results

**Solutions**:
1. Verify agent `role` matches the `agent` field in workflow steps
2. Check `execute_task()` returns a dict with `status` key
3. Ensure all `depends_on` step IDs exist in the workflow
4. Check for circular dependencies

### Nodes not discovering each other

**Problem**: Multi-node setup, but workflows fail to find agents

**Solutions**:
1. Verify `seed_nodes` IP and port are correct
2. Check firewall allows connections on the bind port
3. Ensure `bind_host` is `"0.0.0.0"` (not `"127.0.0.1"`) for remote connections
4. Wait a few seconds after `mesh.start()` for discovery to complete

### "Peer system not available" errors

**Problem**: `self.peers` is `None`

**Solutions**:
1. Only access `self.peers` after `setup()` completes
2. Check that mesh is started with `await mesh.start()`
3. Verify the agent was added with `mesh.add(AgentClass)`

---

## Examples

For complete, runnable examples, see:

- `examples/customagent_p2p_example.py` - P2P mode with peer communication
- `examples/customagent_distributed_example.py` - Distributed mode with workflows
