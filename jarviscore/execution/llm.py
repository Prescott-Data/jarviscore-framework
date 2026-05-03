"""
Unified LLM Client - All providers in one file with zero-config setup
Supports: vLLM, Azure OpenAI, Gemini, Vertex AI, Claude with automatic fallback
"""
import asyncio
import aiohttp
import logging
import time
from typing import Optional, Dict, List, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Try importing optional LLM SDKs
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.debug("Gemini SDK not available (pip install google-genai)")

try:
    from openai import AsyncAzureOpenAI
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False
    logger.debug("Azure OpenAI SDK not available (pip install openai)")

try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False
    logger.debug("Claude SDK not available (pip install anthropic)")


class LLMProvider(Enum):
    """Available LLM providers."""
    VLLM = "vllm"
    AZURE = "azure"
    GEMINI = "gemini"
    VERTEX_AI = "vertex_ai"
    CLAUDE = "claude"


# Token pricing per 1M tokens (updated 2025)
TOKEN_PRICING = {
    # Azure OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.00, "cached": 1.25},
    "gpt-4.1": {"input": 2.00, "output": 8.00, "cached": 0.50},
    "dromos-gpt-4.1": {"input": 2.00, "output": 8.00, "cached": 0.50},
    "o1": {"input": 15.00, "output": 60.00, "cached": 7.50},
    "o3": {"input": 10.00, "output": 40.00, "cached": 2.50},
    "gpt-4": {"input": 30.00, "output": 60.00, "cached": 15.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "cached": 0.25},
    # Google Gemini models
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cached": 0.03},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "cached": 0.31},
    "gemini-1.5-flash": {"input": 0.10, "output": 0.30, "cached": 0.03},
    # Vertex AI (same models, same pricing — accessed via ADC instead of API key)
    # Vertex AI (same models, same pricing — accessed via ADC instead of API key)
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60, "cached": 0.04},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "cached": 0.31},
    "gemini-3.1-pro": {"input": 1.25, "output": 10.00, "cached": 0.31},
    "gemini-3.1-pro-preview": {"input": 1.25, "output": 10.00, "cached": 0.31},
    # Anthropic Claude models
    "claude-opus-4": {"input": 15.00, "output": 75.00, "cached": 3.75},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "cached": 0.75},
    "claude-haiku-3.5": {"input": 1.00, "output": 5.00, "cached": 0.25},
}


