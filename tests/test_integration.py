"""
Integration tests demonstrating full framework usage.
"""
import pytest
from jarviscore import Mesh, AutoAgent, CustomAgent


# Example agents for integration testing
class ScraperAgent(CustomAgent):
    """Web scraper agent using CustomAgent profile (mocked for testing)."""
    role = "scraper"
    capabilities = ["web_scraping", "data_extraction"]

    async def execute_task(self, task):
        # Mock scraper for integration testing
        return {
            "status": "success",
            "output": {
                "url": "example.com",
                "products": ["Product A", "Product B", "Product C"]
            },
            "tokens_used": 0,
            "cost_usd": 0.0
        }


class ProcessorAgent(CustomAgent):
    """Data processor using CustomAgent profile."""
    role = "processor"
    capabilities = ["data_processing", "transformation"]

    async def execute_task(self, task):
        # Simulate data processing
        data = task.get("params", {}).get("data", [])
        processed = [x.upper() if isinstance(x, str) else x * 2 for x in data]

        return {
            "status": "success",
            "output": processed,
            "tokens_used": 0,  # No LLM usage
            "cost_usd": 0.0
        }


class StorageAgent(CustomAgent):
    """Storage agent for saving results."""
    role = "storage"
    capabilities = ["database", "file_storage"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stored_data = []  # Mock storage

    async def execute_task(self, task):
        data = task.get("params", {}).get("data")
        self.stored_data.append(data)

        return {
            "status": "success",
            "output": f"Stored {len(self.stored_data)} record(s)",
            "records_stored": len(self.stored_data)
        }


class TestBasicIntegration:
    """Test basic framework integration."""

    @pytest.mark.asyncio
    async def test_single_agent_workflow(self):
        """Test workflow with single agent."""
        mesh = Mesh(mode="autonomous")
        mesh.add(ScraperAgent)

        await mesh.start()

        results = await mesh.workflow("simple-scrape", [
            {
                "agent": "scraper",
                "task": "Scrape example.com for product data"
            }
        ])

        assert len(results) == 1
        assert results[0]["status"] == "success"

        await mesh.stop()

    @pytest.mark.asyncio
    async def test_multi_agent_workflow(self):
        """Test workflow with multiple agents."""
        mesh = Mesh(mode="autonomous")
        mesh.add(ScraperAgent)
        mesh.add(ProcessorAgent)
        mesh.add(StorageAgent)

        await mesh.start()

        results = await mesh.workflow("scrape-process-store", [
            {
                "agent": "scraper",
                "task": "Scrape example.com"
            },
            {
                "agent": "processor",
                "task": "Process scraped data",
                "params": {"data": ["hello", "world"]}
            },
            {
                "agent": "storage",
                "task": "Save processed data",
                "params": {"data": ["HELLO", "WORLD"]}
            }
        ])

        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)

        await mesh.stop()


class TestMixedProfileIntegration:
    """Test integration of AutoAgent and CustomAgent profiles."""

    @pytest.mark.asyncio
    async def test_auto_and_custom_agents_together(self):
        """Test that AutoAgent and CustomAgent work together."""
        mesh = Mesh(mode="autonomous")

        # Add AutoAgent
        scraper = mesh.add(ScraperAgent)

        # Add CustomAgent
        processor = mesh.add(ProcessorAgent)

        await mesh.start()

        # Verify both agents are registered
        assert mesh.get_agent("scraper") == scraper
        assert mesh.get_agent("processor") == processor

        # Execute workflow using both
        results = await mesh.workflow("mixed-workflow", [
            {"agent": "scraper", "task": "Scrape data"},
            {"agent": "processor", "task": "Process", "params": {"data": [1, 2, 3]}}
        ])

        assert len(results) == 2
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "success"

        await mesh.stop()


