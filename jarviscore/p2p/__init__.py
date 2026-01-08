"""
P2P Integration Layer for JarvisCore

Wraps swim_p2p library for distributed agent coordination:
- SWIM protocol for membership management
- ZMQ messaging for agent communication
- Smart keepalive with traffic suppression
- Step output broadcasting
"""

from .coordinator import P2PCoordinator
from .swim_manager import SWIMThreadManager
from .keepalive import P2PKeepaliveManager, CircuitState
from .broadcaster import StepOutputBroadcaster, StepExecutionResult

__all__ = [
    'P2PCoordinator',
    'SWIMThreadManager',
    'P2PKeepaliveManager',
    'CircuitState',
    'StepOutputBroadcaster',
    'StepExecutionResult',
]
