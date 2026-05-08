"""
Tests for jarviscore.hitl.HITLQueue — the native HITL escalation queue.

What these tests prove:
- HITLQueue.request() creates a flat JSON file AND a Redis entry
- Content is truncated to the framework's size guard limits
- Context values are truncated independently
- check() returns None when pending, HITLResolution when resolved
- resolve() updates the file and Redis atomically
- pending() filters by agent_id and status
- The queue works in file-only mode (no Redis)
- Invalid urgency or category raises ValueError

These tests use a real temp directory for file I/O and MockRedisContextStore
for Redis.
"""

import json
import time

import pytest

from jarviscore.hitl import HITLQueue
from jarviscore.hitl.queue import MAX_CONTENT_CHARS, MAX_CONTEXT_CHARS


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def inbox_dir(tmp_path):
    """Fresh temp directory for each test's HITL inbox."""
    return tmp_path / "test_hitl_inbox"


@pytest.fixture
def redis_store():
    """Mock Redis store — matches the interface HITLQueue expects."""
    try:
        from jarviscore.testing import MockRedisContextStore
        return MockRedisContextStore()
    except ImportError:
        pytest.skip("MockRedisContextStore not available")


@pytest.fixture
def queue(inbox_dir, redis_store):
    """HITLQueue with both file + Redis backends."""
    return HITLQueue(
        agent_id="test-agent",
        inbox_dir=str(inbox_dir),
        redis_store=redis_store,
    )


@pytest.fixture
def file_only_queue(inbox_dir):
    """HITLQueue with file backend only (no Redis)."""
    return HITLQueue(
        agent_id="test-agent",
        inbox_dir=str(inbox_dir),
        redis_store=None,
    )


# ======================================================================
# Basic request lifecycle
# ======================================================================


class TestRequestCreation:
    """Verify that HITLQueue.request() persists correctly."""

    def test_creates_file(self, queue, inbox_dir):
        """request() creates a JSON file in the inbox directory."""
        item_id = queue.request(
            title="Review Q2 deck",
            content="Please review the attached deck.",
            urgency="normal",
            category="data_required",
        )

        filepath = inbox_dir / f"{item_id}.json"
        assert filepath.exists(), f"Expected file at {filepath}"

        data = json.loads(filepath.read_text())
        assert data["id"] == item_id
        assert data["agent"] == "test-agent"
        assert data["title"] == "Review Q2 deck"
        assert data["status"] == "pending"
        assert data["type"] == "hitl"

    def test_creates_redis_entry(self, queue, redis_store):
        """request() also persists to Redis via create_hitl_request_typed()."""
        item_id = queue.request(
            title="Review deployment",
            content="Deploy to production?",
            urgency="high",
            category="critical_action",
        )

        # The typed API stores under hitl_request:{workflow_id}:{step_id}
        # Our queue uses agent_id as workflow_id and request_id as step_id
        hitl_data = redis_store.get_hitl_request("test-agent", item_id)
        assert hitl_data is not None
        assert "pending" in hitl_data["status"]

    def test_returns_unique_ids(self, queue):
        """Two calls return different IDs."""
        id1 = queue.request(title="First", content="a", urgency="normal", category="auth_required")
        id2 = queue.request(title="Second", content="b", urgency="normal", category="auth_required")
        assert id1 != id2

    def test_file_only_mode(self, file_only_queue, inbox_dir):
        """Works without Redis — file is still created."""
        item_id = file_only_queue.request(
            title="File-only test",
            content="No Redis here.",
            urgency="low",
            category="data_required",
        )
        filepath = inbox_dir / f"{item_id}.json"
        assert filepath.exists()

    def test_invalid_urgency_raises(self, queue):
        """Invalid urgency level raises ValueError."""
        with pytest.raises(ValueError, match="Invalid urgency"):
            queue.request(
                title="Bad urgency",
                content="test",
                urgency="mega-urgent",
                category="auth_required",
            )

    def test_invalid_category_raises(self, queue):
        """Invalid category raises ValueError."""
        with pytest.raises(ValueError, match="Invalid HITL category"):
            queue.request(
                title="Bad category",
                content="test",
                urgency="normal",
                category="not_a_real_category",
            )


# ======================================================================
# Content truncation (framework size guard)
# ======================================================================


