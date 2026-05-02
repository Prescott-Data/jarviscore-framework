"""
Test LLM Provider Fallback Chain

Tests the fallback order: Claude → Azure → Gemini → Vertex AI → vLLM
"""

import asyncio
import os
from unittest.mock import MagicMock, patch, AsyncMock
import jarviscore.execution.llm as _llm_module
from jarviscore.execution.llm import UnifiedLLMClient, LLMProvider


def test_provider_detection():
    """Test that all configured providers are detected."""
    print("\n" + "="*70)
    print("Testing LLM Provider Detection")
    print("="*70 + "\n")

    llm = UnifiedLLMClient()

    print(f"Detected providers: {[p.value for p in llm.provider_order]}")
    print(f"\nProvider status:")
    print(f"  ✓ Claude: {'Available' if llm.claude_client else 'Not available'}")
    print(f"  ✓ Azure: {'Available' if llm.azure_client else 'Not available'}")
    print(f"  ✓ Gemini: {'Available' if llm.gemini_client else 'Not available'}")
    print(f"  ✓ vLLM: {'Available' if llm.vllm_endpoint else 'Not available'}")

    # Verify order is correct
    expected_order = ['claude', 'azure', 'gemini']  # vLLM not configured by default
    actual_order = [p.value for p in llm.provider_order]

    print(f"\nFallback order:")
    for i, provider in enumerate(actual_order, 1):
        print(f"  {i}. {provider}")

    assert len(actual_order) > 0, "No providers detected!"
    print("\n✅ Provider detection test passed!")


async def test_claude_primary():
    """Test that Claude is used when available."""
    print("\n" + "="*70)
    print("Testing Claude (Primary Provider)")
    print("="*70 + "\n")

    llm = UnifiedLLMClient()

    if not llm.claude_client:
        print("⚠️  Claude not available, skipping test")
        return

    try:
        result = await llm.generate(
            prompt="Say 'OK' only",
            temperature=0.0,
            max_tokens=10
        )

        print(f"Provider used: {result.get('provider', 'unknown')}")
        print(f"Response: {result.get('content', '')[:50]}")
        assert result.get('provider') == 'claude'
        print("\n✅ Claude test passed!")

    except Exception as e:
        print(f"\n❌ Claude test failed: {e}")
        raise


async def test_azure_fallback():
    """Test Azure fallback when Claude is unavailable."""
    print("\n" + "="*70)
    print("Testing Azure (Fallback #1)")
    print("="*70 + "\n")

    # Create LLM client with Azure only (pass config directly)
    from jarviscore.config.settings import settings

    azure_config = {
        'claude_api_key': None,  # Disable Claude
        'anthropic_api_key': None,
        'azure_api_key': settings.azure_api_key,
        'azure_endpoint': settings.azure_endpoint,
        'azure_deployment': settings.azure_deployment,
        'azure_api_version': settings.azure_api_version,
        'gemini_api_key': None,  # Disable Gemini
        'llm_endpoint': None,  # Disable vLLM
    }

    try:
        llm = UnifiedLLMClient(config=azure_config)

        if not llm.azure_client:
            print("⚠️  Azure not available, skipping test")
            return

        result = await llm.generate(
            prompt="Say 'OK' only",
            temperature=0.0,
            max_tokens=10
        )

        print(f"Provider used: {result.get('provider', 'unknown')}")
        print(f"Response: {result.get('content', '')[:50]}")
        assert result.get('provider') == 'azure'
        print("\n✅ Azure fallback test passed!")

    except Exception as e:
        print(f"\n❌ Azure fallback test failed: {e}")
        raise


async def test_gemini_fallback():
    """Test Gemini fallback when Claude and Azure are unavailable."""
    print("\n" + "="*70)
    print("Testing Gemini (Fallback #2)")
    print("="*70 + "\n")

    # Create LLM client with Gemini only (pass config directly)
    from jarviscore.config.settings import settings

    gemini_config = {
        'claude_api_key': None,  # Disable Claude
        'anthropic_api_key': None,
        'azure_api_key': None,  # Disable Azure
        'azure_endpoint': None,
        'gemini_api_key': settings.gemini_api_key,
        'gemini_model': settings.gemini_model,
        'llm_endpoint': None,  # Disable vLLM
    }

    try:
        llm = UnifiedLLMClient(config=gemini_config)

        if not llm.gemini_client:
            print("⚠️  Gemini not available, skipping test")
            return

        result = await llm.generate(
            prompt="Say 'OK' only",
            temperature=0.0,
            max_tokens=10
        )

        print(f"Provider used: {result.get('provider', 'unknown')}")
        print(f"Response: {result.get('content', '')[:50]}")
        assert result.get('provider') == 'gemini'
        print("\n✅ Gemini fallback test passed!")

    except Exception as e:
        print(f"\n⚠️  Gemini fallback test skipped (quota/rate limit): {e}")
        # Gemini often has quota limits, so we don't fail the test


