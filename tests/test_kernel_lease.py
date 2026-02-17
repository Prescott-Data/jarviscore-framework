"""
Tests for 6A: ExecutionLease + Role Profiles.

What these tests prove:
- Lease defaults match kernel settings
- Role profiles create correctly configured leases
- Token consumption tracks correctly per phase
- Expiration detects all budget dimensions (tokens, turns, wall clock)
- Summary provides accurate state snapshot
- Invalid role raises KeyError
"""

import time

import pytest

from jarviscore.kernel.lease import ExecutionLease, ROLE_LEASE_PROFILES


class TestExecutionLeaseDefaults:
    """Lease creation with default values."""

    def test_default_values(self):
        lease = ExecutionLease()
        assert lease.max_total_tokens == 80_000
        assert lease.thinking_budget == 56_000
        assert lease.action_budget == 24_000
        assert lease.wall_clock_ms == 180_000
        assert lease.emergency_turn_fuse == 30
        assert lease.model_tier == "task"
        assert lease.thinking_used == 0
        assert lease.action_used == 0
        assert lease.turns_used == 0

    def test_not_expired_on_creation(self):
        lease = ExecutionLease()
        assert not lease.is_expired()

    def test_remaining_budgets_full(self):
        lease = ExecutionLease()
        assert lease.remaining_thinking() == 56_000
        assert lease.remaining_action() == 24_000
        assert lease.remaining_total() == 80_000


class TestExecutionLeaseRoleProfiles:
    """Role-based lease creation."""

    def test_coder_profile(self):
        lease = ExecutionLease.for_role("coder")
        assert lease.thinking_budget == 132_000
        assert lease.action_budget == 108_000
        assert lease.max_total_tokens == 240_000
        assert lease.wall_clock_ms == 240_000
        assert lease.emergency_turn_fuse == 24
        assert lease.model_tier == "coding"

    def test_researcher_profile(self):
        lease = ExecutionLease.for_role("researcher")
        assert lease.thinking_budget == 180_000
        assert lease.action_budget == 60_000
        assert lease.model_tier == "task"

    def test_communicator_profile(self):
        lease = ExecutionLease.for_role("communicator")
        assert lease.thinking_budget == 72_000
        assert lease.action_budget == 48_000
        assert lease.max_total_tokens == 120_000
        assert lease.wall_clock_ms == 120_000
        assert lease.emergency_turn_fuse == 14

    def test_unknown_role_raises(self):
        with pytest.raises(KeyError, match="Unknown role"):
            ExecutionLease.for_role("nonexistent")

    def test_profiles_not_mutated(self):
        """Creating a lease from a profile doesn't mutate the profile dict."""
        original = ROLE_LEASE_PROFILES["coder"].copy()
        lease = ExecutionLease.for_role("coder")
        lease.consume(1000, "thinking")
        assert ROLE_LEASE_PROFILES["coder"] == original


class TestExecutionLeaseConsumption:
    """Token consumption and budget tracking."""

    def test_consume_thinking(self):
        lease = ExecutionLease()
        lease.consume(1500, "thinking")
        assert lease.thinking_used == 1500
        assert lease.action_used == 0
        assert lease.remaining_thinking() == 56_000 - 1500

    def test_consume_action(self):
        lease = ExecutionLease()
        lease.consume(2000, "action")
        assert lease.action_used == 2000
        assert lease.thinking_used == 0
        assert lease.remaining_action() == 24_000 - 2000

    def test_consume_invalid_phase(self):
        lease = ExecutionLease()
        with pytest.raises(ValueError, match="Unknown phase"):
            lease.consume(100, "invalid")

    def test_consume_turn(self):
        lease = ExecutionLease()
        lease.consume_turn()
        lease.consume_turn()
        assert lease.turns_used == 2

    def test_remaining_total_tracks_both(self):
        lease = ExecutionLease()
        lease.consume(10_000, "thinking")
        lease.consume(5_000, "action")
        assert lease.remaining_total() == 80_000 - 15_000

    def test_remaining_floors_at_zero(self):
        lease = ExecutionLease(thinking_budget=100)
        lease.consume(200, "thinking")
        assert lease.remaining_thinking() == 0


class TestExecutionLeaseExpiry:
    """Expiration detection across all budget dimensions."""

    def test_thinking_budget_exhausted(self):
        lease = ExecutionLease(thinking_budget=1000)
        lease.consume(1000, "thinking")
        assert lease.is_expired()

    def test_action_budget_exhausted(self):
        lease = ExecutionLease(action_budget=500)
        lease.consume(500, "action")
        assert lease.is_expired()

    def test_total_tokens_exhausted(self):
        lease = ExecutionLease(max_total_tokens=2000)
        lease.consume(1200, "thinking")
        lease.consume(800, "action")
        assert lease.is_expired()

    def test_turn_fuse_exhausted(self):
        lease = ExecutionLease(emergency_turn_fuse=3)
        for _ in range(3):
            lease.consume_turn()
        assert lease.is_expired()

    def test_wall_clock_expired(self):
        lease = ExecutionLease(wall_clock_ms=0)
        # With 0ms budget, it's immediately expired
        assert lease.is_expired()

    def test_not_expired_just_under_limit(self):
        lease = ExecutionLease(thinking_budget=1000)
        lease.consume(999, "thinking")
        assert not lease.is_expired()


class TestExecutionLeaseSummary:
    """Summary output for prompt injection."""

    def test_summary_shape(self):
        lease = ExecutionLease.for_role("coder")
        lease.consume(5000, "thinking")
        lease.consume(2000, "action")
        lease.consume_turn()

        s = lease.summary()
        assert s["thinking"]["used"] == 5000
        assert s["thinking"]["budget"] == 132_000
        assert s["action"]["used"] == 2000
        assert s["total"]["used"] == 7000
        assert s["turns"]["used"] == 1
        assert s["turns"]["fuse"] == 24
        assert s["model_tier"] == "coding"
        assert s["expired"] is False

    def test_summary_expired_flag(self):
        lease = ExecutionLease(thinking_budget=100)
        lease.consume(100, "thinking")
        assert lease.summary()["expired"] is True
