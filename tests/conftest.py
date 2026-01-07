"""
Pytest configuration and fixtures for JarvisCore tests.
"""
import pytest
import logging


@pytest.fixture(autouse=True)
def setup_logging():
    """Setup logging for tests."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


@pytest.fixture
def sample_task():
    """Sample task for testing."""
    return {
        "task": "Test task description",
        "params": {"key": "value"}
    }


@pytest.fixture
def sample_workflow():
    """Sample workflow for testing."""
    return [
        {
            "agent": "agent1",
            "task": "Step 1: Process data"
        },
        {
            "agent": "agent2",
            "task": "Step 2: Transform results",
            "depends_on": [0]
        },
        {
            "agent": "agent3",
            "task": "Step 3: Save to storage",
            "depends_on": [1]
        }
    ]
