"""People as peers on the mesh: HumanAgent, and channels for putting work in front of them."""

from jarviscore.human.channels import DECISIONS, HumanChannel, TerminalChannel
from jarviscore.human.agent import HumanAgent

__all__ = ["DECISIONS", "HumanAgent", "HumanChannel", "TerminalChannel"]
