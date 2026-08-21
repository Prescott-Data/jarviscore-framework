"""Regression tests for the temporary JarvisCore launch-promotion client."""

import json
from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.llm import LLMProvider, UnifiedLLMClient
from jarviscore.kernel.kernel import Kernel
from jarviscore.promo import PROMO_MODEL, PromoAccessError, PromoLLMClient, PromoProtocolError
from jarviscore.promo.client import _HTTPResult


def _promo_only_config(tmp_path, **extra):
    config = {
        "promo_token": "jc_trial_secret",
        "promo_raw_artifact_dir": str(tmp_path),
        "azure_api_key": None,
        "azure_openai_key": None,
        "azure_endpoint": None,
        "azure_openai_endpoint": None,
        "claude_api_key": None,
        "anthropic_api_key": None,
        "gemini_api_key": None,
        "vertex_ai_enabled": False,
        "vertex_ai_project": None,
        "llm_endpoint": None,
        "vllm_endpoint": None,
    }
    config.update(extra)
    return config


def _success_body(call_id: str, content: str, tool_calls=None, model="jarviscore-promo") -> str:
    return json.dumps(
        {
            "call_id": call_id,
            "content": content,
            "tool_calls": tool_calls or [],
            "usage": {"input": 101, "output": 202, "total": 303},
            "model": model,
            "finish_reason": "stop",
            "entitlement": {
                "expires_at": "2026-09-30T00:00:00Z",
                "remaining_tokens": 999_697,
            },
        }
    )


@pytest.mark.asyncio
async def test_large_tail_evidence_and_relation_labels_are_preserved(tmp_path):
    client = PromoLLMClient(token="jc_trial_secret", artifact_dir=str(tmp_path))
    tail_evidence = "TAIL_EVIDENCE_MUST_SURVIVE"
    content = "prefix-" + ("x" * 20_000) + tail_evidence
    tool_calls = [
        {
            "id": "call_relation",
            "name": "retrieve_paths",
            "arguments": {
                "paths": [
                    {
                        "nodes": ["customer", "invoice", "payment"],
                        "edges": ["customer-invoice", "invoice-payment"],
                        "relations": ["OWNS", "SETTLED_BY"],
                        "confidence": 0.987,
                    }
                ],
                "ppr_ranked_entities": [
                    {"entity": f"entity-{index}", "score": 1 / (index + 1)}
                    for index in range(1_000)
                ],
            },
        }
    ]

    async def send(payload, call_id):
        return _HTTPResult(
            status=200,
            headers={"X-JarvisCore-Call-ID": call_id},
            body=_success_body(call_id, content, tool_calls),
        )

    client._send = send
    messages = [{"role": "user", "content": "retain every item"}]
    options = {"response_format": {"type": "json_object"}, "custom_evidence": list(range(2_000))}
    result = await client.generate(
        messages,
        temperature=0.0,
        max_tokens=30_000,
        options=options,
    )

    assert result["content"].endswith(tail_evidence)
    assert result["tool_calls"][0]["arguments"]["paths"][0]["relations"] == [
        "OWNS",
        "SETTLED_BY",
    ]
    assert len(result["tool_calls"][0]["arguments"]["ppr_ranked_entities"]) == 1_000
    assert result["raw_response"]["content"] == content

    artifact = json.loads((tmp_path / f'{result["call_id"]}.json').read_text())
    assert artifact["request"]["payload"]["messages"] == messages
    assert artifact["request"]["payload"]["options"] == options
    assert tail_evidence in artifact["response"]["body"]
    assert "SETTLED_BY" in artifact["response"]["body"]
    assert "jc_trial_secret" not in json.dumps(artifact)
    assert artifact["excluded_diagnostics"] == ["request.headers.Authorization"]