class UnifiedLLMClient:
    """
    Zero-config LLM client with automatic provider detection and fallback.

    Philosophy: Developer writes NOTHING. Framework tries providers in order:
    1. vLLM (local, free)
    2. Azure OpenAI (if configured)
    3. Gemini (if configured)
    4. Claude (if configured)

    Example:
        client = UnifiedLLMClient()
        response = await client.generate("Write Python code to add 2+2")
        # Framework automatically picks best available provider
    """

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize LLM client with zero-config defaults.

        Args:
            config: Optional config dict. If None, auto-detects from environment via Pydantic.
        """
        # Load from Pydantic settings first
        from jarviscore.config import settings

        # Merge: Pydantic settings as base, config dict as override
        self.config = settings.model_dump()
        if config:
            self.config.update(config)

        # Provider clients
        self.vllm_endpoint = None
        self.azure_client = None
        self.gemini_client = None
        self.vertex_ai_client = None
        self.claude_client = None

        # Provider order (tries in this sequence)
        self.provider_order = []

        # Initialize all available providers
        self._setup_providers()

        logger.info(f"LLM Client initialized with providers: {[p.value for p in self.provider_order]}")

    def _setup_providers(self):
        """Auto-detect and setup available LLM providers."""

        # 1. Try Azure OpenAI first (primary provider)
        if AZURE_AVAILABLE:
            azure_key = self.config.get('azure_api_key') or self.config.get('azure_openai_key')
            azure_endpoint = self.config.get('azure_endpoint') or self.config.get('azure_openai_endpoint')

            if azure_key and azure_endpoint:
                try:
                    self.azure_client = AsyncAzureOpenAI(
                        api_key=azure_key,
                        azure_endpoint=azure_endpoint,
                        api_version=self.config.get('azure_api_version', '2025-01-01-preview'),
                        timeout=self.config.get('llm_timeout', 120)
                    )
                    self.provider_order.append(LLMProvider.AZURE)
                    logger.info(f"✓ Azure OpenAI provider available (primary): {azure_endpoint}")
                except Exception as e:
                    logger.warning(f"Failed to setup Azure OpenAI: {e}")

        # 2. Try Claude (fallback #1)
        if CLAUDE_AVAILABLE:
            claude_key = self.config.get('claude_api_key') or self.config.get('anthropic_api_key')
            claude_endpoint = self.config.get('claude_endpoint')
            if claude_key:
                try:
                    if claude_endpoint:
                        self.claude_client = Anthropic(
                            api_key=claude_key,
                            base_url=claude_endpoint
                        )
                        logger.info(f"✓ Claude provider available (fallback): {claude_endpoint}")
                    else:
                        self.claude_client = Anthropic(api_key=claude_key)
                        logger.info("✓ Claude provider available (fallback)")
                    self.provider_order.append(LLMProvider.CLAUDE)
                except Exception as e:
                    logger.warning(f"Failed to setup Claude: {e}")

        # 3. Try vLLM (local, free)
        vllm_endpoint = self.config.get('llm_endpoint') or self.config.get('vllm_endpoint')
        if vllm_endpoint:
            self.vllm_endpoint = vllm_endpoint.rstrip('/')
            self.provider_order.append(LLMProvider.VLLM)
            logger.info(f"✓ vLLM provider available: {self.vllm_endpoint}")

        # 4. Try Gemini (API key auth)
        if GEMINI_AVAILABLE:
            gemini_key = self.config.get('gemini_api_key')
            if gemini_key:
                try:
                    self.gemini_client = genai.Client(api_key=gemini_key)
                    self.gemini_model = self.config.get('gemini_model', 'gemini-2.0-flash')
                    self.provider_order.append(LLMProvider.GEMINI)
                    logger.info(f"✓ Gemini provider available: {self.gemini_model}")
                except Exception as e:
                    logger.warning(f"Failed to setup Gemini: {e}")

        # 5. Try Vertex AI (GCP-native, uses Application Default Credentials)
        if GEMINI_AVAILABLE:
            vertex_enabled = self.config.get('vertex_ai_enabled', False)
            vertex_project = self.config.get('vertex_ai_project')
            if vertex_enabled and vertex_project:
                try:
                    self.vertex_ai_client = genai.Client(
                        vertexai=True,
                        project=vertex_project,
                        location=self.config.get('vertex_ai_location', 'us-central1'),
                    )
                    self.vertex_ai_model = self.config.get('vertex_ai_model', 'gemini-2.5-flash')
                    self.provider_order.append(LLMProvider.VERTEX_AI)
                    logger.info(f"✓ Vertex AI provider available: {self.vertex_ai_model} (project: {vertex_project})")
                except Exception as e:
                    logger.warning(f"Failed to setup Vertex AI: {e}")

        if not self.provider_order:
            logger.warning(
                "⚠️  No LLM providers configured! Set at least one:\n"
                "  - llm_endpoint for vLLM\n"
                "  - azure_api_key + azure_endpoint for Azure\n"
                "  - gemini_api_key for Gemini\n"
                "  - vertex_ai_enabled + vertex_ai_project for Vertex AI\n"
                "  - claude_api_key for Claude"
            )

    async def generate(
        self,
        prompt: str,
        messages: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate completion with automatic provider fallback.

        Args:
            prompt: Text prompt (if messages not provided)
            messages: OpenAI-style message list [{"role": "user", "content": "..."}]
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific options

        Returns:
            {
                "content": "generated text",
                "provider": "vllm|azure|gemini|vertex_ai|claude",
                "tokens": {"input": 100, "output": 200, "total": 300},
                "cost_usd": 0.015,
                "model": "gpt-4o"
            }
        """
        # Convert prompt to messages if needed
        if not messages:
            messages = [{"role": "user", "content": prompt}]

        # Try each provider in order
        last_error = None
        for provider in self.provider_order:
            try:
                logger.debug(f"Trying provider: {provider.value}")

                if provider == LLMProvider.VLLM:
                    return await self._call_vllm(messages, temperature, max_tokens, **kwargs)
                elif provider == LLMProvider.AZURE:
                    return await self._call_azure(messages, temperature, max_tokens, **kwargs)
                elif provider == LLMProvider.GEMINI:
                    return await self._call_gemini(messages, temperature, max_tokens, **kwargs)
                elif provider == LLMProvider.VERTEX_AI:
                    return await self._call_vertex_ai(messages, temperature, max_tokens, **kwargs)
                elif provider == LLMProvider.CLAUDE:
                    return await self._call_claude(messages, temperature, max_tokens, **kwargs)

            except Exception as e:
                last_error = e
                logger.warning(f"Provider {provider.value} failed: {e}")
                continue

        # All providers failed
        raise RuntimeError(
            f"All LLM providers failed. Last error: {last_error}\n"
            f"Tried: {[p.value for p in self.provider_order]}"
        )

    async def _call_vllm(self, messages: List[Dict], temperature: float, max_tokens: int, **kwargs) -> Dict:
        """Call vLLM endpoint."""
        if not self.vllm_endpoint:
            raise RuntimeError("vLLM endpoint not configured")

        endpoint = self.vllm_endpoint
        if not endpoint.endswith('/v1/chat/completions'):
            endpoint = f"{endpoint}/v1/chat/completions"

        payload = {
            "model": self.config.get('llm_model', 'default'),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        timeout = aiohttp.ClientTimeout(total=self.config.get('llm_timeout', 120))
        start_time = time.time()

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, json=payload) as response:
                if response.status != 200:
                    error = await response.text()
                    raise RuntimeError(f"vLLM error {response.status}: {error}")

                data = await response.json()
                duration = time.time() - start_time

                content = data['choices'][0]['message']['content']
                usage = data.get('usage', {})

                return {
                    "content": content,
                    "provider": "vllm",
                    "tokens": {
                        "input": usage.get('prompt_tokens', 0),
                        "output": usage.get('completion_tokens', 0),
                        "total": usage.get('total_tokens', 0)
                    },
                    "cost_usd": 0.0,  # vLLM is free (local)
                    "model": payload['model'],
                    "duration_seconds": duration
                }

    async def _call_azure(self, messages: List[Dict], temperature: float, max_tokens: int, **kwargs) -> Dict:
        """Call Azure OpenAI."""
        if not self.azure_client:
            raise RuntimeError("Azure client not initialized")

        # Allow model kwarg to override deployment (for kernel model routing)
        deployment = kwargs.pop('model', None) or self.config.get('azure_deployment', 'gpt-4o')
        start_time = time.time()

        response = await self.azure_client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )

        duration = time.time() - start_time
        content = response.choices[0].message.content
        usage = response.usage

        # Calculate cost
        pricing = TOKEN_PRICING.get(deployment, {"input": 3.0, "output": 15.0})
        cost = (usage.prompt_tokens * pricing['input'] +
                usage.completion_tokens * pricing['output']) / 1_000_000

        return {
            "content": content,
            "provider": "azure",
            "tokens": {
                "input": usage.prompt_tokens,
                "output": usage.completion_tokens,
                "total": usage.total_tokens
            },
            "cost_usd": cost,
            "model": deployment,
            "duration_seconds": duration
        }

    async def _call_genai_client(
        self,
        client,
        model_name: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        provider_label: str,
        default_pricing: Dict,
        **kwargs,
    ) -> Dict:
        """
        Shared helper for google.genai generate_content calls (Gemini and Vertex AI).

        Handles the request, usage extraction, token estimation fallback, and cost
        calculation so both paths stay consistent.

        Args:
            client: A ``genai.Client`` instance (standard or Vertex AI).
            model_name: Model identifier string (e.g. ``"gemini-2.5-flash"``).
            prompt: Plain-text prompt to send.
            temperature: Sampling temperature (0–1).
            max_tokens: Maximum tokens to generate.
            provider_label: Value for the ``"provider"`` key in the returned dict.
            default_pricing: Fallback pricing dict used when *model_name* is not
                found in ``TOKEN_PRICING``.  Must contain ``"input"`` and
                ``"output"`` keys (cost per 1M tokens).
            **kwargs: Additional arguments forwarded to generate_content
                (e.g. ``tools`` for function-calling support).
        """
        start_time = time.time()

        # Build generate_content kwargs, forwarding tools if provided
        gen_kwargs = {
            "model": model_name,
            "contents": prompt,
            "config": {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        }
        tools = kwargs.get('tools', None)
        if tools:
            gen_kwargs["tools"] = tools

        response = await client.aio.models.generate_content(**gen_kwargs)
        duration = time.time() - start_time

        # Check if the model responded with tool calls instead of text
        tool_calls = []
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'function_call') and part.function_call:
                    tool_calls.append({
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args) if part.function_call.args else {}
                    })

        content = response.text if not tool_calls else ""

        # Get usage metadata if available, otherwise estimate
        usage_metadata = getattr(response, 'usage_metadata', None)
        if usage_metadata:
            input_tokens = getattr(usage_metadata, 'prompt_token_count', 0)
            output_tokens = getattr(usage_metadata, 'candidates_token_count', 0)
        else:
            input_tokens = int(len(prompt.split()) * 1.3)
            output_tokens = int(len(content.split()) * 1.3) if content else 0

        pricing = TOKEN_PRICING.get(model_name, default_pricing)
        cost = (input_tokens * pricing['input'] + output_tokens * pricing['output']) / 1_000_000

        return {
            "content": content,
            "provider": provider_label,
            "tool_calls": tool_calls,
            "tokens": {
                "input": int(input_tokens),
                "output": int(output_tokens),
                "total": int(input_tokens + output_tokens),
            },
            "cost_usd": cost,
            "model": model_name,
            "duration_seconds": duration,
        }

    async def _call_gemini(self, messages: List[Dict], temperature: float, max_tokens: int, **kwargs) -> Dict:
        """Call Google Gemini using the new google.genai SDK."""
        if not self.gemini_client:
            raise RuntimeError("Gemini client not initialized")

        prompt = self._messages_to_prompt(messages)
        return await self._call_genai_client(
            client=self.gemini_client,
            model_name=self.gemini_model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_label="gemini",
            default_pricing={"input": 0.10, "output": 0.30},
        )

    async def _call_vertex_ai(self, messages: List[Dict], temperature: float, max_tokens: int, **kwargs) -> Dict:
        """Call Gemini via Vertex AI using Application Default Credentials."""
        if not self.vertex_ai_client:
            raise RuntimeError("Vertex AI client not initialized")

        prompt = self._messages_to_prompt(messages)
        return await self._call_genai_client(
            client=self.vertex_ai_client,
            model_name=self.vertex_ai_model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_label="vertex_ai",
            default_pricing={"input": 0.15, "output": 0.60},
            **kwargs,
        )

    async def _call_claude(self, messages: List[Dict], temperature: float, max_tokens: int, **kwargs) -> Dict:
        """Call Anthropic Claude."""
        if not self.claude_client:
            raise RuntimeError("Claude client not initialized")

        # Separate system message from conversation
        system_msg = None
        conv_messages = []
        for msg in messages:
            if msg['role'] == 'system':
                system_msg = msg['content']
            else:
                conv_messages.append(msg)

        model = kwargs.pop('model', None) or self.config.get('claude_model', 'claude-sonnet-4')
        start_time = time.time()

        # Prepare request kwargs
        request_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conv_messages
        }

        # Only add system if it exists (Claude API requires it to be string or not present)
        if system_msg:
            request_kwargs["system"] = system_msg

        response = await asyncio.to_thread(
            self.claude_client.messages.create,
            **request_kwargs
        )

        duration = time.time() - start_time
        content = response.content[0].text

        # Calculate cost
        pricing = TOKEN_PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost = (response.usage.input_tokens * pricing['input'] +
                response.usage.output_tokens * pricing['output']) / 1_000_000

        return {
            "content": content,
            "provider": "claude",
            "tokens": {
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
                "total": response.usage.input_tokens + response.usage.output_tokens
            },
            "cost_usd": cost,
            "model": model,
            "duration_seconds": duration
        }

    def _messages_to_prompt(self, messages: List[Dict]) -> str:
        """Convert OpenAI message format to plain text prompt."""
        parts = []
        for msg in messages:
            role = msg['role']
            content = msg['content']
            if role == 'system':
                parts.append(f"System: {content}")
            elif role == 'user':
                parts.append(f"User: {content}")
            elif role == 'assistant':
                parts.append(f"Assistant: {content}")
        return "\n\n".join(parts)


def create_llm_client(config: Optional[Dict] = None) -> UnifiedLLMClient:
    """
    Factory function to create LLM client.

    Zero-config: Just call this and it auto-detects providers.
    """
    return UnifiedLLMClient(config)
