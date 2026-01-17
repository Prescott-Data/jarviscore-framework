"""
Custom Profile Example: Using wrap() Function

This example shows how to use the wrap() function to convert
an existing instance into a JarvisCore agent.

Use Case: You have an already-instantiated object (like a LangChain
agent, CrewAI agent, or any configured instance) and want to use it
with JarvisCore orchestration.
"""
import asyncio
from jarviscore import Mesh, wrap, JarvisContext


# Simulate an existing "LangChain-like" agent
class ExternalLLMAgent:
    """
    Simulates an external LLM agent (like LangChain).
    In real usage, this would be your actual LangChain/CrewAI agent.
    """

    def __init__(self, model_name: str, temperature: float = 0.7):
        self.model_name = model_name
        self.temperature = temperature
        print(f"  Initialized ExternalLLMAgent with {model_name}")

    def invoke(self, query: str) -> dict:
        """LangChain-style invoke method."""
        # Simulate LLM response
        return {
            "answer": f"Response to '{query}' from {self.model_name}",
            "model": self.model_name,
            "tokens_used": len(query.split()) * 10
        }


# Simulate a data processing service
class DataService:
    """Simulates an external data processing service."""

    def __init__(self, api_url: str):
        self.api_url = api_url
        print(f"  Initialized DataService with {api_url}")

    def run(self, data):
        """Process data through the service."""
        if isinstance(data, list):
            return {
                "transformed": [x ** 2 for x in data],
                "source": self.api_url
            }
        return {"transformed": data ** 2, "source": self.api_url}


# Simulate an agent that needs context
class ContextAwareProcessor:
    """Agent that uses JarvisContext to access previous results."""

    def run(self, task, ctx: JarvisContext):
        """Process with context access."""
        # Get all previous results
        all_previous = ctx.all_previous()

        summary = {
            "task": task,
            "previous_steps": list(all_previous.keys()),
            "combined_data": {}
        }

        for step_id, output in all_previous.items():
            if isinstance(output, dict):
                summary["combined_data"][step_id] = output

        return summary


async def main():
    """Demonstrate wrapping existing instances."""
    print("=" * 60)
    print("  Custom Profile Example: wrap() Function")
    print("=" * 60)

    # Create instances of "external" agents
    print("\nCreating external agent instances...")
    llm_agent = ExternalLLMAgent(model_name="gpt-4-turbo", temperature=0.3)
    data_service = DataService(api_url="https://api.example.com/process")
    context_processor = ContextAwareProcessor()

    # Wrap them for JarvisCore
    print("\nWrapping instances for JarvisCore...")

    wrapped_llm = wrap(
        llm_agent,
        role="llm_assistant",
        capabilities=["chat", "qa"],
        execute_method="invoke"  # LangChain uses "invoke"
    )

    wrapped_data = wrap(
        data_service,
        role="data_processor",
        capabilities=["data_processing", "transformation"]
        # execute_method auto-detected as "run"
    )

    wrapped_context = wrap(
        context_processor,
        role="context_aggregator",
        capabilities=["aggregation", "summary"]
    )

    # Create mesh and add wrapped agents
    mesh = Mesh(mode="autonomous")
    mesh.add(wrapped_llm)
    mesh.add(wrapped_data)
    mesh.add(wrapped_context)

    await mesh.start()

    try:
        print("\nExecuting workflow with wrapped agents...\n")

        results = await mesh.workflow("wrap-demo", [
            {
                "id": "llm_step",
                "agent": "llm_assistant",
                "task": "What is the capital of France?",
                "params": {"query": "What is the capital of France?"}
            },
            {
                "id": "data_step",
                "agent": "data_processor",
                "task": "Transform numbers",
                "params": {"data": [1, 2, 3, 4, 5]}
            },
            {
                "id": "summary_step",
                "agent": "context_aggregator",
                "task": "Summarize all results",
                "depends_on": ["llm_step", "data_step"]
            }
        ])

        # Print results
        print("Results:")
        print("-" * 40)

        step_names = ["LLM Assistant", "Data Processor", "Context Aggregator"]
        for i, result in enumerate(results):
            print(f"\n{step_names[i]}:")
            print(f"  Status: {result.get('status')}")
            output = result.get('output', {})
            if isinstance(output, dict):
                for key, value in output.items():
                    print(f"  {key}: {value}")
            else:
                print(f"  Output: {output}")

        print("\n" + "=" * 60)
        print("  Workflow with wrapped instances completed!")
        print("=" * 60)

    finally:
        await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
