"""
Test 2: Standalone Assistant

The Assistant agent working alone - no framework.
Has local tools (search, calculate) but cannot talk to other agents.
"""


class Assistant:
    """
    Standalone Assistant agent.

    Capabilities:
    - Search the web
    - Calculate expressions
    - Chat with user

    Tools available to LLM:
    - search
    - calculate
    """

    def __init__(self):
        self.name = "assistant"

    def search(self, query: str) -> str:
        """Search the web for information."""
        # Simulated search
        return f"Search results for '{query}': Found 10 relevant articles."

    def calculate(self, expression: str) -> str:
        """Calculate a math expression."""
        try:
            result = eval(expression)
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {e}"

    def get_tools(self) -> list:
        """Return tool definitions for LLM."""
        return [
            {
                "name": "search",
                "description": "Search the web for information",
                "parameters": {"query": "string"}
            },
            {
                "name": "calculate",
                "description": "Calculate a math expression",
                "parameters": {"expression": "string"}
            }
        ]

    def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool by name."""
        if tool_name == "search":
            return self.search(args.get("query", ""))
        elif tool_name == "calculate":
            return self.calculate(args.get("expression", ""))
        else:
            return f"Unknown tool: {tool_name}"

    def chat(self, message: str) -> str:
        """Simple chat response."""
        return f"I received: {message}"


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_assistant_init():
    """Assistant initializes correctly."""
    assistant = Assistant()
    assert assistant.name == "assistant"
    print("✓ Assistant initialized")


def test_assistant_search():
    """Assistant can search."""
    assistant = Assistant()
    result = assistant.search("market trends 2024")

    assert "Search results" in result
    assert "market trends" in result
    print(f"✓ Search: {result}")


def test_assistant_calculate():
    """Assistant can calculate."""
    assistant = Assistant()

    result1 = assistant.calculate("2 + 2")
    assert "4" in result1
    print(f"✓ Calculate 2+2: {result1}")

    result2 = assistant.calculate("100 * 0.15")
    assert "15" in result2
    print(f"✓ Calculate 100*0.15: {result2}")


def test_assistant_get_tools():
    """Assistant returns tool definitions."""
    assistant = Assistant()
    tools = assistant.get_tools()
    tool_names = [t["name"] for t in tools]

    assert "search" in tool_names
    assert "calculate" in tool_names
    assert len(tools) == 2
    print(f"✓ Tools: {tool_names}")


def test_assistant_execute_tool():
    """Assistant can execute tools by name."""
    assistant = Assistant()

    result = assistant.execute_tool("search", {"query": "python tutorials"})
    assert "python tutorials" in result
    print(f"✓ Execute search: {result}")

    result = assistant.execute_tool("calculate", {"expression": "10 / 2"})
    assert "5" in result
    print(f"✓ Execute calculate: {result}")


def test_assistant_cannot_talk_to_peers():
    """Assistant has NO way to talk to other agents."""
    assistant = Assistant()
    tools = assistant.get_tools()
    tool_names = [t["name"] for t in tools]

    # No peer communication tools
    assert "ask_peer" not in tool_names
    assert "broadcast_update" not in tool_names
    assert "list_peers" not in tool_names

    # No peers attribute
    assert not hasattr(assistant, 'peers')

    print("✓ Assistant CANNOT talk to peers (limitation)")
    print(f"  Available tools: {tool_names}")
    print(f"  Missing: ask_peer, broadcast_update, list_peers")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 2: STANDALONE ASSISTANT")
    print("="*60 + "\n")

    test_assistant_init()
    test_assistant_search()
    test_assistant_calculate()
    test_assistant_get_tools()
    test_assistant_execute_tool()
    test_assistant_cannot_talk_to_peers()

    print("\n" + "-"*60)
    print("Assistant works, but cannot talk to other agents.")
    print("-"*60 + "\n")
