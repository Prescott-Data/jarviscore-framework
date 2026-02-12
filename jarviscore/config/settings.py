"""
JarvisCore Framework Configuration

Zero-config with standard environment variables (no prefix needed).

Configuration can be provided via:
1. Standard environment variables (CLAUDE_API_KEY, AZURE_OPENAI_KEY, etc.)
2. .env file
3. Direct config dictionary passed to Mesh

Example:
    # Via environment (standard names)
    export CLAUDE_API_KEY="sk-..."
    export AZURE_OPENAI_KEY="..."
    export BIND_HOST="0.0.0.0"
    export BIND_PORT=7946

    # Via config dict
    config = {
        'bind_host': '0.0.0.0',
        'bind_port': 7946,
        'seed_nodes': '192.168.1.100:7946'
    }
    mesh = Mesh(mode="distributed", config=config)
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Framework configuration with zero-config defaults.
    Uses standard environment variable names (no JARVISCORE_ prefix).
    """

    # === P2P Settings ===
    node_name: str = "jarviscore-node"
    bind_host: str = "127.0.0.1"
    bind_port: int = 7946
    seed_nodes: str = ""  # Comma-separated "host:port,host:port"
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
    gemini_model: str = "gemini-1.5-flash"
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
    claude_task_model: str = "claude-sonnet-4-5"
    claude_coding_model: str = "claude-opus-4-5"

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

    # === Browser ===
    browser_enabled: bool = False
    browser_headless: bool = True
    browser_default_viewport: str = "1280x720"

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
