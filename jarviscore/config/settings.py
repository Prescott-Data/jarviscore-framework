"""
JarvisCore Framework Configuration

Configuration can be provided via:
1. Environment variables / .env file (shared settings: LLM keys, Redis URL, storage)
2. Direct config dictionary passed to Mesh (always takes precedence)

Per-process P2P settings (bind_port, bind_host, seed_nodes) use the JARVISCORE_
prefix so they never collide with env vars read by the swim package at import time.
For multi-node deployments these should be set explicitly in each Mesh config dict
or as per-process env vars — not in a shared .env file.

    # Recommended: explicit per-process config dict
    mesh = Mesh(mode="distributed", config={
        'bind_host': '0.0.0.0',
        'bind_port': 7949,
        'seed_nodes': '127.0.0.1:7949',
    })

    # Alternative: per-process env vars (set at launch, not in .env)
    JARVISCORE_BIND_PORT=7949 python ex2_synthesizer.py
    JARVISCORE_BIND_PORT=7946 python ex2_research_node1.py
"""
import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Framework configuration with zero-config defaults.

    P2P bind settings use JARVISCORE_ prefixed env vars to avoid collisions
    with the swim package which reads BIND_PORT/BIND_HOST from the environment
    at import time. All other settings retain their standard names.
    """

    # === P2P Settings ===
    # Read from JARVISCORE_* env vars — never from bare BIND_PORT/BIND_HOST
    # which the swim package may populate from .env at import time.
    # For multi-node: always pass bind_port explicitly in Mesh config dict.
    node_name: str = Field("jarviscore-node", validation_alias="jarviscore_node_name")
    bind_host: str = Field("127.0.0.1",       validation_alias="jarviscore_bind_host")
    bind_port: int = Field(7946,              validation_alias="jarviscore_bind_port")
    seed_nodes: str = Field("",               validation_alias="jarviscore_seed_nodes")
    # Comma-separated "host:port,host:port"
    p2p_enabled: bool = True
    zmq_port_offset: int = 1000
    transport_type: str = "hybrid"  # udp, tcp, or hybrid

    # === Keepalive Settings ===
    keepalive_enabled: bool = True
    keepalive_interval: int = 90  # seconds
    keepalive_timeout: int = 10
    activity_suppress_window: int = 60

    # === Execution Settings ===
    max_retries: int = 3
    max_repair_attempts: int = 3
    execution_timeout: int = 300  # seconds

    # === Sandbox Settings ===
    sandbox_mode: str = "local"  # "local" or "remote"
    sandbox_service_url: Optional[str] = None  # URL for remote sandbox

    # === Storage Settings ===
    log_directory: str = "./logs"

    # === LLM Configuration ===
    llm_timeout: float = 120.0
    llm_temperature: float = 0.7
    # Max concurrent LLM calls across the whole process (0 = unlimited).
    # Set to match your deployment's RPM ÷ expected_avg_call_seconds.
    # e.g. RPM=60, avg_latency=5s → 60/12 = 5 concurrent max.
    # Prevents thundering-herd 429s in multi-agent deployments.
    llm_max_concurrent: int = 0  # 0 = unlimited (backward-compatible default)
    # 429 retry backoff: max retries before giving up on a rate-limited provider.
    # Delay formula: min(base_delay * 2^attempt, 60s).
    llm_max_retries_429: int = 4
    llm_429_base_delay: float = 2.0



    # Claude
    claude_api_key: Optional[str] = None
    claude_endpoint: Optional[str] = None
    claude_model: str = "claude-sonnet-4"
    anthropic_api_key: Optional[str] = None  # Alias for claude_api_key

    # Azure OpenAI
    azure_api_key: Optional[str] = None
    azure_openai_key: Optional[str] = None  # Alias
    azure_endpoint: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None  # Alias
    azure_deployment: str = "gpt-4o"
    azure_api_version: str = "2024-02-15-preview"

    # Gemini
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_temperature: float = 0.1
    gemini_timeout: float = 30.0

    # vLLM
    llm_endpoint: Optional[str] = None
    vllm_endpoint: Optional[str] = None  # Alias
    llm_model: str = "default"

    # === Redis ===
    redis_url: Optional[str] = None  # redis://host:port/db (takes precedence)
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0
    redis_context_ttl_days: int = 7

    # === Blob Storage ===
    storage_backend: str = "local"  # "local" or "azure"
    storage_base_path: str = "./blob_storage"
    azure_storage_connection_string: Optional[str] = None
    azure_storage_container: str = "jarviscore"

    # === Telemetry ===
    telemetry_enabled: bool = True
    telemetry_trace_dir: str = "./traces"
    prometheus_enabled: bool = False
    prometheus_port: int = 9090

    # === Kernel (internal to AutoAgent) ===
    kernel_max_turns: int = 30
    kernel_max_total_tokens: int = 80000
    kernel_thinking_budget: int = 56000
    kernel_action_budget: int = 24000
    kernel_wall_clock_ms: int = 180000

    # === LLM Model Routing ===
    # Azure OpenAI deployments for kernel subagent routing.
    #
    # Two-tier (default — always works):
    #   coding_model  → CoderSubAgent (code generation)
    #   task_model    → Researcher, Communicator, Browser
    #
    # Multi-tier (optional — pass complexity= in workflow task dicts):
    #   task_model_nano     → fast + cheap  (classify, summarise, route)
    #   task_model_standard → general tasks (default when complexity unset)
    #   task_model_heavy    → deep reasoning, long context, planning
    #
    # Example usage in workflow:
    #   {"agent": "researcher", "task": "...", "complexity": "heavy"}
    #
    # Falls back to task_model when a tier-specific setting is not configured.
    coding_model: str = "dromos-gpt-4.1"       # Heavy lifting: code gen (GPT-4.1)
    task_model: str = "gpt-4o"                 # General: research, communication
    task_model_nano: Optional[str] = None      # TASK_MODEL_NANO — fast/cheap tier
    task_model_standard: Optional[str] = None  # TASK_MODEL_STANDARD — default tier
    task_model_heavy: Optional[str] = None     # TASK_MODEL_HEAVY — deep reasoning
    # Legacy aliases (still work if set)
    claude_task_model: str = ""
    claude_coding_model: str = ""

    # === Mailbox ===
    mailbox_max_messages: int = 100
    mailbox_poll_interval: float = 0.5

    # === Function Registry ===
    registry_verified_threshold: int = 1
    registry_golden_threshold: int = 5
    registry_max_cache_size: int = 500

    # === Human-in-the-Loop ===
    hitl_enabled: bool = False
    hitl_max_confidence: float = 0.8
    hitl_min_risk_score: float = 0.7

    # === Auth / Nexus ===
    # Nexus is the ONLY auth path — there is no dev-mode bypass.
    # All credential types (OAuth, api_key, basic_auth) go through Nexus.
    # Set NEXUS_GATEWAY_URL to enable any connected-app functionality.
    nexus_gateway_url: Optional[str] = None  # NEXUS_GATEWAY_URL — required for connected apps
    nexus_return_url: str = "http://localhost:8000/oauth/callback"  # Broker redirects here after consent
    nexus_default_user_id: str = "jarviscore-agent"
    nexus_enabled: Optional[bool] = None  # NEXUS_ENABLED — explicit override; None = auto-detect from nexus_gateway_url
    auth_strategy_cache_ttl: int = 300   # Seconds before re-fetching strategy from Gateway
    auth_flow_timeout: int = 300         # Max seconds to wait for OAuth consent
    auth_poll_interval: float = 2.0      # Seconds between Gateway status polls
    auth_open_browser: bool = True       # Try to open system browser for OAuth flows

    # === Memory / Athena ===
    # Athena is the ONLY persistent memory path — STM, MTM, and LTM graph.
    # When ATHENA_URL is not set, JarvisCore falls back to Redis-only episodic +
    # Blob LTM (EpisodicLedger + LongTermMemory). Setting ATHENA_URL upgrades
    # all agents to full three-tier memory automatically.
    athena_url: Optional[str] = None           # ATHENA_URL — e.g. http://localhost:8080
    athena_tenant_id: str = "default"          # Namespace for multi-tenant Athena deployments
    athena_http_timeout: float = 10.0           # Seconds before Athena HTTP call times out
    athena_session_ttl_days: int = 30           # How long session_id is cached in Redis


    # === Browser ===
    browser_enabled: bool = False
    browser_headless: bool = True
    browser_default_viewport: str = "1280x720"
    # Model for BrowserSubAgent. Must be a CUA (Computer Use Agent) model or
    # at minimum a multimodal model capable of processing screenshots.
    # Recommended:
    #   Gemini:     gemini-2.5-computer-use  (native CUA, built on Gemini 2.5 Pro)
    #   OpenAI:     gpt-5.4-mini             (native CUA, computer-use capable)
    #   Fallback:   any multimodal model (gpt-4o, gemini-2.5-flash) — vision required
    # Falls back to task_model_standard when not set (which may not be CUA-capable).
    browser_model: Optional[str] = None  # BROWSER_MODEL

    # === Search Providers ===
    # Gemini Grounded Search (primary): set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT
    gemini_api_key: Optional[str] = None
    gemini_grounding_api_key: Optional[str] = None
    gemini_grounding_model: str = "gemini-2.5-flash"
    google_cloud_project: Optional[str] = None
    google_cloud_location: str = "global"

    # Serper (secondary Google Search via serper.dev, optional)
    serper_api_key: Optional[str] = None


    # === Logging ===
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


def get_config_from_dict(config_dict: Optional[dict] = None) -> dict:
    """
    Get configuration from dictionary or environment.

    Args:
        config_dict: Optional configuration dictionary

    Returns:
        Configuration dictionary with defaults applied
    """
    # Load from environment first
    try:
        base_config = settings.model_dump()
    except Exception:
        # If pydantic fails, use manual defaults
        base_config = {}

    # Override with provided config
    if config_dict:
        base_config.update(config_dict)

    return base_config


# Global settings instance - loads from .env automatically
settings = Settings()
