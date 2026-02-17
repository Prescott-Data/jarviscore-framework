"""Default subagent implementations for the kernel."""

from .coder import CoderSubAgent
from .researcher import ResearcherSubAgent
from .communicator import CommunicatorSubAgent

__all__ = [
    "CoderSubAgent",
    "ResearcherSubAgent",
    "CommunicatorSubAgent",
]
