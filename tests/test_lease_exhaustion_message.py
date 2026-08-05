"""Lease exhaustion names the dimension that fired (#92)."""

from jarviscore.kernel.lease import ExecutionLease


def _lease(**overrides):
    lease = ExecutionLease.for_role("researcher")
    for k, v in overrides.items():
        setattr(lease, k, v)
    return lease


def test_fresh_lease_reports_nothing():
    lease = _lease()
    assert lease.expired_dimensions() == []
    assert not lease.is_expired()


def test_thinking_exhaustion_named():
    lease = _lease()
    lease.thinking_used = lease.thinking_budget
    dims = lease.expired_dimensions()
    assert any(d.startswith("thinking(") for d in dims)
    assert lease.is_expired()


def test_action_exhaustion_named():
    lease = _lease()
    lease.action_used = lease.action_budget
    assert any(d.startswith("action(") for d in lease.expired_dimensions())


def test_total_exhaustion_named_with_counts():
    lease = _lease()
    lease.thinking_used = lease.max_total_tokens
    dims = lease.expired_dimensions()
    total = next(d for d in dims if d.startswith("total_tokens("))
    assert f"{lease.max_total_tokens}/{lease.max_total_tokens}" in total


def test_turn_fuse_named():
    lease = _lease()
    lease.turns_used = lease.emergency_turn_fuse
    assert any(d.startswith("turn_fuse(") for d in lease.expired_dimensions())


def test_wall_clock_named():
    lease = _lease()
    lease.start_time -= (lease.wall_clock_ms / 1000) + 1
    assert any(d.startswith("wall_clock(") for d in lease.expired_dimensions())


def test_multiple_dimensions_all_named():
    lease = _lease()
    lease.thinking_used = lease.thinking_budget
    lease.turns_used = lease.emergency_turn_fuse
    dims = lease.expired_dimensions()
    assert len(dims) >= 2
