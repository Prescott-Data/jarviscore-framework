"""
P2P Message Types for JarvisCore Framework

Defines dataclasses for peer information and messages exchanged
between agents via the PeerClient API.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import time


class MessageType(Enum):
    """Types of peer-to-peer messages."""
    NOTIFY = "notify"       # Fire-and-forget notification
    REQUEST = "request"     # Request expecting response
    RESPONSE = "response"   # Response to a request


@dataclass
class PeerInfo:
    """
    Information about a peer agent in the mesh.

    Attributes:
        agent_id: Unique identifier for the agent
        role: The agent's role (e.g., "scout", "analyst")
        capabilities: List of capabilities the agent provides
        node_id: P2P node identifier (host:port)
        status: Current status (alive, suspected, dead)
    """
    agent_id: str
    role: str
    capabilities: List[str]
    node_id: str = ""
    status: str = "alive"

    def has_capability(self, capability: str) -> bool:
        """Check if peer has a specific capability."""
        return capability in self.capabilities


@dataclass
class IncomingMessage:
    """
    A message received from a peer agent.

    Attributes:
        sender: Agent ID or role of the sender
        sender_node: P2P node ID of the sender
        type: Message type (notify, request, response)
        data: Message payload
        correlation_id: ID linking request to response (for request-response pattern)
        timestamp: When the message was sent
    """
    sender: str
    sender_node: str
    type: MessageType
    data: Dict[str, Any]
    correlation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def is_request(self) -> bool:
        """Check if this message expects a response."""
        return self.type == MessageType.REQUEST

    @property
    def is_notify(self) -> bool:
        """Check if this is a fire-and-forget notification."""
        return self.type == MessageType.NOTIFY


@dataclass
class OutgoingMessage:
    """
    A message to be sent to a peer agent.

    Used internally by PeerClient for message construction.
    """
    target: str              # Target agent role or ID
    type: MessageType
    data: Dict[str, Any]
    correlation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    sender: str = ""         # Filled in by PeerClient
    sender_node: str = ""    # Filled in by PeerClient
