"""Word matching may order atoms within a provider. It may not pick the provider.

Ranking across all 150 providers let substring counting choose one: the letter
"a" scored as a name match against 1,130 atoms, and "crm" scored inside the
vendor name "agilecrm", so a task about Slack surfaced a CRM atom.
"""

import pytest

from jarviscore.execution.code_registry import FunctionRegistry
from jarviscore.kernel.kernel import Kernel


SLACK_TASK = "Post a short message to our Slack #general channel saying the CRM audit is starting."


@pytest.fixture
def registry(tmp_path):
    r = FunctionRegistry(storage_path=str(tmp_path))
    r.function_metadata = {
        "slack_send_message": {
            "function_name": "slack_send_message",
            "system": "slack",
            "description": "Send a message to a Slack channel.",
            "capabilities": ["messaging"],
            "tags": ["slack", "chat"],
            "registry_stage": "verified",
        },
        "agilecrm_list_accounts": {
            "function_name": "agilecrm_list_accounts",
            "system": "agilecrm",
            "description": "List companies via POST /contacts/companies/list.",
            "capabilities": ["accounts"],
            "tags": ["agilecrm", "crm"],
            "registry_stage": "verified",
        },
    }
    return r


# ── Ranking ──────────────────────────────────────────────────────────────────

def test_a_stopword_matches_nothing(registry):
    """'a' used to score a name match against almost every atom."""
    assert registry.semantic_search("a", limit=100) == []


def test_stopwords_do_not_carry_a_task(registry):
    assert registry.semantic_search("is the to of our", limit=100) == []


def test_a_single_letter_is_not_a_name_match(registry):
    """Substring matching made 'a' a maximum-weight hit on 'agilecrm_...'."""
    for match in registry.semantic_search("a message", limit=10):
        assert match["function_name"] == "slack_send_message"


def test_the_right_provider_outranks_the_lexical_accident(registry):
    top = registry.semantic_search(SLACK_TASK, limit=5)[0]
    assert top["system"] == "slack"


def test_crm_no_longer_scores_inside_a_vendor_name(registry):
    """'crm' is a substring of 'agilecrm'; it must not read as a name match."""
    scores = {m["function_name"]: m["_score"] for m in registry.semantic_search(SLACK_TASK, limit=5)}
    assert scores["slack_send_message"] > scores.get("agilecrm_list_accounts", 0)


# ── Selection ────────────────────────────────────────────────────────────────

def _kernel(registry):
    k = Kernel.__new__(Kernel)
    k.code_registry = registry
    return k


def test_no_provider_named_means_no_candidate(registry):
    """Which API a task needs is a decision, not a word count."""
    assert _kernel(registry)._check_registry_reuse(SLACK_TASK) is None


def test_a_named_provider_searches_only_inside_it(registry, monkeypatch):
    monkeypatch.setattr(registry, "get_function_code", lambda name: "def f(): ...")
    candidate = _kernel(registry)._check_registry_reuse(SLACK_TASK, system="slack")
    assert candidate is not None
    assert candidate["system"] == "slack"


def test_a_named_provider_never_yields_another_ones_atom(registry, monkeypatch):
    monkeypatch.setattr(registry, "get_function_code", lambda name: "def f(): ...")
    candidate = _kernel(registry)._check_registry_reuse(
        "list our companies", system="agilecrm"
    )
    assert candidate is None or candidate["system"] == "agilecrm"
