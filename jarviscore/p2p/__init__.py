"""
P2P Integration Layer for JarvisCore

Wraps swim_p2p library for distributed agent coordination:
- SWIM protocol for membership management
- ZMQ messaging for agent communication
- Smart keepalive with traffic suppression
- Step output broadcasting
- PeerClient for direct agent-to-agent communication
"""

from .coordinator import P2PCoordinator
from .swim_manager import SWIMThreadManager
from .keepalive import P2PKeepaliveManager, CircuitState
from .broadcaster import StepOutputBroadcaster, StepExecutionResult
from .peer_client import PeerClient
from .peer_tool import PeerTool
from .messages import PeerInfo, IncomingMessage, MessageType

__all__ = [
    'P2PCoordinator',
    'SWIMThreadManager',
    'P2PKeepaliveManager',
    'CircuitState',
    'StepOutputBroadcaster',
    'StepExecutionResult',
    # PeerClient API
    'PeerClient',
    'PeerTool',
    'PeerInfo',
    'IncomingMessage',
    'MessageType',
]
