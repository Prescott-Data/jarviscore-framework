"""
P2P Integration Layer for JarvisCore

Wraps swim_p2p library for distributed agent coordination:
- SWIM protocol for membership management
- ZMQ messaging for agent communication
- Smart keepalive with traffic suppression
- Step output broadcasting
- PeerClient for direct agent-to-agent communication
"""

from .keepalive import P2PKeepaliveManager, CircuitState
from .broadcaster import StepOutputBroadcaster, StepExecutionResult
from .peer_client import PeerClient
from .peer_tool import PeerTool
from .messages import PeerInfo, IncomingMessage, MessageType

_LAZY = {"P2PCoordinator": ".coordinator", "SWIMThreadManager": ".swim_manager"}


def __getattr__(name):
    # swim-p2p prints to stdout at import; load it only when P2P is actually used
    if name in _LAZY:
        import importlib

        module = importlib.import_module(_LAZY[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
