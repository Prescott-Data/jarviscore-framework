"""Cross-session memory with no service to run: kept facts outlive the process."""

import json

import pytest

from jarviscore.kernel import Kernel
from jarviscore.memory.local import LocalMemory
from jarviscore.memory.unified import UnifiedMemory
from jarviscore.storage.local import LocalBlobStorage
from jarviscore.testing import MockLLMClient


def _reply(content):
    return {"content": content, "tokens": {"input": 1, "output": 1, "total": 2}, "cost_usd": 0.0}


def _route(role):
    return _reply(json.dumps({"role": role, "confidence": 0.9, "reason": "t", "evidence_required": False}))


FACT = "Acme Corp renews its contract on 3 March 2027; the contact person is Jane Mwangi."


class TestLocalMemory:
    def test_a_kept_fact_is_found_by_a_later_instance(self, tmp_path):
        LocalMemory("account_manager", base_dir=str(tmp_path)).remember(FACT, kind="client")

        found = LocalMemory("account_manager", base_dir=str(tmp_path)).recall(
            "When does Acme Corp renew, and who is the contact?"
        )

        assert found[0]["content"] == FACT
        assert found[0]["kind"] == "client"

    def test_identity_and_tenant_keep_memories_apart(self, tmp_path):
        LocalMemory("account_manager", scope="tenant-a", base_dir=str(tmp_path)).remember(FACT)

        assert LocalMemory("account_manager", scope="tenant-b", base_dir=str(tmp_path)).recall("Acme") == []
        assert LocalMemory("researcher", scope="tenant-a", base_dir=str(tmp_path)).recall("Acme") == []
        assert LocalMemory("account_manager", scope="tenant-a", base_dir=str(tmp_path)).recall("Acme")

    def test_the_same_fact_is_kept_once(self, tmp_path):
        memory = LocalMemory("a", base_dir=str(tmp_path))
        assert memory.remember(FACT) and memory.remember(FACT)

        assert len(memory.recall("Acme Corp contract")) == 1

    def test_nothing_unrelated_is_returned(self, tmp_path):
        memory = LocalMemory("a", base_dir=str(tmp_path))
        memory.remember(FACT)

        assert memory.recall("weather in Nairobi") == []
        assert memory.recall("") == []


class TestUnifiedMemoryUsesTheLocalTier:
    @pytest.mark.asyncio
    async def test_remember_and_recall_without_athena(self, tmp_path):
        local = LocalMemory("account_manager", base_dir=str(tmp_path))
        memory = UnifiedMemory("wf", "step", "account_manager-1a2b3c4d", local_memory=local)

        assert await memory.remember(FACT, kind="client") is True
        assert (await memory.recall("Acme renewal contact"))[0]["content"] == FACT

    @pytest.mark.asyncio
    async def test_athena_is_keyed_to_the_stable_identity(self, monkeypatch):
        seen = {}

        async def create(**kwargs):
            seen.update(kwargs)
            return None

        monkeypatch.setattr("jarviscore.memory.athena_memory.AthenaMemory.create", create)
        memory = UnifiedMemory(
            "wf", "step", "account_manager-1a2b3c4d",
            athena_client=object(), memory_identity="account_manager",
        )

        await memory._get_athena_memory()

        assert seen["agent_id"] == "account_manager"


class TestKernelMemoryAcrossProcesses:
    def _kernel(self, tmp_path, llm, **config):
        kernel = Kernel(
            llm_client=llm,
            blob_storage=LocalBlobStorage(str(tmp_path / "blobs")),
            config={"kernel_max_turns": 5, **config},
        )
        kernel.memory_identity = "account_manager"
        return kernel

    @pytest.mark.asyncio
    async def test_a_fact_kept_in_one_run_reaches_the_next(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        first = MockLLMClient(responses=[
            _route("communicator"),
            _reply(f"THOUGHT: keep it\nTOOL: remember\nPARAMS: {json.dumps({'fact': FACT})}"),
            _reply("THOUGHT: kept\nDONE: Noted.\nRESULT: {}"),
        ])
        await self._kernel(tmp_path, first).execute(
            task="Remember for later: Acme renews on 3 March 2027, contact Jane Mwangi.",
            agent_id="account_manager-aaaa1111",
        )

        second = MockLLMClient(responses=[
            _route("communicator"),
            _reply("THOUGHT: from memory\nDONE: 3 March 2027, Jane Mwangi.\nRESULT: {}"),
        ])
        output = await self._kernel(tmp_path, second).execute(
            task="When does Acme Corp renew, and who is the contact person?",
            agent_id="account_manager-bbbb2222",
        )

        assert output.status == "success"
        prompt = "\n".join(str(m.get("content")) for m in second.calls[-1]["messages"])
        assert "FROM EARLIER SESSIONS" in prompt
        assert "Jane Mwangi" in prompt

    @pytest.mark.asyncio
    async def test_a_mesh_that_separates_tenants_keeps_unscoped_steps_closed(self, tmp_path):
        kernel = self._kernel(tmp_path, MockLLMClient(), memory_scope_field="owner_id")

        assert kernel._create_memory("wf", "s", "a", {}).local is None
        assert kernel._create_memory("wf", "s", "a", {"owner_id": "t1"}).local.scope == "t1"

    @pytest.mark.asyncio
    async def test_the_local_tier_can_be_turned_off(self, tmp_path):
        kernel = self._kernel(tmp_path, MockLLMClient(), local_memory=False)

        assert kernel._create_memory("wf", "s", "a", {}).local is None