@pytest.mark.asyncio
async def test_error_response_is_preserved_and_exposed(tmp_path):
    client = PromoLLMClient(token="jc_trial_secret", artifact_dir=str(tmp_path))
    tail_evidence = "quota-ledger-tail-record"

    async def send(payload, call_id):
        return _HTTPResult(
            status=402,
            headers={"Retry-After": "0"},
            body=json.dumps(
                {
                    "code": "quota_exhausted",
                    "message": "Promotional allowance consumed",
                    "ledger_evidence": ["opening", tail_evidence],
                }
            ),
        )

    client._send = send
    with pytest.raises(PromoAccessError) as caught:
        await client.generate(
            [{"role": "user", "content": "hello"}],
            temperature=0.0,
            max_tokens=10,
        )

    error = caught.value
    assert error.code == "quota_exhausted"
    assert error.status == 402
    assert error.raw_response["ledger_evidence"][-1] == tail_evidence
    artifact = json.loads(open(error.raw_artifact_path, encoding="utf-8").read())
    assert tail_evidence in artifact["response"]["body"]


@pytest.mark.asyncio
async def test_network_errors_never_persist_the_promotion_token(tmp_path):
    token = "jc_trial_must_not_leak"
    client = PromoLLMClient(token=token, artifact_dir=str(tmp_path))

    async def send(payload, call_id):
        raise RuntimeError(f"transport rejected Authorization: Bearer {token}")

    client._send = send
    with pytest.raises(PromoAccessError) as caught:
        await client.generate(
            [{"role": "user", "content": "hello"}],
            temperature=0.0,
            max_tokens=10,
        )

    error = caught.value
    assert error.code == "promotion_network_error"
    assert token not in str(error)
    assert token not in json.dumps(error.raw_response)
    artifact = open(error.raw_artifact_path, encoding="utf-8").read()
    assert token not in artifact


@pytest.mark.asyncio
async def test_promo_failure_never_falls_through_to_paid_provider(tmp_path):
    llm = UnifiedLLMClient(
        config={
            "promo_token": "jc_trial_secret",
            "promo_raw_artifact_dir": str(tmp_path),
            "azure_api_key": None,
            "azure_openai_key": None,
            "azure_endpoint": None,
            "azure_openai_endpoint": None,
            "claude_api_key": None,
            "anthropic_api_key": None,
            "gemini_api_key": None,
            "vertex_ai_enabled": False,
            "vertex_ai_project": None,
            "llm_endpoint": None,
            "vllm_endpoint": None,
        }
    )
    paid_provider = AsyncMock(return_value={"content": "unexpected paid response"})
    llm._call_azure = paid_provider
    llm.provider_order = [LLMProvider.PROMO, LLMProvider.AZURE]
    llm.promo_client.generate = AsyncMock(
        side_effect=PromoAccessError(
            "promotion_expired",
            "Promotion expired",
            status=403,
            call_id="jcp_expired",
        )
    )

    with pytest.raises(PromoAccessError, match="Promotion expired"):
        await llm.generate(prompt="hello", max_tokens=10)
    paid_provider.assert_not_awaited()


def test_promo_is_auto_detected_first_and_uses_fixed_https_endpoint(tmp_path):
    llm = UnifiedLLMClient(
        config={
            "promo_token": "jc_trial_secret",
            "promo_raw_artifact_dir": str(tmp_path),
            "azure_api_key": None,
            "azure_openai_key": None,
            "azure_endpoint": None,
            "azure_openai_endpoint": None,
            "claude_api_key": None,
            "anthropic_api_key": None,
            "gemini_api_key": None,
            "vertex_ai_enabled": False,
            "vertex_ai_project": None,
            "llm_endpoint": None,
            "vllm_endpoint": None,
        }
    )

    assert llm.provider_order == [LLMProvider.PROMO]
    assert llm.promo_client.endpoint == (
        "https://jarviscore.developers.prescottdata.io/api/promo/v1/generate"
    )
    assert llm.nano_model == "jarviscore-promo"
    assert llm.planner_model == "jarviscore-promo"


def test_promo_client_endpoint_is_fixed_and_not_configurable(tmp_path):
    with pytest.raises(TypeError):
        PromoLLMClient(
            token="jc_trial_secret",
            endpoint="https://attacker.example/generate",
            artifact_dir=str(tmp_path),
        )

    client = PromoLLMClient(token="jc_trial_secret", artifact_dir=str(tmp_path))
    with pytest.raises(AttributeError):
        client.endpoint = "https://attacker.example/generate"


def test_promo_client_model_is_fixed_and_not_configurable(tmp_path):
    with pytest.raises(TypeError):
        PromoLLMClient(
            token="jc_trial_secret",
            model="gpt-4o-private-deployment",
            artifact_dir=str(tmp_path),
        )

    client = PromoLLMClient(token="jc_trial_secret", artifact_dir=str(tmp_path))
    assert not hasattr(client, "model")


