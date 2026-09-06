"""Context pressure — how a turn stays inside its budget without losing data.

Context grows roughly linearly with turns while model capacity is fixed. The
tempting fix is to cut inside values, but a character limit decides what an
agent may know by counting bytes: a clipped JSON payload is not a smaller
payload, it is an invalid one, and the part that was cut is simply gone.

So nothing here trims. Under pressure the manager decides *which blocks are
rendered this turn*, in priority order, and replaces what it cannot inline with
a pointer to the canonical record. Every value that appears, appears whole.

The ladder, applied only as far as needed to fit:

  NORMAL     everything renders
  COMPRESS   oldest history is summarised into long-term memory (a derived
             artifact; the original stays in its store)
  EVICT_P3   stop inlining P3 blocks
  EVICT_P2   stop inlining P2 blocks; prior step outputs become references
  RECOVERY   P0 only, plus a notice telling the agent what it is missing

Priorities:

  P0  never evicted — mission, goal state, the pressure notice itself
  P1  kept if possible — failure memory, findings, beliefs, working memory
  P2  stop inlining first — input context, long-term memory, tool history
  P3  stop inlining — internal variables
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, MutableMapping, Optional

PRESSURE_STATE_KEY = "context_pressure"


class PressureTier(str, Enum):
    NORMAL = "normal"
    COMPRESS = "compress"
    EVICT_P3 = "evict_p3"
    EVICT_P2 = "evict_p2"
    RECOVERY = "recovery"


LADDER: tuple[PressureTier, ...] = (
    PressureTier.NORMAL,
    PressureTier.COMPRESS,
    PressureTier.EVICT_P3,
    PressureTier.EVICT_P2,
    PressureTier.RECOVERY,
)

BLOCK_PRIORITY: Dict[str, int] = {
    "mission": 0,
    "goal_state": 0,
    "context_pressure": 0,
    "budget": 0,
    "failure_memory": 1,
    "knowledge": 1,
    "belief_state": 1,
    "working_memory": 1,
    "input_context": 2,
    "long_term_memory": 2,
    "tool_history": 2,
    "internal_variables": 3,
}

# Identity and instruction: without these the agent does not know what it was
# asked, so they survive every tier.
INPUT_CONTEXT_ALWAYS_KEYS = frozenset({
    "task", "description", "objective", "human_response",
    "action_type", "step_id", "workflow_id", "system", "provider",
})

# Bulk carried for convenience; the canonical copy lives in the workflow store.
INPUT_CONTEXT_BULK_KEYS = frozenset({
    "context_variables", "injected_context", "previous_output", "previous_outputs",
})


@dataclass
class PressureState:
    tier: PressureTier = PressureTier.NORMAL
    evicted: List[str] = field(default_factory=list)
    tokens: int = 0
    budget: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "evicted": list(self.evicted),
            "tokens": self.tokens,
            "budget": self.budget,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "PressureState":
        if not isinstance(raw, dict):
            return cls()
        try:
            tier = PressureTier(str(raw.get("tier") or PressureTier.NORMAL.value))
        except ValueError:
            tier = PressureTier.NORMAL
        evicted = raw.get("evicted")
        return cls(
            tier=tier,
            evicted=[str(item) for item in evicted] if isinstance(evicted, list) else [],
            tokens=int(raw.get("tokens") or 0),
            budget=int(raw.get("budget") or 0),
        )


def get_pressure(internal_variables: Optional[MutableMapping[str, Any]]) -> PressureState:
    if not isinstance(internal_variables, dict):
        return PressureState()
    return PressureState.from_dict(internal_variables.get(PRESSURE_STATE_KEY))


def set_pressure(internal_variables: MutableMapping[str, Any], pressure: PressureState) -> None:
    internal_variables[PRESSURE_STATE_KEY] = pressure.to_dict()


def should_render_block(block_key: str, tier: PressureTier) -> bool:
    priority = BLOCK_PRIORITY.get(block_key, 2)
    if tier == PressureTier.RECOVERY:
        return priority == 0
    if tier == PressureTier.EVICT_P2:
        return priority <= 1
    if tier == PressureTier.EVICT_P3:
        return priority <= 2
    return True


def prior_step_mode(tier: PressureTier) -> str:
    """``full`` or ``references`` — never a fragment of a payload."""
    if tier in (PressureTier.EVICT_P2, PressureTier.RECOVERY):
        return "references"
    return "full"


def filter_input_context_keys(keys: Iterable[str], tier: PressureTier) -> List[str]:
    """Drop whole keys, never part of a value."""
    keys = list(keys)
    if tier == PressureTier.RECOVERY:
        return [key for key in keys if key in INPUT_CONTEXT_ALWAYS_KEYS]
    if tier in (PressureTier.EVICT_P2, PressureTier.EVICT_P3):
        return [key for key in keys if key not in INPUT_CONTEXT_BULK_KEYS]
    return keys


def format_step_references(workflow_id: str, step_ids: Iterable[str]) -> str:
    """Where the full upstream payloads are, since they were not inlined."""
    lines = [
        "## PRIOR STEP REFERENCES",
        "Upstream outputs were not inlined this turn because the context budget "
        "could not hold them whole. They are unchanged in the workflow store:",
        "",
    ]
    lines += [f"- `{step_id}` → `step_output:{workflow_id}:{step_id}`" for step_id in step_ids]
    return "\n".join(lines)


def format_pressure_notice(pressure: PressureState) -> str:
    """What the agent is missing, in its own prompt, so it can act accordingly."""
    lines = [
        "## CONTEXT PRESSURE",
        f"Tier: **{pressure.tier.value}** "
        f"({pressure.tokens} of {pressure.budget} tokens at full fidelity).",
    ]
    if pressure.evicted:
        lines.append(
            "Not inlined this turn: " + ", ".join(f"`{name}`" for name in pressure.evicted) + "."
        )
    lines.append(
        "Nothing was truncated — every value shown is whole. Withheld records are "
        "unchanged in their stores; retrieve what you need rather than assuming it is gone."
    )
    return "\n".join(lines)