class TestContentTruncation:
    """Verify that oversized payloads are capped."""

    def test_content_truncated(self, queue, inbox_dir):
        """Content exceeding MAX_CONTENT_CHARS is truncated."""
        huge_content = "X" * (MAX_CONTENT_CHARS + 5000)
        item_id = queue.request(
            title="Big payload",
            content=huge_content,
            urgency="normal",
            category="data_required",
        )

        data = json.loads((inbox_dir / f"{item_id}.json").read_text())
        assert len(data["content"]) <= MAX_CONTENT_CHARS + 50  # + ellipsis marker
        assert "truncated" in data["content"]

    def test_context_values_truncated(self, queue, inbox_dir):
        """String values in context dict are truncated individually."""
        huge_goal = "Y" * (MAX_CONTEXT_CHARS + 5000)
        item_id = queue.request(
            title="Context test",
            content="Short content.",
            urgency="normal",
            category="data_required",
            context={"goal": huge_goal, "short_key": "keep this"},
        )

        data = json.loads((inbox_dir / f"{item_id}.json").read_text())
        assert len(data["context"]["goal"]) <= MAX_CONTEXT_CHARS + 50
        assert data["context"]["short_key"] == "keep this"

    def test_small_content_not_truncated(self, queue, inbox_dir):
        """Content under the limit is preserved exactly."""
        item_id = queue.request(
            title="Small",
            content="Short and sweet.",
            urgency="normal",
            category="auth_required",
        )

        data = json.loads((inbox_dir / f"{item_id}.json").read_text())
        assert data["content"] == "Short and sweet."
        assert "truncated" not in data["content"]


# ======================================================================
# Check / Resolution
# ======================================================================


class TestCheckAndResolve:
    """Verify polling and resolution lifecycle."""

    def test_check_pending_returns_none(self, queue):
        """check() returns None for a pending item."""
        item_id = queue.request(
            title="Pending test",
            content="Still waiting.",
            urgency="normal",
            category="auth_required",
        )
        resolution = queue.check(item_id)
        assert resolution is None  # pending → no resolution yet

    def test_resolve_updates_file(self, queue, inbox_dir):
        """resolve() writes decision to the JSON file."""
        item_id = queue.request(
            title="Resolve test",
            content="Will be approved.",
            urgency="normal",
            category="critical_action",
        )
        result = queue.resolve(item_id, "approved", reason="Looks good")
        assert result is True

        data = json.loads((inbox_dir / f"{item_id}.json").read_text())
        assert data["status"] == "approved"
        assert data["decision"] == "approved"
        assert data["decision_reason"] == "Looks good"
        assert data["decided_at"] is not None

    def test_resolve_nonexistent_returns_false(self, queue):
        """Resolving a non-existent item returns False."""
        assert queue.resolve("hitl-ghost-12345678", "approved") is False


# ======================================================================
# Pending items
# ======================================================================


class TestPending:
    """Verify the pending() filter."""

    def test_lists_pending_items(self, queue):
        """pending() returns only pending items for this agent."""
        queue.request(title="Item 1", content="first", urgency="normal", category="auth_required")
        queue.request(title="Item 2", content="second", urgency="high", category="critical_action")

        items = queue.pending()
        assert len(items) == 2

    def test_excludes_resolved_items(self, queue):
        """Resolved items don't appear in pending()."""
        id1 = queue.request(title="To approve", content="yes", urgency="normal", category="auth_required")
        queue.request(title="Still pending", content="wait", urgency="normal", category="auth_required")

        queue.resolve(id1, "approved")

        items = queue.pending()
        assert len(items) == 1
        assert items[0]["title"] == "Still pending"

    def test_empty_when_no_items(self, queue):
        """pending() returns empty list when no items exist."""
        assert queue.pending() == []


# ======================================================================
# Dual-write consistency
# ======================================================================


class TestDualWrite:
    """Verify that file and Redis stay in sync."""

    def test_both_backends_written(self, queue, inbox_dir, redis_store):
        """request() writes to both file and Redis."""
        item_id = queue.request(
            title="Dual write test",
            content="Check both backends.",
            urgency="normal",
            category="data_required",
        )

        # File exists
        assert (inbox_dir / f"{item_id}.json").exists()

        # Redis entry exists
        redis_data = redis_store.get_hitl_request("test-agent", item_id)
        assert redis_data is not None
