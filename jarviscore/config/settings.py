"""
JarvisCore Framework Configuration

Simplified from integration-agent (78 SWIM options → 15 core options).

Configuration can be provided via:
1. Environment variables with JARVISCORE_ prefix
2. .env file
3. Direct config dictionary passed to Mesh

Example:
    # Via environment
    export JARVISCORE_BIND_HOST="0.0.0.0"
    export JARVISCORE_BIND_PORT=7946

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


class JarvisCoreConfig(BaseSettings):
    """
    Framework configuration - simplified from integration-agent.

    Reduces 78 SWIM options to 15 most important ones.
    """

    # === Basic P2P Settings ===
    node_name: str = "jarviscore-node"
    bind_host: str = "127.0.0.1"
    bind_port: int = 7946
    seed_nodes: str = ""  # Comma-separated "host:port,host:port"

    # === P2P Features ===
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
    execution_timeout: int = 300  # seconds
    repair_attempts: int = 3

    # === LLM Settings (for Prompt-Dev) ===
    llm_provider: str = "vllm"  # vllm, azure, gemini
    llm_endpoint: str = ""
    llm_api_key: Optional[str] = None
    llm_model: str = "default"

    # === Logging ===
    log_level: str = "INFO"

    class Config:
        env_prefix = "JARVISCORE_"
        env_file = ".env"
        case_sensitive = False


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
        settings = JarvisCoreConfig()
        base_config = settings.model_dump()
    except Exception:
        # If pydantic fails, use manual defaults
        base_config = {
            'node_name': 'jarviscore-node',
            'bind_host': '127.0.0.1',
            'bind_port': 7946,
            'seed_nodes': '',
            'p2p_enabled': True,
            'zmq_port_offset': 1000,
            'transport_type': 'hybrid',
            'keepalive_enabled': True,
            'keepalive_interval': 90,
            'keepalive_timeout': 10,
            'activity_suppress_window': 60,
            'max_retries': 3,
            'execution_timeout': 300,
            'repair_attempts': 3,
            'llm_provider': 'vllm',
            'llm_endpoint': '',
            'llm_api_key': None,
            'llm_model': 'default',
            'log_level': 'INFO',
        }

    # Override with provided config
    if config_dict:
        base_config.update(config_dict)

    return base_config


# Default configuration instance
default_config = get_config_from_dict()
