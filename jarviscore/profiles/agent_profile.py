"""
jarviscore.profiles.agent_profile
===================================
AgentProfile — typed role intelligence contract for JarvisCore agents.

Loaded from YAML files in a directory resolved as follows (first match wins):
  1. $JARVISCORE_PROFILES_DIR/{role_name}.yaml   — set by your application
  2. jarviscore/profiles/agents/{role_name}.yaml  — bundled fallback (example only)

Application repos should set JARVISCORE_PROFILES_DIR to their own profiles
directory so agents get the right domain intelligence without modifying
the framework package.

This is what gives each agent its autonomous operational intelligence:
  - What they own (artifacts to produce)
  - SOPs (standing operating procedures — what to do without being told)
  - Expertise (domain knowledge to ground their reasoning)
  - Escalation rules (when and who to HITL)
  - Default kernel role (so the Kernel routes instantly without classification)

Usage:
    # Set in your .env or shell:
    # JARVISCORE_PROFILES_DIR=/path/to/yourapp/profiles/agents

    # AutoAgent.setup() calls this automatically:
    profile = AgentProfile.load("researcher")
    self._profile_block = profile.to_prompt_block()

    # In execute_task(), prepend to system_prompt:
    full_prompt = f"{self._profile_block}\\n\\n---\\n\\n{self.system_prompt}"
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

def _profiles_dir() -> Path:
    """
    Resolve the active profile directory at load time.

    Applications often set JARVISCORE_PROFILES_DIR during their own bootstrap,
    which can happen after this module is imported by another JarvisCore path.
    """
    configured = os.environ.get("JARVISCORE_PROFILES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).parent / "agents"


class AgentProfile:
    """
    Structured role intelligence for a JarvisCore agent.

    Attributes:
        role:                 Full role name, e.g. "Researcher — Data Intelligence Agent"
        expertise:            Domain areas this agent is authoritative on
        sops:                 Standing operating procedures (ordered)
        domain_facts:         Static facts about the org/context
        owns:                 Artifacts this agent produces (accountability)
        escalates_to:         Who to HITL when blocked
        default_kernel_role:  Optional explicit Kernel routing hint
    """

    def __init__(
        self,
        role: str,
        expertise: List[str],
        sops: List[str],
        domain_facts: Dict[str, str],
        owns: List[str],
        escalates_to: List[str],
        default_kernel_role: Optional[str] = None,
    ) -> None:
        self.role = role
        self.expertise = expertise
        self.sops = sops
        self.domain_facts = domain_facts
        self.owns = owns
        self.escalates_to = escalates_to
        self.default_kernel_role = default_kernel_role

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, role_name: str) -> Optional["AgentProfile"]:
        """
        Load an agent profile from a YAML file.

        Args:
            role_name: The agent's role slug, e.g. "researcher", "analyst"

        Returns:
            AgentProfile, or None if no profile found (graceful degradation).
        """
        yaml_path = _profiles_dir() / f"{role_name.lower()}.yaml"
        if not yaml_path.exists():
            logger.debug("[AgentProfile] No profile found for '%s' at %s", role_name, yaml_path)
            return None

        try:
            import yaml  # PyYAML — already in most envs, graceful fallback otherwise
        except ImportError:
            logger.warning("[AgentProfile] PyYAML not installed — agent profiles disabled. "
                           "Install with: pip install pyyaml")
            return None

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            return cls(
                role=data.get("role", role_name),
                expertise=data.get("expertise", []),
                sops=data.get("sops", []),
                domain_facts=data.get("domain_facts", {}),
                owns=data.get("owns", []),
                escalates_to=data.get("escalates_to", []),
                default_kernel_role=data.get("default_kernel_role"),
            )
        except Exception as exc:
            logger.warning("[AgentProfile] Failed to load profile '%s': %s", role_name, exc)
            return None

    # ── Prompt Rendering ─────────────────────────────────────────────────────

    def to_prompt_block(self) -> str:
        """
        Render the profile as a structured system prompt section.

        The block is prepended to the agent's base system prompt, giving the
        LLM structured role awareness before any task-specific context.
        """
        parts: List[str] = []
        parts.append(f"## ROLE INTELLIGENCE: {self.role.upper()}")
        parts.append("")

        if self.expertise:
            parts.append("### Expertise")
            for item in self.expertise:
                parts.append(f"- {item}")
            parts.append("")

        if self.domain_facts:
            parts.append("### Context")
            for k, v in self.domain_facts.items():
                parts.append(f"- **{k}**: {v}")
            parts.append("")

        if self.owns:
            parts.append("### What You Own")
            for item in self.owns:
                parts.append(f"- {item}")
            parts.append("")

        if self.sops:
            parts.append("### Standing Operating Procedures (follow autonomously — do not wait to be asked)")
            for i, sop in enumerate(self.sops, 1):
                parts.append(f"{i}. {sop}")
            parts.append("")

        if self.escalates_to:
            targets = ", ".join(self.escalates_to)
            parts.append(f"### Escalation")
            parts.append(f"When blocked for more than 48 hours or facing a decision outside your authority, escalate to: **{targets}** via HITL.")
            parts.append("")

        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"<AgentProfile role={self.role!r} sops={len(self.sops)} owns={len(self.owns)}>"
