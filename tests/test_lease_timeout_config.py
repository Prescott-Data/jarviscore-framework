"""Regression tests for issues #135 and #137.

#135 — global kernel_* config knobs (bridged from Settings/env by Mesh) must
reach lease enforcement, and per-role kernel_role_profiles overrides must merge
key-wise instead of replacing whole profiles.

#137 — workflow step wait budgets must be configurable: workflow_step_timeout
config, mesh.workflow(timeout_per_step=...), and per-step "timeout" keys.
"""
import pytest

from jarviscore.config.settings import Settings
from jarviscore.kernel.kernel import Kernel
from jarviscore.kernel.lease import ROLE_LEASE_PROFILES
from jarviscore.orchestration.dependency import DependencyManager


def _kernel(config=None):
    return Kernel(llm_client=None, config=config or {})


class TestGlobalLeaseOverrides:
    def test_defaults_match_profiles(self):
        kernel = _kernel()
        lease = kernel._lease_for_role("researcher")
        assert lease.wall_clock_ms == ROLE_LEASE_PROFILES["researcher"]["wall_clock_ms"]

    def test_global_wall_clock_reaches_every_role(self):
        kernel = _kernel({"kernel_wall_clock_ms": 999_000})
        for role in ("coder", "researcher", "communicator", "browser"):
            assert kernel._lease_for_role(role).wall_clock_ms == 999_000

    def test_global_token_budgets_apply(self):
        kernel = _kernel({
            "kernel_max_total_tokens": 111_000,
            "kernel_thinking_budget": 66_000,
            "kernel_action_budget": 33_000,
        })
        lease = kernel._lease_for_role("researcher")
        assert lease.max_total_tokens == 111_000
        assert lease.thinking_budget == 66_000
        assert lease.action_budget == 33_000

    def test_per_role_override_beats_global(self):
        kernel = _kernel({
            "kernel_wall_clock_ms": 999_000,
            "kernel_role_profiles": {"researcher": {"wall_clock_ms": 5_000}},
        })
        assert kernel._lease_for_role("researcher").wall_clock_ms == 5_000
        assert kernel._lease_for_role("coder").wall_clock_ms == 999_000

    def test_partial_role_override_merges_keywise(self):
        kernel = _kernel({
            "kernel_role_profiles": {"researcher": {"wall_clock_ms": 5_000}},
        })
        lease = kernel._lease_for_role("researcher")
        assert lease.wall_clock_ms == 5_000
        # the rest of the profile must survive a partial override
        assert lease.model_tier == ROLE_LEASE_PROFILES["researcher"]["model_tier"]
        assert lease.thinking_budget == ROLE_LEASE_PROFILES["researcher"]["thinking_budget"]

    def test_builtin_profiles_not_mutated(self):
        before = dict(ROLE_LEASE_PROFILES["researcher"])
        _kernel({"kernel_wall_clock_ms": 1_000})
        assert ROLE_LEASE_PROFILES["researcher"] == before


class TestWorkflowTimeoutConfig:
    def test_settings_field_exists(self):
        assert Settings().workflow_step_timeout == 300.0

    def test_dependency_manager_default(self):
        mgr = DependencyManager(default_timeout=42.0)
        assert mgr.default_timeout == 42.0

    @pytest.mark.asyncio
    async def test_wait_for_uses_default_when_none(self, monkeypatch):
        mgr = DependencyManager(default_timeout=7.0)
        seen = {}

        async def fake_wait_memory(deps, memory, timeout):
            seen["timeout"] = timeout
            return {}

        monkeypatch.setattr(mgr, "_wait_memory", fake_wait_memory)
        await mgr.wait_for(["s1"], {})
        assert seen["timeout"] == 7.0

    @pytest.mark.asyncio
    async def test_wait_for_explicit_timeout_wins(self, monkeypatch):
        mgr = DependencyManager(default_timeout=7.0)
        seen = {}

        async def fake_wait_memory(deps, memory, timeout):
            seen["timeout"] = timeout
            return {}

        monkeypatch.setattr(mgr, "_wait_memory", fake_wait_memory)
        await mgr.wait_for(["s1"], {}, timeout=1.5)
        assert seen["timeout"] == 1.5
