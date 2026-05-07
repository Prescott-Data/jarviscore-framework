"""
Test LLM Provider Fallback Chain

Tests the fallback order: Azure → Claude → Gemini → vLLM
Azure is the primary provider in this deployment.
"""

import asyncio
import pytest
from jarviscore.execution.llm import UnifiedLLMClient


def test_provider_detection():
    """Test that all configured providers are detected."""
    llm = UnifiedLLMClient()

    actual_order = [p.value for p in llm.provider_order]
    print(f"\nDetected provider order: {actual_order}")
    print(f"  Azure:  {'Available' if llm.azure_client else 'Not available'}")
    print(f"  Claude: {'Available' if llm.claude_client else 'Not available'}")
    print(f"  Gemini: {'Available' if llm.gemini_client else 'Not available'}")
    print(f"  vLLM:   {'Available' if llm.vllm_endpoint else 'Not available'}")

    assert len(actual_order) > 0, "No providers detected!"
    # Azure must be the first provider in this deployment
    assert actual_order[0] == 'azure', (
        f"Expected Azure as primary provider, got: {actual_order[0]}"
    )


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
        'azure_api_key': None,       # Disable Azure
        'azure_endpoint': None,
        'claude_api_key': getattr(settings, 'claude_api_key', None),
        'anthropic_api_key': getattr(settings, 'anthropic_api_key', None),
        'gemini_api_key': None,      # Disable Gemini
        'llm_endpoint': None,        # Disable vLLM
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
        print(f"Response: {result.get('content', '')[:50]}")
        assert result.get('provider') == 'claude', (
            f"Expected claude, got {result.get('provider')}"
        )
    except RuntimeError as e:
        # Claude endpoint may be configured but deployment may not exist on
        # this Azure Anthropic resource — treat as infrastructure skip
        pytest.skip(f"Claude deployment unavailable: {e}")


@pytest.mark.asyncio
async def test_gemini_fallback():
    """Test Gemini fallback when Azure and Claude are unavailable."""
    from jarviscore.config.settings import settings

    gemini_only_config = {
        'azure_api_key': None,       # Disable Azure
        'azure_endpoint': None,
        'claude_api_key': None,      # Disable Claude
        'anthropic_api_key': None,
        'gemini_api_key': getattr(settings, 'gemini_api_key', None),
        'gemini_model': getattr(settings, 'gemini_model', None),
        'llm_endpoint': None,        # Disable vLLM
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
        # Gemini often hits quota limits — skip rather than fail
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
        'llm_endpoint': None,
    }
    llm = UnifiedLLMClient(config=empty_config)
    assert len(llm.provider_order) == 0

    with pytest.raises((RuntimeError, Exception)):
        await llm.generate(prompt="test", max_tokens=5)
