# CustomAgent Guide

CustomAgent lets you integrate your **existing agent code** with JarvisCore's networking and orchestration capabilities.

**You keep**: Your execution logic, LLM calls, and business logic.
**Framework provides**: Agent discovery, peer communication, workflow orchestration, and multi-node deployment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Choose Your Mode](#choose-your-mode)
3. [P2P Mode](#p2p-mode)
4. [ListenerAgent (v0.3.0)](#listeneragent-v030) - API-first agents without run() loops
5. [Distributed Mode](#distributed-mode)
6. [Cognitive Discovery (v0.3.0)](#cognitive-discovery-v030) - Dynamic peer awareness for LLMs
7. [FastAPI Integration (v0.3.0)](#fastapi-integration-v030) - 3-line setup with JarvisLifespan
8. [Cloud Deployment (v0.3.0)](#cloud-deployment-v030) - Self-registration for containers
9. [API Reference](#api-reference)
10. [Multi-Node Deployment](#multi-node-deployment)
11. [Error Handling](#error-handling)
12. [Troubleshooting](#troubleshooting)

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

| Feature | P2P Mode (CustomAgent) | P2P Mode (ListenerAgent) | Distributed Mode |
|---------|------------------------|--------------------------|------------------|
| **Primary method** | `run()` - continuous loop | `on_peer_request()` handlers | `execute_task()` - on-demand |
| **Communication** | Direct peer messaging | Handler-based (no loop) | Workflow orchestration |
| **Best for** | Custom message loops | API-first agents, FastAPI | Pipelines, batch processing |
| **Coordination** | Agents self-coordinate | Framework handles loop | Framework coordinates |
| **Supports workflows** | No | No | Yes |

> **New in v0.3.0**: `ListenerAgent` lets you write P2P agents without managing the `run()` loop yourself. Just implement `on_peer_request()` and `on_peer_notify()` handlers.

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

> **Note**: This is a minimal example. For the full pattern with **LLM-driven peer communication** (where your LLM autonomously decides when to call other agents), see the [Complete Example](#complete-example-llm-driven-peer-communication) below.

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

### Complete Example: LLM-Driven Peer Communication

This is the **key pattern** for P2P mode. Your LLM gets peer tools added to its toolset, and it **autonomously decides** when to ask other agents for help.

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM-DRIVEN PEER COMMUNICATION                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User: "Analyze this sales data"                                │
│                    │                                            │
│                    ▼                                            │
│  ┌─────────────────────────────────────┐                        │
│  │         ASSISTANT'S LLM             │                        │
│  │                                     │                        │
│  │  Tools available:                   │                        │
│  │  - web_search (local)               │                        │
│  │  - ask_peer   (peer) ◄── NEW!       │                        │
│  │  - broadcast  (peer) ◄── NEW!       │                        │
│  │                                     │                        │
│  │  LLM decides: "I need analysis      │                        │
│  │  help, let me ask the analyst"      │                        │
│  └─────────────────────────────────────┘                        │
│                    │                                            │
│                    ▼ uses ask_peer tool                         │
│  ┌─────────────────────────────────────┐                        │
│  │          ANALYST AGENT              │                        │
│  │  (processes with its own LLM)       │                        │
│  └─────────────────────────────────────┘                        │
│                    │                                            │
│                    ▼ returns analysis                           │
│  ┌─────────────────────────────────────┐                        │
│  │         ASSISTANT'S LLM             │                        │
│  │  "Based on the analyst's findings,  │                        │
│  │   here's your answer..."            │                        │
│  └─────────────────────────────────────┘                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**The key insight**: You add peer tools to your LLM's toolset. The LLM decides when to use them.

```python
# agents.py
import asyncio
from jarviscore.profiles import CustomAgent


class AnalystAgent(CustomAgent):
    """
    Analyst agent - specialists in data analysis.

    This agent:
    1. Listens for incoming requests from peers
    2. Processes requests using its own LLM
    3. Responds with analysis results
    """
    role = "analyst"
    capabilities = ["analysis", "data_interpretation", "reporting"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your LLM client

    def get_tools(self) -> list:
        """
        Tools available to THIS agent's LLM.

        The analyst has local analysis tools.
        It can also ask other peers if needed.
        """
        tools = [
            {
                "name": "statistical_analysis",
                "description": "Run statistical analysis on numeric data",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string", "description": "Data to analyze"}
                    },
                    "required": ["data"]
                }
            }
        ]

        # ADD PEER TOOLS - so LLM can ask other agents if needed
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """
        Execute a tool by name.

        Routes to peer tools or local tools as appropriate.
        """
        # PEER TOOLS - check and execute
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # LOCAL TOOLS
        if tool_name == "statistical_analysis":
            data = args.get("data", "")
            return f"Analysis of '{data}': mean=150.3, std=23.4, trend=positive"

        return f"Unknown tool: {tool_name}"

    async def process_with_llm(self, query: str) -> str:
        """Process a request using LLM with tools."""
        system_prompt = """You are an expert data analyst.
You have tools for statistical analysis.
Analyze data thoroughly and provide insights."""

        tools = self.get_tools()
        messages = [{"role": "user", "content": query}]

        # Call LLM with tools
        response = self.llm.chat(messages, tools=tools, system=system_prompt)

        # Handle tool use if LLM decides to use a tool
        if response.get("type") == "tool_use":
            tool_result = await self.execute_tool(
                response["tool_name"],
                response["tool_args"]
            )
            # Continue conversation with tool result
            response = self.llm.continue_with_tool_result(
                messages, response["tool_use_id"], tool_result
            )

        return response.get("content", "Analysis complete.")

    async def run(self):
        """Listen for incoming requests from peers."""
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("question", msg.data.get("query", ""))

                    # Process with LLM
                    result = await self.process_with_llm(query)

                    await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        """Required by base class."""
        return {"status": "success"}


class AssistantAgent(CustomAgent):
    """
    Assistant agent - coordinates with other specialists.

    This agent:
    1. Has its own LLM for reasoning
    2. Has peer tools (ask_peer, broadcast) in its toolset
    3. LLM AUTONOMOUSLY decides when to ask other agents
    """
    role = "assistant"
    capabilities = ["chat", "coordination", "search"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your LLM client
        self.tool_calls = []  # Track tool usage

    def get_tools(self) -> list:
        """
        Tools available to THIS agent's LLM.

        IMPORTANT: This includes PEER TOOLS!
        The LLM sees ask_peer, broadcast_update, list_peers
        and decides when to use them.
        """
        # Local tools
        tools = [
            {
                "name": "web_search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        ]

        # ADD PEER TOOLS TO LLM'S TOOLSET
        # This is the key! LLM will see:
        # - ask_peer: Ask another agent for help
        # - broadcast_update: Send message to all peers
        # - list_peers: See available agents
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """
        Execute a tool by name.

        When LLM calls ask_peer, this routes to the peer system.
        """
        self.tool_calls.append({"tool": tool_name, "args": args})

        # PEER TOOLS - route to peer system
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # LOCAL TOOLS
        if tool_name == "web_search":
            return f"Search results for '{args.get('query')}': Found 10 articles."

        return f"Unknown tool: {tool_name}"

    async def chat(self, user_message: str) -> str:
        """
        Complete LLM chat with autonomous tool use.

        The LLM sees all tools (including peer tools) and decides
        which to use. If user asks for analysis, LLM will use
        ask_peer to contact the analyst.
        """
        # System prompt tells LLM about its capabilities
        system_prompt = """You are a helpful assistant.

You have access to these capabilities:
- web_search: Search the web for information
- ask_peer: Ask specialist agents for help (e.g., analyst for data analysis)
- broadcast_update: Send updates to all connected agents
- list_peers: See what other agents are available

When a user needs data analysis, USE ask_peer to ask the analyst.
When a user needs web information, USE web_search.
Be concise in your responses."""

        tools = self.get_tools()
        messages = [{"role": "user", "content": user_message}]

        # Call LLM - it will decide which tools to use
        response = self.llm.chat(messages, tools=tools, system=system_prompt)

        # Handle tool use loop
        while response.get("type") == "tool_use":
            tool_name = response["tool_name"]
            tool_args = response["tool_args"]

            # Execute the tool (might be ask_peer!)
            tool_result = await self.execute_tool(tool_name, tool_args)

            # Continue conversation with tool result
            response = self.llm.continue_with_tool_result(
                messages, response["tool_use_id"], tool_result, tools
            )

        return response.get("content", "")

    async def run(self):
        """Main loop - listen for incoming requests."""
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("query", "")
                    result = await self.chat(query)
                    await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        """Required by base class."""
        return {"status": "success"}
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import AnalystAgent, AssistantAgent


async def main():
    mesh = Mesh(
        mode="p2p",
        config={
            "bind_port": 7950,
            "node_name": "my-agents",
        }
    )

    # Add both agents
    mesh.add(AnalystAgent)
    assistant = mesh.add(AssistantAgent)

    await mesh.start()

    # Start analyst listening in background
    analyst = mesh.get_agent("analyst")
    analyst_task = asyncio.create_task(analyst.run())

    # Give time for setup
    await asyncio.sleep(0.5)

    # User asks a question - LLM will autonomously decide to use ask_peer
    print("User: Please analyze the Q4 sales trends")
    response = await assistant.chat("Please analyze the Q4 sales trends")
    print(f"Assistant: {response}")

    # Check what tools were used
    print(f"\nTools used: {assistant.tool_calls}")
    # Output: [{'tool': 'ask_peer', 'args': {'role': 'analyst', 'question': '...'}}]

    # Cleanup
    analyst.request_shutdown()
    analyst_task.cancel()
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Concepts for P2P Mode

#### Adding Peer Tools to Your LLM

This is the most important pattern. Add peer tools to `get_tools()`:

```python
def get_tools(self) -> list:
    tools = [
        # Your local tools...
    ]

    # ADD PEER TOOLS - LLM will see ask_peer, broadcast, list_peers
    if self.peers:
        tools.extend(self.peers.as_tool().schema)

    return tools
```

#### Routing Tool Execution

Route tool calls to either peer tools or local tools:

```python
async def execute_tool(self, tool_name: str, args: dict) -> str:
    # Check peer tools first
    if self.peers and tool_name in self.peers.as_tool().tool_names:
        return await self.peers.as_tool().execute(tool_name, args)

    # Then local tools
    if tool_name == "my_local_tool":
        return self.my_local_tool(args)

    return f"Unknown tool: {tool_name}"
```

#### System Prompt for Peer Awareness

Tell the LLM about peer capabilities:

```python
system_prompt = """You are a helpful assistant.

You have access to:
- ask_peer: Ask specialist agents for help
- broadcast_update: Send updates to all agents

When a user needs specialized help, USE ask_peer to contact the right agent."""
```

#### The `run()` Loop

Listen for incoming requests and process with LLM:

```python
async def run(self):
    while not self.shutdown_requested:
        if self.peers:
            msg = await self.peers.receive(timeout=0.5)
            if msg and msg.is_request:
                result = await self.process_with_llm(msg.data)
                await self.peers.respond(msg, {"response": result})
        await asyncio.sleep(0.1)
```

---

## ListenerAgent (v0.3.0)

**ListenerAgent** is for developers who want P2P communication without writing the `run()` loop themselves.

### The Problem with CustomAgent for P2P

Every P2P CustomAgent needs this boilerplate:

```python
# BEFORE (CustomAgent) - You write the same loop every time
class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def run(self):
        """You have to write this loop for every P2P agent."""
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    # Handle request
                    result = self.process(msg.data)
                    await self.peers.respond(msg, {"response": result})
                elif msg and msg.is_notify:
                    # Handle notification
                    self.handle_notify(msg.data)
            await asyncio.sleep(0.1)

    async def execute_task(self, task):
        """Still required even though you're using run()."""
        return {"status": "success"}
```

### The Solution: ListenerAgent

```python
# AFTER (ListenerAgent) - Just implement the handlers
from jarviscore.profiles import ListenerAgent

class MyAgent(ListenerAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        """Called when another agent sends a request."""
        return {"result": msg.data.get("task", "").upper()}

    async def on_peer_notify(self, msg):
        """Called when another agent broadcasts a notification."""
        print(f"Notification received: {msg.data}")
```

**What you no longer need:**
- ❌ `run()` loop with `while not self.shutdown_requested`
- ❌ `self.peers.receive()` and `self.peers.respond()` boilerplate
- ❌ `execute_task()` stub method
- ❌ `asyncio.sleep()` timing

**What the framework handles:**
- ✅ Message receiving loop
- ✅ Routing requests to `on_peer_request()`
- ✅ Routing notifications to `on_peer_notify()`
- ✅ Automatic response sending
- ✅ Shutdown handling

### Complete ListenerAgent Example

```python
# agents.py
from jarviscore.profiles import ListenerAgent


class AnalystAgent(ListenerAgent):
    """A data analyst that responds to peer requests."""

    role = "analyst"
    capabilities = ["analysis", "data_interpretation"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()  # Your LLM client

    async def on_peer_request(self, msg):
        """
        Handle incoming requests from other agents.

        Args:
            msg: IncomingMessage with msg.data, msg.sender_role, etc.

        Returns:
            dict: Response sent back to the requesting agent
        """
        query = msg.data.get("question", "")

        # Your analysis logic
        result = self.llm.chat(f"Analyze: {query}")

        return {"response": result, "status": "success"}

    async def on_peer_notify(self, msg):
        """
        Handle broadcast notifications.

        Args:
            msg: IncomingMessage with notification data

        Returns:
            None (notifications don't expect responses)
        """
        print(f"[{self.role}] Received notification: {msg.data}")


class AssistantAgent(ListenerAgent):
    """An assistant that coordinates with specialists."""

    role = "assistant"
    capabilities = ["chat", "coordination"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def on_peer_request(self, msg):
        """Handle incoming chat requests."""
        query = msg.data.get("query", "")

        # Use peer tools to ask specialists
        if self.peers and "data" in query.lower():
            # Ask the analyst for help
            analyst_response = await self.peers.as_tool().execute(
                "ask_peer",
                {"role": "analyst", "question": query}
            )
            return {"response": analyst_response.get("response", "")}

        # Handle directly
        return {"response": self.llm.chat(query)}
```

```python
# main.py
import asyncio
from jarviscore import Mesh
from agents import AnalystAgent, AssistantAgent


async def main():
    mesh = Mesh(mode="p2p", config={"bind_port": 7950})

    mesh.add(AnalystAgent)
    mesh.add(AssistantAgent)

    await mesh.start()

    # Agents automatically run their listeners
    await mesh.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

### When to Use ListenerAgent vs CustomAgent

| Use ListenerAgent when... | Use CustomAgent when... |
|---------------------------|-------------------------|
| You want the simplest P2P agent | You need custom message loop timing |
| Request/response pattern fits your use case | You need to initiate messages proactively |
| You're integrating with FastAPI | You need fine-grained control over the loop |
| You want less boilerplate | You have complex coordination logic |

### ListenerAgent with FastAPI

ListenerAgent shines with FastAPI integration. See [FastAPI Integration](#fastapi-integration-v030) below.

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

## Cognitive Discovery (v0.3.0)

**Cognitive Discovery** lets your LLM dynamically learn about available peers instead of hardcoding agent names in prompts.

### The Problem: Hardcoded Peer Names

Before v0.3.0, you had to hardcode peer information in your system prompts:

```python
# BEFORE: Hardcoded peer names - breaks when peers change
system_prompt = """You are a helpful assistant.

You have access to:
- ask_peer: Ask specialist agents for help
  - Use role="analyst" for data analysis
  - Use role="researcher" for research tasks
  - Use role="writer" for content creation

When a user needs data analysis, USE ask_peer with role="analyst"."""
```

**Problems:**
- If you add a new agent, you must update every prompt
- If an agent is offline, the LLM still tries to call it
- Prompts become stale as your system evolves
- Difficult to manage across many agents

### The Solution: `get_cognitive_context()`

```python
# AFTER: Dynamic peer awareness - always up to date
async def get_system_prompt(self) -> str:
    base_prompt = """You are a helpful assistant.

You have access to peer tools for collaborating with other agents."""

    # Generate LLM-ready peer descriptions dynamically
    if self.peers:
        peer_context = self.peers.get_cognitive_context()
        return f"{base_prompt}\n\n{peer_context}"

    return base_prompt
```

The `get_cognitive_context()` method generates text like:

```
Available Peers:
- analyst (capabilities: analysis, data_interpretation)
  Use ask_peer with role="analyst" for data analysis tasks
- researcher (capabilities: research, web_search)
  Use ask_peer with role="researcher" for research tasks
```

### Complete Example: Dynamic Peer Discovery

```python
# agents.py
from jarviscore.profiles import CustomAgent


class AssistantAgent(CustomAgent):
    """An assistant that dynamically discovers and uses peers."""

    role = "assistant"
    capabilities = ["chat", "coordination"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    def get_system_prompt(self) -> str:
        """Build system prompt with dynamic peer context."""
        base_prompt = """You are a helpful AI assistant.

When users ask questions that require specialized knowledge:
1. Check what peers are available
2. Use ask_peer to get help from the right specialist
3. Synthesize their response for the user"""

        # DYNAMIC: Add current peer information
        if self.peers:
            peer_context = self.peers.get_cognitive_context()
            return f"{base_prompt}\n\n{peer_context}"

        return base_prompt

    def get_tools(self) -> list:
        """Get tools including peer tools."""
        tools = [
            # Your local tools...
        ]

        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def chat(self, user_message: str) -> str:
        """Chat with dynamic peer awareness."""
        # System prompt now includes current peer info
        system = self.get_system_prompt()
        tools = self.get_tools()

        response = self.llm.chat(
            messages=[{"role": "user", "content": user_message}],
            tools=tools,
            system=system
        )

        # Handle tool use...
        return response.get("content", "")
```

### Benefits of Cognitive Discovery

| Before (Hardcoded) | After (Dynamic) |
|--------------------|-----------------|
| Update prompts manually when peers change | Prompts auto-update |
| LLM tries to call offline agents | Only shows available agents |
| Difficult to manage at scale | Scales automatically |
| Stale documentation in prompts | Always current |

---

## FastAPI Integration (v0.3.0)

**JarvisLifespan** reduces FastAPI integration from ~100 lines to 3 lines.

### The Problem: Manual Lifecycle Management

Before v0.3.0, integrating an agent with FastAPI required manual lifecycle management:

```python
# BEFORE: ~100 lines of boilerplate
from contextlib import asynccontextmanager
from fastapi import FastAPI
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent
import asyncio


class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def run(self):
        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    result = self.process(msg.data)
                    await self.peers.respond(msg, {"response": result})
            await asyncio.sleep(0.1)

    async def execute_task(self, task):
        return {"status": "success"}


# Manual lifecycle management
mesh = None
agent = None
run_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mesh, agent, run_task

    # Startup
    mesh = Mesh(mode="p2p", config={"bind_port": 7950})
    agent = mesh.add(MyAgent)
    await mesh.start()
    run_task = asyncio.create_task(agent.run())

    yield

    # Shutdown
    agent.request_shutdown()
    run_task.cancel()
    await mesh.stop()


app = FastAPI(lifespan=lifespan)


@app.post("/process")
async def process(data: dict):
    # Your endpoint logic
    return {"result": "processed"}
```

### The Solution: JarvisLifespan

```python
# AFTER: 3 lines to integrate
from fastapi import FastAPI
from jarviscore.profiles import ListenerAgent
from jarviscore.integrations.fastapi import JarvisLifespan


class ProcessorAgent(ListenerAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data.get("task", "").upper()}


# That's it - 3 lines!
app = FastAPI(lifespan=JarvisLifespan(ProcessorAgent(), mode="p2p"))


@app.post("/process")
async def process(data: dict):
    return {"result": "processed"}
```

### JarvisLifespan Configuration

```python
from jarviscore.integrations.fastapi import JarvisLifespan

# Basic usage
app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p"))

# With configuration
app = FastAPI(
    lifespan=JarvisLifespan(
        agent,
        mode="p2p",              # or "distributed"
        bind_port=7950,          # P2P port
        seed_nodes="ip:port",    # For multi-node
    )
)
```

### Complete FastAPI Example

```python
# app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from jarviscore.profiles import ListenerAgent
from jarviscore.integrations.fastapi import JarvisLifespan


class AnalysisRequest(BaseModel):
    data: str


class AnalystAgent(ListenerAgent):
    """Agent that handles both API requests and P2P messages."""

    role = "analyst"
    capabilities = ["analysis"]

    async def setup(self):
        await super().setup()
        self.llm = MyLLMClient()

    async def on_peer_request(self, msg):
        """Handle requests from other agents in the mesh."""
        query = msg.data.get("question", "")
        result = self.llm.chat(f"Analyze: {query}")
        return {"response": result}

    def analyze(self, data: str) -> dict:
        """Method called by API endpoint."""
        result = self.llm.chat(f"Analyze this data: {data}")
        return {"analysis": result}


# Create agent instance
analyst = AnalystAgent()

# Create FastAPI app with automatic lifecycle management
app = FastAPI(
    title="Analyst Service",
    lifespan=JarvisLifespan(analyst, mode="p2p", bind_port=7950)
)


@app.post("/analyze")
async def analyze(request: AnalysisRequest):
    """API endpoint - also accessible as a peer in the mesh."""
    result = analyst.analyze(request.data)
    return result


@app.get("/peers")
async def list_peers():
    """See what other agents are in the mesh."""
    if analyst.peers:
        return {"peers": analyst.peers.list()}
    return {"peers": []}
```

Run with:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Your agent is now:
- Serving HTTP API on port 8000
- Participating in P2P mesh on port 7950
- Discoverable by other agents
- Automatically handles lifecycle

### Testing the Flow

**Step 1: Start the FastAPI server (Terminal 1)**
```bash
python examples/fastapi_integration_example.py
```

**Step 2: Join a scout agent (Terminal 2)**
```bash
python examples/fastapi_integration_example.py --join-as scout
```

**Step 3: Test with curl (Terminal 3)**
```bash
# Chat with assistant (may delegate to analyst)
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"message": "Analyze Q4 sales trends"}'

# Ask analyst directly
curl -X POST http://localhost:8000/ask/analyst -H "Content-Type: application/json" -d '{"message": "What are key revenue metrics?"}'

# See what each agent knows about peers (cognitive context)
curl http://localhost:8000/agents
```

**Expected flow for `/chat`:**
1. Request goes to **assistant** agent
2. Assistant's LLM sees peers via `get_cognitive_context()`
3. LLM decides to delegate to **analyst** (data analysis request)
4. Assistant uses `ask_peer` tool → P2P message to analyst
5. Analyst processes and responds via P2P
6. Response includes `"delegated_to": "analyst"` and `"peer_data"`

**Example response:**
```json
{
  "message": "Analyze Q4 sales trends",
  "response": "Based on the analyst's findings...",
  "delegated_to": "analyst",
  "peer_data": {"analysis": "...", "confidence": 0.9}
}
```

---

## Cloud Deployment (v0.3.0)

**Self-registration** lets agents join existing meshes without a central orchestrator - perfect for Docker, Kubernetes, and auto-scaling.

### The Problem: Central Orchestrator Required

Before v0.3.0, all agents had to be registered with a central Mesh:

```python
# BEFORE: Central orchestrator pattern
# You needed one "main" node that registered all agents

# main_node.py (central orchestrator)
mesh = Mesh(mode="distributed", config={"bind_port": 7950})
mesh.add(ResearcherAgent)  # Must be on this node
mesh.add(WriterAgent)      # Must be on this node
await mesh.start()
```

**Problems with this approach:**
- Single point of failure
- Can't easily scale agent instances
- Doesn't work well with Kubernetes/Docker
- All agents must be on the same node or manually configured

### The Solution: `join_mesh()` and `leave_mesh()`

```python
# AFTER: Self-registering agents
# Each agent can join any mesh independently

# agent_container.py (runs in Docker/K8s)
from jarviscore.profiles import ListenerAgent
import os


class WorkerAgent(ListenerAgent):
    role = "worker"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": "processed"}


async def main():
    agent = WorkerAgent()
    await agent.setup()

    # Join existing mesh via environment variable
    seed_nodes = os.environ.get("JARVISCORE_SEED_NODES", "mesh-service:7950")
    await agent.join_mesh(seed_nodes=seed_nodes)

    # Agent is now part of the mesh, discoverable by others
    await agent.serve_forever()

    # Clean shutdown
    await agent.leave_mesh()
```

### Environment Variables for Cloud

| Variable | Description | Example |
|----------|-------------|---------|
| `JARVISCORE_SEED_NODES` | Comma-separated list of mesh nodes | `"10.0.0.1:7950,10.0.0.2:7950"` |
| `JARVISCORE_MESH_ENDPOINT` | This agent's reachable address | `"worker-pod-abc:7950"` |
| `JARVISCORE_BIND_PORT` | Port to listen on | `"7950"` |

### Docker Deployment Example

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "agent.py"]
```

```python
# agent.py
import asyncio
import os
from jarviscore.profiles import ListenerAgent


class WorkerAgent(ListenerAgent):
    role = "worker"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        task = msg.data.get("task", "")
        return {"result": f"Processed: {task}"}


async def main():
    agent = WorkerAgent()
    await agent.setup()

    # Configuration from environment
    seed_nodes = os.environ.get("JARVISCORE_SEED_NODES")
    mesh_endpoint = os.environ.get("JARVISCORE_MESH_ENDPOINT")

    if seed_nodes:
        await agent.join_mesh(
            seed_nodes=seed_nodes,
            advertise_endpoint=mesh_endpoint
        )
        print(f"Joined mesh via {seed_nodes}")
    else:
        print("Running standalone (no JARVISCORE_SEED_NODES)")

    await agent.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  mesh-seed:
    build: .
    environment:
      - JARVISCORE_BIND_PORT=7950
    ports:
      - "7950:7950"

  worker-1:
    build: .
    environment:
      - JARVISCORE_SEED_NODES=mesh-seed:7950
      - JARVISCORE_MESH_ENDPOINT=worker-1:7950
    depends_on:
      - mesh-seed

  worker-2:
    build: .
    environment:
      - JARVISCORE_SEED_NODES=mesh-seed:7950
      - JARVISCORE_MESH_ENDPOINT=worker-2:7950
    depends_on:
      - mesh-seed
```

### Kubernetes Deployment Example

```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jarvis-worker
spec:
  replicas: 3  # Scale as needed
  selector:
    matchLabels:
      app: jarvis-worker
  template:
    metadata:
      labels:
        app: jarvis-worker
    spec:
      containers:
      - name: worker
        image: myregistry/jarvis-worker:latest
        env:
        - name: JARVISCORE_SEED_NODES
          value: "jarvis-mesh-service:7950"
        - name: JARVISCORE_MESH_ENDPOINT
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        ports:
        - containerPort: 7950
---
apiVersion: v1
kind: Service
metadata:
  name: jarvis-mesh-service
spec:
  selector:
    app: jarvis-mesh-seed
  ports:
  - port: 7950
    targetPort: 7950
```

### How Self-Registration Works

```
┌─────────────────────────────────────────────────────────────┐
│                    SELF-REGISTRATION FLOW                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. New container starts                                    │
│     │                                                       │
│     ▼                                                       │
│  2. agent.join_mesh(seed_nodes="mesh:7950")                │
│     │                                                       │
│     ▼                                                       │
│  3. Agent connects to seed node                            │
│     │                                                       │
│     ▼                                                       │
│  4. SWIM protocol discovers all peers                      │
│     │                                                       │
│     ▼                                                       │
│  5. Agent registers its role/capabilities                  │
│     │                                                       │
│     ▼                                                       │
│  6. Other agents can now discover and call this agent      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### RemoteAgentProxy (Automatic)

When agents join from different nodes, the framework automatically creates `RemoteAgentProxy` objects. You don't need to do anything special - the mesh handles it:

```python
# On any node, you can discover and call remote agents
if agent.peers:
    # This works whether the peer is local or remote
    response = await agent.peers.as_tool().execute(
        "ask_peer",
        {"role": "worker", "question": "Process this data"}
    )
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
| `join_mesh(seed_nodes, ...)` | Both | **(v0.3.0)** Self-register with an existing mesh |
| `leave_mesh()` | Both | **(v0.3.0)** Gracefully leave the mesh |
| `serve_forever()` | Both | **(v0.3.0)** Block until shutdown signal |

### ListenerAgent Class (v0.3.0)

ListenerAgent extends CustomAgent with handler-based P2P communication.

| Attribute/Method | Type | Description |
|------------------|------|-------------|
| `role` | `str` | Required. Unique identifier for this agent type |
| `capabilities` | `list[str]` | Required. List of capabilities for discovery |
| `on_peer_request(msg)` | async method | Handle incoming requests. Return dict to respond |
| `on_peer_notify(msg)` | async method | Handle broadcast notifications. No return needed |

**Note:** ListenerAgent does not require `run()` or `execute_task()` implementations.

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

### PeerClient Methods (v0.3.0)

Access via `self.peers`:

| Method | Returns | Description |
|--------|---------|-------------|
| `get_cognitive_context()` | `str` | Generate LLM-ready text describing available peers |
| `list()` | `list[PeerInfo]` | Get list of connected peers |
| `as_tool()` | `PeerTool` | Get peer tools for LLM tool use |
| `receive(timeout)` | `IncomingMessage` | Receive next message (for CustomAgent run loops) |
| `respond(msg, data)` | `None` | Respond to a request message |

### JarvisLifespan (v0.3.0)

FastAPI integration helper:

```python
from jarviscore.integrations.fastapi import JarvisLifespan

JarvisLifespan(
    agent,                      # Agent instance
    mode="p2p",                 # "p2p" or "distributed"
    bind_port=7950,             # Optional: P2P port
    seed_nodes="ip:port",       # Optional: for multi-node
)
```

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

- `examples/customagent_p2p_example.py` - P2P mode with LLM-driven peer communication
- `examples/customagent_distributed_example.py` - Distributed mode with workflows
- `examples/listeneragent_cognitive_discovery_example.py` - ListenerAgent + cognitive discovery (v0.3.0)
- `examples/fastapi_integration_example.py` - FastAPI + JarvisLifespan (v0.3.0)
- `examples/cloud_deployment_example.py` - Self-registration with join_mesh (v0.3.0)

---

*CustomAgent Guide - JarvisCore Framework v0.3.0*
