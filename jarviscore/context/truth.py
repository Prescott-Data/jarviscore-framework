"""
Truth Models for JarvisCore v1.0.1.

Typed contracts for shared knowledge between agents:
- Evidence: A confidence-scored pointer to supporting data
- TruthFact: A versioned, evidence-backed claim
- TruthContext: The canonical shared fact store for a workflow
- AgentOutput: Standardized envelope returned by all subagents

Ported from IA/CA's schema.py with improvements:
- Pydantic v2 models (not raw dicts)
- Evidence has explicit `kind` enum (not free-form strings)
- TruthFact tracks version for conflict detection
- AgentOutput adds "yield" status for HITL pause
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """
    Evidence pointer for any claim in the TruthContext.

    Every fact should cite its sources. Evidence tracks where the
    information came from, how confident we are in it, and an
    optional verbatim quote.

    Attributes:
        kind: Category of evidence source
        pointer: URI, file path, or identifier pointing to the source
        quote: Optional verbatim excerpt from the source
        collected_at: ISO timestamp when evidence was gathered
        confidence: How reliable this evidence is (0.0 to 1.0)
    """
    kind: Literal[
        "doc_url",
        "internal_doc",
        "code_pointer",
        "ui_capture",
        "runtime_observation",
        "other",
    ]
    pointer: str
    quote: Optional[str] = None
    collected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    confidence: float = 0.5

    def model_post_init(self, __context: Any) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")


class TruthFact(BaseModel):
    """
    A versioned, evidence-backed fact in the TruthContext.

    Facts are the atoms of shared knowledge. Each fact has a value,
    a list of supporting evidence, a confidence score, and version
    tracking for conflict detection.

    Attributes:
        value: The actual fact data (any JSON-serializable type)
        evidence: Supporting evidence for this fact
        confidence: Aggregate confidence in this fact (0.0 to 1.0)
        source: Which agent or step produced this fact
        version: Incremented on each update (for conflict detection)
        updated_at: ISO timestamp of last update
    """
    value: Any
    evidence: List[Evidence] = Field(default_factory=list)
    confidence: float = 0.5
    source: str = "unknown"
    version: int = 1
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def model_post_init(self, __context: Any) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0-1.0, got {self.confidence}")


class TruthContext(BaseModel):
    """
    Canonical shared truth store for a workflow.

    This is the single source of truth that all agents in a workflow
    read from and write to. Facts are keyed by name, and every
    mutation is recorded in the history ledger.

    Attributes:
        facts: Named facts with evidence and versioning
        history: Audit trail of all mutations (who changed what, when)
        version: Global version counter (incremented on every merge)
    """
    facts: Dict[str, TruthFact] = Field(default_factory=dict)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    version: int = 1

    def get_fact_value(self, key: str, default: Any = None) -> Any:
        """Get a fact's value by key, or default if not found."""
        fact = self.facts.get(key)
        if fact is None:
            return default
        return fact.value

    def get_fact(self, key: str) -> Optional[TruthFact]:
        """Get the full TruthFact by key (includes evidence, confidence)."""
        return self.facts.get(key)

    def fact_keys(self) -> List[str]:
        """List all fact keys."""
        return list(self.facts.keys())

    def to_flat_dict(self) -> Dict[str, Any]:
        """Flatten to {key: value} dict, stripping metadata."""
        return {k: f.value for k, f in self.facts.items()}

    def high_confidence_facts(self, threshold: float = 0.7) -> Dict[str, TruthFact]:
        """Return only facts above the confidence threshold."""
        return {k: f for k, f in self.facts.items() if f.confidence >= threshold}


class AgentOutput(BaseModel):
    """
    Standardized output envelope for all subagents.

    Every subagent (coder, researcher, reviewer, etc.) returns this
    envelope. The kernel uses it to distill facts, update truth,
    and decide the next action.

    Attributes:
        status: "success" (done), "failure" (error), or "yield" (needs human input)
        payload: The actual result data (typed per subagent)
        summary: Human-readable summary for logs and scratchpad
        trajectory: Tool execution path taken (for audit)
        metadata: Additional context (evidence, facts, cost, etc.)
    """
    status: Literal["success", "failure", "yield"]
    payload: Optional[Any] = None
    summary: str = ""
    trajectory: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
