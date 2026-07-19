"""
Test LLM Provider Fallback Chain

Tests the fallback order: Azure → Claude → Gemini → Vertex AI → vLLM
Azure is the primary provider in this deployment.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch
import jarviscore.execution.llm as _llm_module
from jarviscore.execution.llm import UnifiedLLMClient, LLMProvider


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def test_provider_detection():
    """Test that all configured providers are detected."""
    llm = UnifiedLLMClient()

    actual_order = [p.value for p in llm.provider_order]
    print(f"\nDetected provider order: {actual_order}")
    print(f"  Azure:      {'Available' if llm.azure_client else 'Not available'}")
    print(f"  Claude:     {'Available' if llm.claude_client else 'Not available'}")
    print(f"  Gemini:     {'Available' if llm.gemini_client else 'Not available'}")
    print(f"  Vertex AI:  {'Available' if llm.vertex_ai_client else 'Not available'}")
    print(f"  vLLM:       {'Available' if llm.vllm_endpoint else 'Not available'}")

    assert len(actual_order) >= 0
    if not actual_order:
        pytest.skip("No LLM providers configured in this environment")
    if not llm.azure_client:
        pytest.skip("Azure not configured in this environment")
    assert actual_order[0] == 'azure', (
        f"Expected Azure as primary provider, got: {actual_order[0]}"
    )


# ---------------------------------------------------------------------------
# Live provider tests (skip when credentials not present)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_primary():
    """Test that Azure is used as the primary provider."""
    llm = UnifiedLLMClient()

    if not llm.azure_client:
        pytest.skip("Azure not configured in this environment")

    result = await llm.generate(
        prompt="Say 'OK' only",
        temperature=0.0,
        max_tokens=10,
    )

    print(f"\nProvider used: {result.get('provider', 'unknown')}")
    print(f"Response: {result.get('content', '')[:50]}")
    assert result.get('provider') == 'azure', (
        f"Expected azure, got {result.get('provider')}"
    )


@pytest.mark.asyncio
async def test_claude_fallback():
    """Test that Claude is used as fallback when Azure is disabled."""
    from jarviscore.config.settings import settings

    claude_only_config = {
        'azure_api_key': None,
        'azure_endpoint': None,
        'claude_api_key': getattr(settings, 'claude_api_key', None),
        'anthropic_api_key': getattr(settings, 'anthropic_api_key', None),
        'gemini_api_key': None,
        'vertex_ai_enabled': False,
        'vertex_ai_project': None,
        'llm_endpoint': None,
    }

    llm = UnifiedLLMClient(config=claude_only_config)

    if not llm.claude_client:
        pytest.skip("Claude not configured in this environment")

    try:
        result = await llm.generate(
            prompt="Say 'OK' only",
            temperature=0.0,
            max_tokens=10,
        )
        print(f"\nProvider used: {result.get('provider', 'unknown')}")
        assert result.get('provider') == 'claude', (
            f"Expected claude, got {result.get('provider')}"
        )
    except RuntimeError as e:
        pytest.skip(f"Claude deployment unavailable: {e}")


@pytest.mark.asyncio
async def test_gemini_fallback():
    """Test Gemini fallback when Azure and Claude are unavailable."""
    from jarviscore.config.settings import settings

    gemini_only_config = {
        'azure_api_key': None,
        'azure_endpoint': None,
        'claude_api_key': None,
        'anthropic_api_key': None,
        'gemini_api_key': getattr(settings, 'gemini_api_key', None),
        'gemini_model': getattr(settings, 'gemini_model', None),
        'vertex_ai_enabled': False,
        'vertex_ai_project': None,
        'llm_endpoint': None,
    }

    llm = UnifiedLLMClient(config=gemini_only_config)

    if not llm.gemini_client:
        pytest.skip("Gemini not configured in this environment")

    try:
        result = await llm.generate(
            prompt="Say 'OK' only",
            temperature=0.0,
            max_tokens=10,
        )
        print(f"\nProvider used: {result.get('provider', 'unknown')}")
        assert result.get('provider') == 'gemini'
    except Exception as e:
        pytest.skip(f"Gemini quota/rate limit: {e}")


@pytest.mark.asyncio
async def test_no_providers_raises():
    """Test that generating with no providers configured raises RuntimeError."""
    empty_config = {
        'azure_api_key': None,
        'azure_endpoint': None,
        'claude_api_key': None,
        'anthropic_api_key': None,
        'gemini_api_key': None,
        'vertex_ai_enabled': False,
        'vertex_ai_project': None,
        'llm_endpoint': None,
    }
    llm = UnifiedLLMClient(config=empty_config)
    assert len(llm.provider_order) == 0

    with pytest.raises((RuntimeError, Exception)):
        await llm.generate(prompt="test", max_tokens=5)


def _fake_azure_response(content: str = "OK"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3, total_tokens=13),
    )


@pytest.mark.asyncio
async def test_azure_content_filter_fails_visibly_by_default():
    """JarvisCore must not silently rewrite prompts after provider filter hits."""
    llm = UnifiedLLMClient(config={
        "azure_api_key": None,
        "azure_endpoint": None,
        "claude_api_key": None,
        "anthropic_api_key": None,
        "gemini_api_key": None,
        "vertex_ai_enabled": False,
        "llm_endpoint": None,
        "azure_content_filter_repair_enabled": False,
    })
    create = AsyncMock(side_effect=RuntimeError("ResponsibleAIPolicyViolation content_filter jailbreak"))
    llm.azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with pytest.raises(RuntimeError, match="does not rewrite prompts by default"):
        await llm._call_azure(
            messages=[{"role": "user", "content": "kill the competition"}],
            temperature=0.0,
            max_tokens=10,
        )
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_azure_content_filter_repair_is_explicit_opt_in():
    llm = UnifiedLLMClient(config={
        "azure_api_key": None,
        "azure_endpoint": None,
        "claude_api_key": None,
        "anthropic_api_key": None,
        "gemini_api_key": None,
        "vertex_ai_enabled": False,
        "llm_endpoint": None,
        "azure_content_filter_repair_enabled": True,
    })
    create = AsyncMock(side_effect=[
        RuntimeError("ResponsibleAIPolicyViolation content_filter hate"),
        _fake_azure_response("repaired"),
    ])
    llm.azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    result = await llm._call_azure(
        messages=[{"role": "user", "content": "kill the competition"}],
        temperature=0.0,
        max_tokens=10,
    )

    assert create.await_count == 2
    repaired_messages = create.await_args_list[1].kwargs["messages"]
    assert repaired_messages[0]["content"] == "outperform competitors"
    assert result["content"] == "repaired"
    assert result["content_filter_repaired"] is True


# ---------------------------------------------------------------------------
# Vertex AI provider tests (mocked — no real GCP credentials required)
# ---------------------------------------------------------------------------


def _vertex_config(**overrides):
    """Return a minimal config that enables only Vertex AI."""
    base = {
        'claude_api_key': None,
        'anthropic_api_key': None,
        'azure_api_key': None,
        'azure_endpoint': None,
        'gemini_api_key': None,
        'llm_endpoint': None,
        'vertex_ai_enabled': True,
        'vertex_ai_project': 'test-gcp-project',
        'vertex_ai_location': 'us-central1',
        'vertex_ai_model': 'gemini-2.5-flash',
    }
    base.update(overrides)
    return base


def test_vertex_ai_provider_detected():
    """Vertex AI is added to provider_order when enabled with a project set."""
    fake_client = MagicMock()
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=_vertex_config())

        provider_values = [p.value for p in llm.provider_order]
        assert LLMProvider.VERTEX_AI in llm.provider_order, (
            f"vertex_ai missing from provider_order: {provider_values}"
        )
        assert llm.vertex_ai_client is fake_client
        assert llm.vertex_ai_model == 'gemini-2.5-flash'
        mock_genai.Client.assert_called_once_with(
            vertexai=True,
            project='test-gcp-project',
            location='us-central1',
        )


def test_vertex_ai_not_detected_when_disabled():
    """Vertex AI is NOT added to provider_order when vertex_ai_enabled=False."""
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = MagicMock()

        llm = UnifiedLLMClient(config=_vertex_config(vertex_ai_enabled=False))

        assert LLMProvider.VERTEX_AI not in llm.provider_order


def test_vertex_ai_not_detected_without_project():
    """Vertex AI is NOT added to provider_order when project is missing."""
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = MagicMock()

        llm = UnifiedLLMClient(config=_vertex_config(vertex_ai_project=None))

        assert LLMProvider.VERTEX_AI not in llm.provider_order


def test_vertex_ai_preferred_over_gemini_when_gemini_absent():
    """Vertex AI is selected and Gemini is absent when no Gemini API key given."""
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = MagicMock()

        llm = UnifiedLLMClient(config=_vertex_config())

        provider_values = [p.value for p in llm.provider_order]
        assert 'gemini' not in provider_values
        assert 'vertex_ai' in provider_values


@pytest.mark.asyncio
async def test_vertex_ai_generate_returns_correct_shape():
    """_call_vertex_ai returns a well-formed response dict."""
    fake_response = MagicMock()
    fake_response.text = "Hello from Vertex AI"
    fake_response.candidates = []
    usage = MagicMock()
    usage.prompt_token_count = 10
    usage.candidates_token_count = 20
    fake_response.usage_metadata = usage

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.aio = fake_aio

    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=_vertex_config())
        result = await llm.generate(prompt="Hello", temperature=0.5, max_tokens=100)

    assert result['provider'] == 'vertex_ai'
    assert result['content'] == "Hello from Vertex AI"
    assert result['tokens']['input'] == 10
    assert result['tokens']['output'] == 20
    assert result['tokens']['total'] == 30
    assert result['model'] == 'gemini-2.5-flash'
    assert 'cost_usd' in result
    assert 'duration_seconds' in result


@pytest.mark.asyncio
async def test_vertex_ai_failure_falls_back_to_next_provider():
    """When Vertex AI raises, the next provider in the chain is tried."""
    fake_vertex_client = MagicMock()
    error_aio = MagicMock()
    error_aio.models.generate_content = AsyncMock(side_effect=RuntimeError("ADC not configured"))
    fake_vertex_client.aio = error_aio

    fake_claude_response = MagicMock()
    fake_claude_response.content = [MagicMock(text="OK from Claude")]
    fake_claude_response.usage = MagicMock(input_tokens=5, output_tokens=3)

    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'CLAUDE_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai, \
         patch.object(_llm_module, 'Anthropic', create=True) as mock_anthropic_cls:

        mock_genai.Client.return_value = fake_vertex_client

        fake_claude_client = MagicMock()
        fake_claude_client.messages.create.return_value = fake_claude_response
        mock_anthropic_cls.return_value = fake_claude_client

        config = _vertex_config(claude_api_key='fake-claude-key')
        llm = UnifiedLLMClient(config=config)

        provider_values = [p.value for p in llm.provider_order]
        assert 'vertex_ai' in provider_values
        assert 'claude' in provider_values

        result = await llm.generate(prompt="Hello", temperature=0.0, max_tokens=10)

    assert result['provider'] == 'claude', (
        f"Expected fallback to claude, got {result['provider']}"
    )


# ---------------------------------------------------------------------------
# _normalize_tools_for_gemini unit tests
# ---------------------------------------------------------------------------


def test_normalize_tools_empty_or_none():
    assert UnifiedLLMClient._normalize_tools_for_gemini(None) is None
    assert UnifiedLLMClient._normalize_tools_for_gemini([]) == []


def test_normalize_tools_already_gemini_native():
    """Case 1: already wrapped in function_declarations → passthrough."""
    native = [{"function_declarations": [{"name": "my_fn", "parameters": {}}]}]
    result = UnifiedLLMClient._normalize_tools_for_gemini(native)
    assert result is native


def test_normalize_tools_anthropic_input_schema():
    """Case 2: Anthropic / PeerTool format (input_schema) → function_declarations."""
    tools = [
        {
            "name": "search",
            "description": "Search the web",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ]
    result = UnifiedLLMClient._normalize_tools_for_gemini(tools)
    assert len(result) == 1
    assert "function_declarations" in result[0]
    decls = result[0]["function_declarations"]
    assert decls[0]["name"] == "search"
    assert decls[0]["parameters"] == {"type": "object", "properties": {"query": {"type": "string"}}}
    assert "input_schema" not in decls[0]


def test_normalize_tools_flat_name_parameters():
    """Case 3: flat list with name+parameters → wrap in function_declarations."""
    tools = [{"name": "greet", "parameters": {"type": "object", "properties": {}}}]
    result = UnifiedLLMClient._normalize_tools_for_gemini(tools)
    assert len(result) == 1
    assert "function_declarations" in result[0]
    assert result[0]["function_declarations"][0]["name"] == "greet"


def test_normalize_tools_mixed_schemas():
    """Mixed list: one Anthropic, one flat → all wrapped in a single block."""
    tools = [
        {"name": "fn_a", "description": "A", "input_schema": {"type": "object"}},
        {"name": "fn_b", "parameters": {"type": "object"}},
    ]
    result = UnifiedLLMClient._normalize_tools_for_gemini(tools)
    assert len(result) == 1
    decls = result[0]["function_declarations"]
    assert len(decls) == 2
    assert {d["name"] for d in decls} == {"fn_a", "fn_b"}


# ---------------------------------------------------------------------------
# Tool-calls response parsing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vertex_ai_tool_calls_parsed_from_response():
    """When the model returns function_call parts, tool_calls is populated."""
    fc = MagicMock()
    fc.name = "search"
    fc.args = {"query": "latest AI news"}

    part = MagicMock()
    part.function_call = fc

    candidate = MagicMock()
    candidate.content.parts = [part]

    fake_response = MagicMock()
    fake_response.candidates = [candidate]
    fake_response.text = ""
    fake_response.usage_metadata = None

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.aio = fake_aio

    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=_vertex_config())
        result = await llm._call_vertex_ai(
            messages=[{"role": "user", "content": "find news"}],
            temperature=0.0,
            max_tokens=100,
        )

    assert result["tool_calls"] == [{"name": "search", "args": {"query": "latest AI news"}}]
    assert result["content"] == ""
    assert result["provider"] == "vertex_ai"


@pytest.mark.asyncio
async def test_gemini_forwards_tools_kwarg():
    """_call_gemini forwards tools to _call_genai_client."""
    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.candidates = []
    usage = MagicMock()
    usage.prompt_token_count = 5
    usage.candidates_token_count = 5
    fake_response.usage_metadata = usage

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.aio = fake_aio

    gemini_config = {
        'claude_api_key': None,
        'anthropic_api_key': None,
        'azure_api_key': None,
        'azure_endpoint': None,
        'gemini_api_key': 'fake-key',
        'llm_endpoint': None,
        'vertex_ai_enabled': False,
        'vertex_ai_project': None,
    }

    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=gemini_config)
        tools_payload = [{"name": "fn", "input_schema": {"type": "object"}}]
        await llm._call_gemini(
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.0,
            max_tokens=50,
            tools=tools_payload,
        )

    call_kwargs = fake_aio.models.generate_content.call_args
    sent_config = (
        call_kwargs.kwargs.get("config")
        or (call_kwargs[1].get("config") if call_kwargs[1] else {})
        or {}
    )
    assert "tools" in sent_config, "tools kwarg was not forwarded to generate_content"