def test_promo_model_configuration_is_ignored(tmp_path):
    llm = UnifiedLLMClient(
        config=_promo_only_config(tmp_path, promo_model="gpt-4o-private-deployment")
    )

    assert llm.provider_order == [LLMProvider.PROMO]
    assert llm.nano_model == PROMO_MODEL
    assert llm.planner_model == PROMO_MODEL
    assert not hasattr(llm.promo_client, "model")


def test_kernel_tiers_resolve_to_promo_alias(tmp_path):
    llm = UnifiedLLMClient(config=_promo_only_config(tmp_path))
    kernel = Kernel(
        llm_client=llm,
        config={
            "coding_model": "gpt-5-codex",
            "browser_model": "cua-preview",
            "task_model": "gpt-5",
            "task_model_nano": "gpt-5.4-nano",
            "task_model_standard": "gpt-5-mini",
            "task_model_heavy": "gpt-5.2-chat",
        },
    )

    tiers = [
        ("coding", None),
        ("browser", None),
        ("task", None),
        ("task", "nano"),
        ("task", "standard"),
        ("task", "heavy"),
    ]
    for tier, complexity in tiers:
        assert kernel._get_model_for_tier(tier, complexity) == PROMO_MODEL


@pytest.mark.asyncio
async def test_direct_model_override_fails_visibly(tmp_path):
    llm = UnifiedLLMClient(config=_promo_only_config(tmp_path))
    sent_payloads = []

    async def send(payload, call_id):
        sent_payloads.append(payload)
        return _HTTPResult(status=200, headers={}, body=_success_body(call_id, "ok"))

    llm.promo_client._send = send
    with pytest.raises(ValueError, match="cannot request model"):
        await llm.generate(prompt="hello", max_tokens=10, model="gpt-4o")
    assert sent_payloads == []


@pytest.mark.asyncio
async def test_payload_never_contains_a_requested_model(tmp_path):
    llm = UnifiedLLMClient(config=_promo_only_config(tmp_path))
    captured = {}

    async def send(payload, call_id):
        captured["payload"] = payload
        return _HTTPResult(status=200, headers={}, body=_success_body(call_id, "ok"))

    llm.promo_client._send = send
    # Internal tier routing passes the alias; the payload must carry only it.
    await llm.generate(prompt="hello", max_tokens=10, model=PROMO_MODEL)

    assert "requested_model" not in captured["payload"]
    assert captured["payload"]["model"] == PROMO_MODEL


@pytest.mark.asyncio
async def test_response_naming_a_real_model_is_rejected(tmp_path):
    client = PromoLLMClient(token="jc_trial_secret", artifact_dir=str(tmp_path))

    async def send(payload, call_id):
        return _HTTPResult(
            status=200,
            headers={},
            body=_success_body(call_id, "leaky", model="gpt-4o-eastus-deployment"),
        )

    client._send = send
    with pytest.raises(PromoProtocolError, match="promotional alias"):
        await client.generate(
            [{"role": "user", "content": "hello"}],
            temperature=0.0,
            max_tokens=10,
        )


@pytest.mark.asyncio
async def test_send_uses_bearer_header_and_never_places_token_in_payload(tmp_path, monkeypatch):
    captured = {}

    class FakeResponse:
        status = 200
        headers = {"X-Test": "ok"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def text(self):
            return "{}"

    class FakeSession:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def post(self, endpoint, *, json, headers):
            captured.update(endpoint=endpoint, payload=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr("jarviscore.promo.client.aiohttp.ClientSession", FakeSession)
    token = "jc_trial_header_only"
    client = PromoLLMClient(token=token, artifact_dir=str(tmp_path))
    payload = {"call_id": "jcp_header_test", "messages": []}

    response = await client._send(payload, "jcp_header_test")

    assert response.status == 200
    assert captured["endpoint"] == client.endpoint
    assert captured["headers"]["Authorization"] == f"Bearer {token}"
    assert captured["headers"]["X-JarvisCore-Call-ID"] == "jcp_header_test"
    assert token not in json.dumps(captured["payload"])