class TestCapabilityRouting:
    """Test task routing by capabilities."""

    @pytest.mark.asyncio
    async def test_route_by_capability(self):
        """Test that tasks are routed by capability."""
        mesh = Mesh(mode="autonomous")
        mesh.add(ProcessorAgent)

        await mesh.start()

        # Route by capability instead of role
        results = await mesh.workflow("capability-routing", [
            {
                "agent": "data_processing",  # Capability, not role
                "task": "Process this data",
                "params": {"data": [10, 20, 30]}
            }
        ])

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["output"] == [20, 40, 60]  # Doubled

        await mesh.stop()


class TestAgentStateAndCustomization:
    """Test agent state management and customization."""

    @pytest.mark.asyncio
    async def test_agent_maintains_state_across_tasks(self):
        """Test that CustomAgent can maintain state across multiple tasks."""
        mesh = Mesh(mode="autonomous")
        storage = mesh.add(StorageAgent)

        await mesh.start()

        # Execute multiple storage tasks
        await mesh.workflow("multi-store", [
            {"agent": "storage", "task": "Store item 1", "params": {"data": "item1"}},
            {"agent": "storage", "task": "Store item 2", "params": {"data": "item2"}},
            {"agent": "storage", "task": "Store item 3", "params": {"data": "item3"}},
        ])

        # Verify storage agent maintained state
        assert len(storage.stored_data) == 3
        assert storage.stored_data == ["item1", "item2", "item3"]

        await mesh.stop()


class TestErrorHandling:
    """Test error handling in workflows."""

    @pytest.mark.asyncio
    async def test_missing_agent_error(self):
        """Test workflow with missing agent."""
        mesh = Mesh(mode="autonomous")
        mesh.add(ProcessorAgent)

        await mesh.start()

        results = await mesh.workflow("missing-agent", [
            {
                "agent": "nonexistent_agent",
                "task": "Should fail"
            }
        ])

        assert len(results) == 1
        assert results[0]["status"] == "failure"
        assert "No agent found" in results[0]["error"]

        await mesh.stop()


class TestRealWorldScenario:
    """Test real-world usage scenarios."""

    @pytest.mark.asyncio
    async def test_data_pipeline_scenario(self):
        """Test complete data pipeline: scrape → process → store."""
        mesh = Mesh(mode="autonomous")
        mesh.add(ScraperAgent)
        mesh.add(ProcessorAgent)
        storage = mesh.add(StorageAgent)

        await mesh.start()

        # Simulate data pipeline
        results = await mesh.workflow("data-pipeline", [
            {
                "agent": "scraper",
                "task": "Scrape example.com for products"
            },
            {
                "agent": "processor",
                "task": "Clean and normalize product data",
                "params": {"data": ["product-a", "product-b", "product-c"]},
                "depends_on": [0]
            },
            {
                "agent": "storage",
                "task": "Save to database",
                "params": {"data": ["PRODUCT-A", "PRODUCT-B", "PRODUCT-C"]},
                "depends_on": [1]
            }
        ])

        # Verify all steps succeeded
        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)

        # Verify data was stored
        assert len(storage.stored_data) == 1
        assert storage.stored_data[0] == ["PRODUCT-A", "PRODUCT-B", "PRODUCT-C"]

        await mesh.stop()

    @pytest.mark.asyncio
    async def test_agent_discovery_by_capability(self):
        """Test that mesh can discover agents by capability."""
        mesh = Mesh(mode="autonomous")
        mesh.add(ScraperAgent)
        mesh.add(ProcessorAgent)
        mesh.add(StorageAgent)

        # Test capability indexing
        scrapers = mesh.get_agents_by_capability("web_scraping")
        assert len(scrapers) == 1
        assert scrapers[0].role == "scraper"

        processors = mesh.get_agents_by_capability("data_processing")
        assert len(processors) == 1
        assert processors[0].role == "processor"

        storage_agents = mesh.get_agents_by_capability("database")
        assert len(storage_agents) == 1
        assert storage_agents[0].role == "storage"
