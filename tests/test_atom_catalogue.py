"""The atom catalogue is loaded, offered, and added to.

The framework ships 1,224 atoms across 150 providers, the docs describe them as
available from startup, and nothing ever loaded them. Every deployment began
with an empty registry, so the Kernel's registry-first search found nothing, the
coder's `check_registry` found nothing, and agents rewrote integrations that
were already on disk — then threw the new code away, because the coder path
never wrote back either.

These tests hold the three links: the catalogue is seeded, a match is offered
with its stage stated rather than filtered out, and what the agent is told to do
about it lives in the prompt rather than in a sentence injected into state.
"""

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarviscore.execution.code_registry import create_function_registry
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

    def test_a_registry_with_history_is_not_reseeded(self, monkeypatch):
        """Re-seeding would overwrite execution counts earned by real runs."""
        calls = []

        def fake_seed(registry, **kwargs):
            calls.append(registry)
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
            create_function_registry(directory)
            assert len(calls) == 1
            create_function_registry(directory)      # same path, now populated
            assert len(calls) == 1

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