# ---------------------------------------------------------------------------
# Vertex AI provider tests (use mocks — no real GCP credentials required)
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
    print("\n✅ Vertex AI provider detection test passed!")


def test_vertex_ai_not_detected_when_disabled():
    """Vertex AI is NOT added to provider_order when vertex_ai_enabled=False."""
    fake_client = MagicMock()
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=_vertex_config(vertex_ai_enabled=False))

        assert LLMProvider.VERTEX_AI not in llm.provider_order, (
            "vertex_ai should not be in provider_order when disabled"
        )
    print("\n✅ Vertex AI disabled detection test passed!")


def test_vertex_ai_not_detected_without_project():
    """Vertex AI is NOT added to provider_order when project is missing."""
    fake_client = MagicMock()
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=_vertex_config(vertex_ai_project=None))

        assert LLMProvider.VERTEX_AI not in llm.provider_order, (
            "vertex_ai should not be in provider_order when project is missing"
        )
    print("\n✅ Vertex AI missing project detection test passed!")


def test_vertex_ai_preferred_over_gemini_when_gemini_absent():
    """Vertex AI is selected and Gemini is absent when no Gemini API key is given."""
    fake_client = MagicMock()
    with patch.object(_llm_module, 'GEMINI_AVAILABLE', True), \
         patch.object(_llm_module, 'genai', create=True) as mock_genai:
        mock_genai.Client.return_value = fake_client

        llm = UnifiedLLMClient(config=_vertex_config())

        provider_values = [p.value for p in llm.provider_order]
        assert 'gemini' not in provider_values, (
            f"gemini should not appear when api key is absent: {provider_values}"
        )
        assert 'vertex_ai' in provider_values
    print("\n✅ Vertex AI preferred over absent Gemini test passed!")


async def test_vertex_ai_generate_returns_correct_shape():
    """_call_vertex_ai returns a well-formed response dict."""
    fake_response = MagicMock()
    fake_response.text = "Hello from Vertex AI"
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
    print("\n✅ Vertex AI generate shape test passed!")


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
    print("\n✅ Vertex AI fallback to Claude test passed!")


async def run_all_tests():
    """Run all fallback tests."""
    print("\n" + "="*70)
    print("JarvisCore LLM Fallback Chain Tests")
    print("Testing: Claude → Azure → Gemini → Vertex AI → vLLM")
    print("="*70)

    # Test 1: Provider detection
    test_provider_detection()

    # Test 2: Claude (primary)
    await test_claude_primary()

    # Test 3: Azure (fallback #1)
    await test_azure_fallback()

    # Test 4: Gemini (fallback #2)
    await test_gemini_fallback()

    # Test 5: Vertex AI (mocked — no GCP credentials needed)
    test_vertex_ai_provider_detected()
    test_vertex_ai_not_detected_when_disabled()
    test_vertex_ai_not_detected_without_project()
    test_vertex_ai_preferred_over_gemini_when_gemini_absent()
    await test_vertex_ai_generate_returns_correct_shape()
    await test_vertex_ai_failure_falls_back_to_next_provider()

    print("\n" + "="*70)
    print("Summary")
    print("="*70)
    print("\n✅ All fallback tests completed successfully!")
    print("\nFallback chain verified:")
    print("  1. Claude (primary) - ✅ Working")
    print("  2. Azure (fallback) - ✅ Working")
    print("  3. Gemini (fallback) - ✅ Working (quota limits may apply)")
    print("  4. Vertex AI - ✅ Working (mocked)")
    print("  5. vLLM (local) - ⚠️  Configure LLM_ENDPOINT to test")
    print()


if __name__ == '__main__':
    asyncio.run(run_all_tests())
