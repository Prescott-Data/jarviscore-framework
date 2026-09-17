"""The atom catalogue is loaded, offered, and added to.

The framework ships a catalogue of atoms across 150 providers, the docs describe
them as available from startup, and nothing ever loaded them. Every deployment
began with an empty registry, so the Kernel's registry-first search found
nothing, the coder's `check_registry` found nothing, and agents rewrote
integrations that were already on disk, then threw the new code away, because
the coder path never wrote back either.

These tests hold the three links: the catalogue is seeded, a match is offered
with its stage stated rather than filtered out, and what the agent is told to do
about it lives in the prompt rather than in a sentence injected into state.
"""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarviscore.execution.code_registry import create_function_registry
from jarviscore.execution.atom_contract import read_contract
from jarviscore.integrations.seed_registry import seed_registry
from jarviscore.kernel.defaults.coder import CoderSubAgent


@pytest.fixture(scope="module")
def seeded():
    with tempfile.TemporaryDirectory() as directory:
        yield create_function_registry(directory)


# ──────────────────────────────────────────────────────────────────
# Seeding
# ──────────────────────────────────────────────────────────────────

class TestCatalogueIsLoaded:

    def test_a_fresh_registry_holds_the_shipped_atoms(self, seeded):
        assert len(seeded.function_metadata) > 1000

    def test_atoms_are_scoped_to_their_provider(self, seeded):
        names = {f["function_name"] for f in seeded.get_functions_by_system("hubspot")}
        assert "hubspot_list_contacts" in names

    def test_the_task_that_started_this_finds_its_atom(self, seeded):
        """"Read our HubSpot CRM and tell me how many contacts we have.\""""
        hits = seeded.semantic_search("how many contacts are in hubspot", limit=5)
        assert "hubspot_list_contacts" in [h["function_name"] for h in hits]

    def test_seeding_can_be_declined(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = create_function_registry(directory, seed=False)
            assert registry.function_metadata == {}

    def test_a_registry_with_history_receives_only_missing_shipped_atoms(self, monkeypatch):
        calls = []

        def fake_seed(registry, **kwargs):
            calls.append(kwargs)
            if not registry.has_function("hubspot_list_contacts"):
                registry.register_function(
                    "hubspot_list_contacts",
                    "def hubspot_list_contacts(auth_info):\n    return {}\n",
                    metadata={"system": "hubspot", "description": "list contacts"},
                )
            return {"registered": ["hubspot_list_contacts"], "failed": []}

        monkeypatch.setattr(
            "jarviscore.integrations.seed_registry.seed_registry", fake_seed,
        )
        with tempfile.TemporaryDirectory() as directory:
            first = create_function_registry(directory)
            first.update_function_metadata("hubspot_list_contacts", {"success_count": 7})
            assert len(calls) == 1
            second = create_function_registry(directory)
            assert len(calls) == 2
            assert all(call == {"missing_only": True} for call in calls)
            assert second.get_function_metadata("hubspot_list_contacts")["success_count"] == 7

    def test_stale_invalid_builtin_is_upgraded_without_losing_history(self):
        legacy = """
async def google_calendar_delete_event(event_id: str, calendar_id='primary'):
    return await nexus_call('DELETE', f'https://example.test/{event_id}')
"""
        with tempfile.TemporaryDirectory() as directory:
            registry = create_function_registry(directory, seed=False)
            registry.register_function(
                "google_calendar_delete_event",
                legacy,
                metadata={
                    "system": "google_calendar",
                    "description": "Delete an event",
                    "capabilities": ["delete_event"],
                },
            )
            registry.update_function_metadata(
                "google_calendar_delete_event",
                {"execution_count": 9, "success_count": 7, "failure_count": 2},
            )

            seed_registry(registry, systems=["google_calendar"], missing_only=True)

            source = registry.get_function_code("google_calendar_delete_event")
            contract = read_contract(
                source, system="google_calendar",
                expected_name="google_calendar_delete_event",
            )
            metadata = registry.get_function_metadata("google_calendar_delete_event")
            assert contract.ok
            assert metadata["version"] == 2
            assert metadata["execution_count"] == 9
            assert metadata["success_count"] == 7
            assert metadata["failure_count"] == 2

    def test_stale_token_retrieving_builtin_is_upgraded(self):
        stale = """
async def google_drive_create_folder(folder_name: str, parent_folder_id: str=None) -> dict:
    token = _get_nexus_token(None)
    return await nexus_call('POST', 'https://example.test', headers={'Authorization': token})
"""
        with tempfile.TemporaryDirectory() as directory:
            registry = create_function_registry(directory, seed=False)
            registry.register_function(
                "google_drive_create_folder",
                stale,
                metadata={
                    "system": "google_drive",
                    "description": "Create folder",
                    "capabilities": ["folders"],
                },
            )
            registry.update_function_metadata(
                "google_drive_create_folder",
                {"execution_count": 4, "failure_count": 4},
            )

            seed_registry(registry, systems=["google_drive"], missing_only=True)

            source = registry.get_function_code("google_drive_create_folder")
            metadata = registry.get_function_metadata("google_drive_create_folder")
            assert "_get_nexus_token" not in source
            assert metadata["version"] == 2
            assert metadata["execution_count"] == 4
            assert metadata["failure_count"] == 4

    def test_changed_valid_catalogue_atom_converges_but_repair_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = create_function_registry(directory, seed=False)
            stale_valid = '''\
async def google_calendar_list_events(calendar_id: str='primary') -> dict:
    """List calendar events without participant details."""
    response = await nexus_call('GET', 'https://example.test/events')
    return {'success': True, 'events': response['json'].get('items', [])}
'''
            registry.register_function(
                "google_calendar_list_events",
                stale_valid,
                metadata={
                    "system": "google_calendar",
                    "description": "List events",
                    "capabilities": ["events"],
                    "catalogue_managed": True,
                    "catalogue_source_hash": hashlib.sha256(
                        stale_valid.encode("utf-8")
                    ).hexdigest(),
                },
            )

            seed_registry(registry, systems=["google_calendar"], missing_only=True)
            upgraded = registry.get_function_metadata(
                "google_calendar_list_events"
            )
            assert upgraded["version"] == 2
            assert "attendees" in registry.get_function_code(
                "google_calendar_list_events"
            )

            registry.update_function_metadata(
                "google_calendar_list_events",
                {"repair_of_version": 2},
            )
            repaired_source = registry.get_function_code(
                "google_calendar_list_events"
            ).replace("'status': e.get('status'),", "'status': 'locally-repaired',")
            registry.register_function(
                "google_calendar_list_events",
                repaired_source,
                metadata={
                    "system": "google_calendar",
                    "description": "List repaired events",
                    "capabilities": ["events"],
                    "repair_of_version": 2,
                },
            )
            seed_registry(registry, systems=["google_calendar"], missing_only=True)

            preserved = registry.get_function_metadata(
                "google_calendar_list_events"
            )
            assert preserved["version"] == 3
            assert "locally-repaired" in registry.get_function_code(
                "google_calendar_list_events"
            )

    def test_a_broken_catalogue_does_not_stop_the_agent(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "jarviscore.integrations.seed_registry.seed_registry",
            MagicMock(side_effect=RuntimeError("catalogue corrupt")),
        )
        with tempfile.TemporaryDirectory() as directory:
            with caplog.at_level("WARNING"):
                registry = create_function_registry(directory)

        assert registry.function_metadata == {}
        assert "registry starts empty" in caplog.text

    def test_seeding_nothing_is_reported_not_silent(self, monkeypatch, caplog):
        """An empty registry looking like normal operation is how this survived."""
        monkeypatch.setattr(
            "jarviscore.integrations.seed_registry.seed_registry",
            lambda registry, **kwargs: {"registered": [], "failed": []},
        )
        with tempfile.TemporaryDirectory() as directory:
            with caplog.at_level("WARNING"):
                create_function_registry(directory)

        assert "no functions" in caplog.text


# ──────────────────────────────────────────────────────────────────
# Offering the match
# ──────────────────────────────────────────────────────────────────

def _coder(matches, code="def run():\n    return 1\n"):
    coder = CoderSubAgent.__new__(CoderSubAgent)
    coder.code_registry = MagicMock()
    coder.code_registry.semantic_search.return_value = matches
    coder.code_registry.get_function_code.return_value = code
    coder.llm_client = MagicMock()
    coder._dispatch_metadata = {}
    return coder


def _match(name, stage, system="hubspot", success=0):
    return {
        "function_name": name, "registry_stage": stage, "system": system,
        "success_count": success, "description": name, "capabilities": [],
    }


@pytest.fixture(autouse=True)
def _no_llm_normalizer(monkeypatch):
    normalizer = MagicMock()
    normalizer.normalize = AsyncMock(side_effect=lambda task: task)
    monkeypatch.setattr(
        "jarviscore.execution.intent_normalizer.IntentNormalizer",
        lambda *args, **kwargs: normalizer,
    )


class TestCheckRegistry:

    @pytest.mark.asyncio
    async def test_a_candidate_is_offered_with_its_stage_stated(self):
        """Filtering candidates out left the agent writing code that existed."""
        coder = _coder([_match("hubspot_list_contacts", "candidate")])

        result = await coder._tool_check_registry(task="count contacts", system="hubspot")

        assert result["found"] is True
        assert result["function_name"] == "hubspot_list_contacts"
        assert result["stage"] == "candidate"
        assert "never confirmed against a live API" in result["message"]

    @pytest.mark.asyncio
    async def test_a_verified_match_is_preferred_over_a_candidate(self):
        coder = _coder([
            _match("hubspot_list_contacts", "candidate"),
            _match("hubspot_get_contact", "verified", success=3),
        ])

        result = await coder._tool_check_registry(task="contacts", system="hubspot")

        assert result["function_name"] == "hubspot_get_contact"
        assert "live API" in result["message"]

    @pytest.mark.asyncio
    async def test_the_whole_code_is_returned_not_a_preview(self):
        """A truncated function is not a function you can execute."""
        body = "def run():\n    " + ("# padding\n    " * 200) + "return 1\n"
        coder = _coder([_match("hubspot_list_contacts", "candidate")], code=body)

        result = await coder._tool_check_registry(task="contacts", system="hubspot")

        assert result["code"] == body

    @pytest.mark.asyncio
    async def test_matches_are_scoped_to_the_declared_system(self):
        coder = _coder([
            _match("insightly_list_contacts", "verified", system="insightly"),
            _match("hubspot_list_contacts", "candidate", system="hubspot"),
        ])

        result = await coder._tool_check_registry(task="contacts", system="hubspot")

        assert result["system"] == "hubspot"

    @pytest.mark.asyncio
    async def test_a_verified_atom_for_the_wrong_provider_never_wins(self):
        """Observed live: a HubSpot task was handed a verified AgileCRM atom.

        Stage only ranks within the right system. An atom for another provider
        calls a different API, so it is not a weaker match — it is wrong.
        """
        coder = _coder([
            _match("agilecrm_get_account", "verified", system="agilecrm", success=1),
            _match("hubspot_list_contacts", "candidate", system="hubspot"),
        ])

        result = await coder._tool_check_registry(task="count contacts", system="hubspot")

        assert result["function_name"] == "hubspot_list_contacts"

    @pytest.mark.asyncio
    async def test_nothing_for_this_provider_is_said_plainly(self):
        coder = _coder([_match("agilecrm_get_account", "verified", system="agilecrm")])

        result = await coder._tool_check_registry(task="contacts", system="hubspot")

        assert result["found"] is False
        assert "No function in the registry targets hubspot" in result["message"]

    @pytest.mark.asyncio
    async def test_the_declared_system_is_taken_from_the_run_context(self):
        """The provider is in state; the agent should not have to remember it."""
        coder = _coder([
            _match("agilecrm_get_account", "verified", system="agilecrm"),
            _match("hubspot_list_contacts", "candidate", system="hubspot"),
        ])
        coder._run_context = {"system": "hubspot"}

        result = await coder._tool_check_registry(task="count contacts")

        assert result["function_name"] == "hubspot_list_contacts"

    @pytest.mark.asyncio
    async def test_no_match_is_reported_plainly(self):
        coder = _coder([])
        result = await coder._tool_check_registry(task="contacts", system="hubspot")
        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_no_registry_is_not_a_crash(self):
        coder = CoderSubAgent.__new__(CoderSubAgent)
        coder.code_registry = None
        result = await coder._tool_check_registry(task="contacts")
        assert result["found"] is False


# ──────────────────────────────────────────────────────────────────
# Where the teaching lives
# ──────────────────────────────────────────────────────────────────

class TestDecisionsAreTaughtNotInjected:

    def test_the_kernel_injects_facts_not_instructions(self):
        """A sentence telling the agent what to do does not belong in state."""
        import inspect
        from jarviscore.kernel.kernel import Kernel

        source = inspect.getsource(Kernel.execute)

        assert '"_hint"' not in source
        assert '"registry_candidate"' in source

    def test_the_coder_does_not_forward_a_hint_into_the_sandbox(self):
        import inspect

        source = inspect.getsource(CoderSubAgent)
        assert '"_hint"' not in source

    def test_the_prompt_teaches_the_catalogue(self):
        prompt = CoderSubAgent.DEFAULT_SYSTEM_PROMPT

        assert "THE CATALOGUE" in prompt
        assert "check_registry" in prompt
        assert "register_function" in prompt
        # Reuse is the first move, not the thing you try once stuck.
        assert prompt.index("check_registry") < prompt.index("delegate_research")


class TestFailedAtomRepairLifecycle:

    @pytest.mark.asyncio
    async def test_failed_atom_is_replaced_only_after_repaired_source_succeeds(self):
        original = '''\
async def google_drive_export_file(file_id: str, mime_type: str = "text/plain") -> dict:
    """Export a Google Workspace file."""
    response = await nexus_call("GET", f"https://example.test/files/{file_id}")
    return {"success": False, "error": response["body"]}
'''
        repaired = '''\
async def google_drive_export_file(file_id: str, mime_type: str = "text/plain") -> dict:
    """Export a Google Workspace file."""
    response = await nexus_call(
        "GET",
        f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
        params={"mimeType": mime_type},
    )
    if not response["ok"]:
        return {"success": False, "error": response["body"]}
    return {"success": True, "data": response["content"].decode("utf-8")}
'''
        with tempfile.TemporaryDirectory() as directory:
            registry = create_function_registry(directory, seed=False)
            registry.register_function(
                "google_drive_export_file",
                original,
                metadata={
                    "system": "google_drive",
                    "description": "Export a Google Workspace file",
                    "capabilities": ["export_file"],
                },
            )
            registry.update_execution_stats(
                "google_drive_export_file", success=True, execution_time=0.1,
            )
            old_path = Path(
                registry.get_function_metadata("google_drive_export_file")["atom_path"]
            )

            coder = CoderSubAgent(
                agent_id="repair-coder",
                llm_client=MagicMock(),
                sandbox=MagicMock(),
                code_registry=registry,
            )
            coder.sandbox.execute = AsyncMock(return_value={
                "status": "success",
                "output": {"success": True, "data": "Introduction"},
            })
            coder._run_context = {"system": "google_drive"}
            failed = {
                "status": "failure",
                "error": "Only files with binary content can be downloaded.",
                "execution_time": 0.2,
            }
            coder._record_atom_outcome(
                "google_drive_export_file",
                failed,
                params={"file_id": "doc-1", "mime_type": "text/plain"},
            )

            inspected = coder._tool_inspect_atom_for_repair("google_drive_export_file")
            candidate = coder._tool_repair_atom("google_drive_export_file", repaired)
            executed = await coder._tool_execute_code(candidate_id=candidate["candidate_id"])
            registered = coder._tool_register_function(
                function_name="google_drive_export_file",
                candidate_id=candidate["candidate_id"],
                system="google_drive",
            )

            metadata = registry.get_function_metadata("google_drive_export_file")
            assert inspected["source"] == original
            assert failed["atom_repair"]["available"] is True
            assert executed["status"] == "success"
            assert registered["status"] == "registered"
            assert metadata["version"] == 2
            assert metadata["registry_stage"] == "verified"
            assert metadata["repair_of_version"] == 1
            assert "binary content" in metadata["repair_failure"]
            assert registry.get_function_code("google_drive_export_file") == repaired
            assert old_path.read_text() == original

    def test_unexecuted_candidate_cannot_replace_registry_source(self):
        coder = CoderSubAgent.__new__(CoderSubAgent)
        coder.code_registry = MagicMock()
        coder._candidates = [{
            "candidate_id": 1,
            "code": "def hubspot_list_deals(): return {}",
            "status": "validated",
            "system": "hubspot",
        }]

        result = coder._tool_register_function(
            function_name="hubspot_list_deals",
            candidate_id=1,
            system="hubspot",
            description="List deals",
        )

        assert result["semantic_error"] == "REGISTRY_EXECUTION_PROOF_REQUIRED"
        coder.code_registry.register_function.assert_not_called()
