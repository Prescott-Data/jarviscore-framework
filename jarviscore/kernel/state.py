"""
KernelState — Runtime state for subagent OODA loop + checkpoint/resume.

This is the single source of truth during a subagent's execution.
The ContextManager reads from it to build prompts.
The OODA loop mutates it via add_tool_result() / add_thought().
It serializes via model_dump_json() for Redis checkpoint/resume.

Design decisions:
  - Pydantic BaseModel for serialisation (checkpoint to Redis)
  - ToolResult is a structured model, not a raw dict
  - Mutation methods are explicit (add_tool_result, add_thought)
  - internal_variables is a flexible dict for subagent-specific state
  - belief_state tracks constraints and hypotheses
"""

import copy
import shlex
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolReceiptError(ValueError):
    """A final artifact references missing or incompatible tool evidence."""


class ArtifactReferenceError(ValueError):
    """A composed artifact references missing or incompatible dependency output."""


class ArtifactReference(BaseModel):
    """Exact location of an artifact supplied by one direct dependency."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    path: List[str | int] = Field(default_factory=list)


class CommandObservation(BaseModel):
    """Authoritative command evidence hydrated from one tool receipt."""

    model_config = ConfigDict(extra="forbid")

    tool_receipt_id: str = Field(min_length=1)
    command: List[str] = Field(min_length=1)
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = Field(ge=0)
    observed_at: datetime


class WorkspaceMutation(BaseModel):
    """Authoritative file mutation evidence hydrated from workspace_write."""

    model_config = ConfigDict(extra="forbid")

    tool_receipt_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    bytes: int = Field(ge=0)
    executable: bool = False
    observed_at: datetime


class ToolResult(BaseModel):
    """Record of a single tool invocation within the OODA loop."""

    tool_name: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    tool_output: Any = None
    error: Optional[str] = None
    status: Literal["success", "failure", "blocked"] = "success"
    timestamp: float = Field(default_factory=time.time)
    duration_ms: int = Field(default=0, ge=0)
    receipt_id: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and self.error is None

    @property
    def observed_at(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    def command_observation(self) -> CommandObservation:
        """Project a workspace command result into immutable evidence."""
        if self.tool_name != "workspace_run" or not isinstance(self.tool_output, dict):
            raise ToolReceiptError(
                f"Tool receipt {self.receipt_id!r} is not command evidence"
            )
        raw_command = self.tool_input.get("command")
        command = (
            [str(value) for value in raw_command]
            if isinstance(raw_command, list)
            else shlex.split(str(raw_command or ""))
        )
        if not command or "returncode" not in self.tool_output:
            raise ToolReceiptError(
                f"Tool receipt {self.receipt_id!r} has no complete command result"
            )
        return CommandObservation(
            tool_receipt_id=self.receipt_id,
            command=command,
            exit_code=int(self.tool_output["returncode"]),
            stdout=str(self.tool_output.get("stdout") or ""),
            stderr=str(self.tool_output.get("stderr") or ""),
            duration_ms=self.duration_ms,
            observed_at=self.observed_at,
        )

    def workspace_mutation(self) -> WorkspaceMutation:
        """Project a workspace write result into immutable evidence."""
        if self.tool_name not in {"workspace_write", "workspace_edit"} or not isinstance(
            self.tool_output, dict
        ):
            raise ToolReceiptError(
                f"Tool receipt {self.receipt_id!r} is not workspace mutation evidence"
            )
        required = {"path", "sha256", "bytes"}
        if self.tool_output.get("status") != "success" or not required <= set(
            self.tool_output
        ):
            raise ToolReceiptError(
                f"Tool receipt {self.receipt_id!r} has no complete workspace mutation"
            )
        return WorkspaceMutation(
            tool_receipt_id=self.receipt_id,
            path=str(self.tool_output["path"]),
            sha256=str(self.tool_output["sha256"]),
            bytes=int(self.tool_output["bytes"]),
            executable=bool(self.tool_output.get("executable", False)),
            observed_at=self.observed_at,
        )


class KernelState(BaseModel):
    """
    Serializable runtime state for the kernel's OODA loop.

    Persisted to Redis via save_checkpoint() for crash recovery.
    The kernel can resume from any checkpoint by loading the state
    and continuing the OODA loop from where it left off.

    The ContextManager reads this state each turn to build a
    priority-ordered prompt that fits the token budget.
    """

    workflow_id: str = ""
    step_id: str = ""
    agent_id: str = ""
    task: str = ""
    status: Literal["active", "waiting", "completed", "failed"] = "active"
    turn: int = 0
    phase: str = "discovery"

    system_prompt: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)

    # Structured tool execution history (OODA loop audit trail)
    tool_history: List[ToolResult] = Field(default_factory=list)

    # Working memory — thoughts, scratchpad notes
    thoughts: List[str] = Field(default_factory=list)
    scratchpad_notes: str = ""

    # Flexible key-value store for subagent-specific state
    # (e.g. research_findings, candidate_code, shared_context)
    internal_variables: Dict[str, Any] = Field(default_factory=dict)

    # Belief state — constraints discovered, hypotheses formed
    belief_state: Dict[str, Any] = Field(default_factory=dict)

    # Budget tracking (mirrors lease state for checkpoint)
    thinking_tokens_used: int = 0
    action_tokens_used: int = 0
    tokens_used: int = 0
    tokens_budget: int = 240_000
    total_cost_usd: float = 0.0

    # Error tracking
    last_error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    # Failure ledger snapshot (for cross-session persistence)
    failure_ledger: List[Dict[str, Any]] = Field(default_factory=list)

    # Timestamps
    started_at: float = Field(default_factory=time.time)
    last_checkpoint_at: Optional[float] = None

    # Final output
    output: Optional[Any] = None

    # ──────────────────────────────────────────────────────────────
    # Backward-compat aliases
    # ──────────────────────────────────────────────────────────────

    @property
    def input_data(self) -> Dict[str, Any]:
        """Alias for context — ResearcherSubAgent uses state.input_data to
        access the kernel's enriched context dict (provider, credentials, etc).
        This field was renamed context in a prior refactor; keep both names live
        so the researcher code doesn't need to be mass-patched."""
        return self.context


    def add_tool_result(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        error: Optional[str] = None,
        *,
        timestamp: Optional[float] = None,
        duration_ms: int = 0,
    ) -> ToolResult:
        """Record a tool invocation result.

        Returns the ToolResult for inspection by the caller.
        """
        status: Literal["success", "failure", "blocked"] = "success"
        if error:
            status = "failure"
        elif isinstance(tool_output, dict):
            out_status = str(tool_output.get("status", "")).lower()
            if out_status in ("error", "failed", "blocked"):
                status = "failure"
                if not error:
                    error = tool_output.get("error")

        result = ToolResult(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            error=str(error) if error else None,
            status=status,
            timestamp=time.time() if timestamp is None else timestamp,
            duration_ms=max(0, int(duration_ms)),
            receipt_id=(
                f"tool:{self.workflow_id or f'local-{self.agent_id}-{int(self.started_at * 1_000_000)}'}:"
                f"{self.step_id or self.agent_id}:{len(self.tool_history) + 1}"
            ),
        )
        self.tool_history.append(result)

        if error:
            self.last_error = str(error)[:500]
        return result

    def hydrate_tool_receipts(
        self,
        value: Any,
        *,
        require_command_receipts: bool = False,
    ) -> Any:
        """Replace command claims with the authoritative referenced tool result."""
        receipts = {
            receipt.receipt_id: receipt
            for receipt in self.tool_history
            if receipt.receipt_id
        }
        prior_observations: Dict[str, CommandObservation] = {}
        prior_mutations: Dict[str, WorkspaceMutation] = {}
        workflow_prefix = (
            f"tool:{self.workflow_id}:"
            if self.workflow_id and self.workflow_id != "unknown"
            else ""
        )

        def collect_prior(candidate: Any) -> None:
            if isinstance(candidate, list):
                for item in candidate:
                    collect_prior(item)
                return
            if not isinstance(candidate, dict):
                return
            receipt_id = str(candidate.get("tool_receipt_id") or "").strip()
            if receipt_id:
                if workflow_prefix and not receipt_id.startswith(workflow_prefix):
                    return
                try:
                    prior_observations[receipt_id] = CommandObservation.model_validate(
                        candidate
                    )
                except Exception:
                    try:
                        prior_mutations[receipt_id] = WorkspaceMutation.model_validate(
                            candidate
                        )
                    except Exception:
                        pass
            for item in candidate.values():
                collect_prior(item)

        collect_prior((self.context or {}).get("previous_step_results") or {})

        def hydrate(candidate: Any) -> Any:
            if isinstance(candidate, list):
                return [hydrate(item) for item in candidate]
            if not isinstance(candidate, dict):
                return candidate
            receipt_id = str(candidate.get("tool_receipt_id") or "").strip()
            command_claim = "command" in candidate and any(
                field in candidate
                for field in ("exit_code", "stdout", "stderr", "duration_ms", "observed_at")
            )
            if receipt_id:
                if workflow_prefix and not receipt_id.startswith(workflow_prefix):
                    raise ToolReceiptError(
                        f"Tool receipt {receipt_id!r} belongs to another workflow"
                    )
                receipt = receipts.get(receipt_id)
                mutation_claim = "path" in candidate and any(
                    field in candidate
                    for field in ("sha256", "bytes", "executable")
                )
                if mutation_claim and receipt is not None:
                    evidence: BaseModel = receipt.workspace_mutation()
                elif mutation_claim:
                    evidence = prior_mutations.get(receipt_id)
                elif receipt is not None:
                    evidence = receipt.command_observation()
                else:
                    evidence = prior_observations.get(receipt_id)
                if evidence is None:
                    raise ToolReceiptError(f"Unknown tool receipt {receipt_id!r}")
                return evidence.model_dump(mode="json")
            if require_command_receipts and command_claim:
                raise ToolReceiptError(
                    "Command observations require a tool_receipt_id from workspace_run"
                )
            return {key: hydrate(item) for key, item in candidate.items()}

        return hydrate(value)

    def receipt_evidence(self, value: Any = None) -> List[Dict[str, Any]]:
        """Canonical evidence cited by one output, safe for final validation."""
        cited = set()

        def collect(candidate: Any) -> None:
            if isinstance(candidate, list):
                for item in candidate:
                    collect(item)
                return
            if not isinstance(candidate, dict):
                return
            receipt_id = str(candidate.get("tool_receipt_id") or "").strip()
            if receipt_id:
                cited.add(receipt_id)
            for item in candidate.values():
                collect(item)

        collect(self.output if value is None else value)
        evidence = []
        for receipt in self.tool_history:
            if receipt.receipt_id not in cited:
                continue
            try:
                if receipt.tool_name == "workspace_run":
                    item = receipt.command_observation()
                elif receipt.tool_name in {"workspace_write", "workspace_edit"}:
                    item = receipt.workspace_mutation()
                else:
                    continue
            except ToolReceiptError:
                continue
            evidence.append(item.model_dump(mode="json"))
        return evidence

    def add_thought(self, thought: str) -> None:
        """Record an internal thought / meta-cognition note."""
        self.thoughts.append(thought)
        # Keep bounded — only the last 20 thoughts are useful for context
        if len(self.thoughts) > 20:
            self.thoughts = self.thoughts[-20:]

    def update_epistemic_state(self, key: str, value: Any) -> None:
        """Update belief state with a discovered fact or constraint.

        Called by subagent tools after successful data extraction to
        populate the BELIEF STATE context block visible to the LLM.
        """
        self.belief_state[key] = value

    def get_last_tool_result(self) -> Optional[ToolResult]:
        """Return the most recent tool result, or None."""
        return self.tool_history[-1] if self.tool_history else None

    def get_final_output(self) -> Any:
        """The agent's answer, if it gave one.

        Only what the agent set at DONE counts. Falling back to the last tool's
        output presented a sandbox return value as the conclusion of a task the
        agent had not finished reasoning about; the last thought is the same
        thing in prose. A run that did not conclude has no answer, and saying
        so is more useful to the caller than a payload it will misread as one.
        """
        return self.output

    def unfinished_account(self) -> Optional[str]:
        """What the agent was doing when the run stopped, for a run with no answer."""
        if self.output is not None:
            return None
        parts = []
        if self.thoughts:
            parts.append(f"Last reasoning: {self.thoughts[-1]}")
        for tr in reversed(self.tool_history):
            if tr.succeeded and tr.tool_output is not None:
                parts.append(f"Last tool: {tr.tool_name}")
                break
        return " | ".join(parts) or None


def hydrate_receipt_evidence(
    value: Any,
    *,
    receipt_evidence: List[Dict[str, Any]],
    previous_step_results: Optional[Dict[str, Any]] = None,
    require_receipts: bool = True,
    workflow_id: str = "",
) -> Any:
    """Ground receipt-bearing output after all product normalization hooks."""
    commands: Dict[str, CommandObservation] = {}
    mutations: Dict[str, WorkspaceMutation] = {}
    workflow_prefix = f"tool:{workflow_id}:" if workflow_id else ""

    def collect(candidate: Any) -> None:
        if isinstance(candidate, list):
            for item in candidate:
                collect(item)
            return
        if not isinstance(candidate, dict):
            return
        receipt_id = str(candidate.get("tool_receipt_id") or "").strip()
        if receipt_id:
            if workflow_prefix and not receipt_id.startswith(workflow_prefix):
                return
            try:
                commands[receipt_id] = CommandObservation.model_validate(candidate)
            except Exception:
                try:
                    mutations[receipt_id] = WorkspaceMutation.model_validate(candidate)
                except Exception:
                    pass
        for item in candidate.values():
            collect(item)

    collect(receipt_evidence)
    collect(previous_step_results or {})

    def hydrate(candidate: Any) -> Any:
        if isinstance(candidate, list):
            return [hydrate(item) for item in candidate]
        if not isinstance(candidate, dict):
            return candidate
        receipt_id = str(candidate.get("tool_receipt_id") or "").strip()
        command_claim = "command" in candidate and any(
            field in candidate
            for field in ("exit_code", "stdout", "stderr", "duration_ms", "observed_at")
        )
        mutation_claim = "path" in candidate and any(
            field in candidate for field in ("sha256", "bytes", "executable")
        )
        if receipt_id:
            if workflow_prefix and not receipt_id.startswith(workflow_prefix):
                raise ToolReceiptError(
                    f"Tool receipt {receipt_id!r} belongs to another workflow"
                )
            evidence: Optional[BaseModel]
            if mutation_claim:
                evidence = mutations.get(receipt_id)
            else:
                evidence = commands.get(receipt_id)
            if evidence is None:
                raise ToolReceiptError(f"Unknown tool receipt {receipt_id!r}")
            return evidence.model_dump(mode="json")
        if require_receipts and command_claim:
            raise ToolReceiptError(
                "Command observations require an authoritative tool_receipt_id"
            )
        if require_receipts and mutation_claim:
            raise ToolReceiptError(
                "Workspace mutations require an authoritative tool_receipt_id"
            )
        return {key: hydrate(item) for key, item in candidate.items()}

    return hydrate(value)


def hydrate_artifact_references(
    value: Any,
    *,
    previous_step_results: Dict[str, Any],
    required_reference_paths: tuple[tuple[str, ...], ...] = (),
) -> Any:
    """Replace explicit artifact references with exact direct-dependency values."""

    def is_reference(candidate: Any) -> bool:
        return (
            isinstance(candidate, dict)
            and set(candidate) == {"artifact_ref"}
            and isinstance(candidate["artifact_ref"], dict)
        )

    def targets(candidate: Any, path: tuple[str, ...]) -> List[Any]:
        if not path:
            return [candidate]
        segment, *remaining = path
        tail = tuple(remaining)
        if segment == "*":
            if not isinstance(candidate, list):
                return []
            return [item for value in candidate for item in targets(value, tail)]
        if not isinstance(candidate, dict) or segment not in candidate:
            return []
        return targets(candidate[segment], tail)

    for path in required_reference_paths:
        for target in targets(value, path):
            if target is not None and not is_reference(target):
                raise ArtifactReferenceError(
                    f"Composed artifact field {'.'.join(path)!r} must use an "
                    "exact artifact_ref"
                )

    def hydrate(candidate: Any, active: tuple[tuple[str, tuple[str | int, ...]], ...]) -> Any:
        if isinstance(candidate, list):
            return [hydrate(item, active) for item in candidate]
        if not isinstance(candidate, dict):
            return candidate
        if not is_reference(candidate):
            return {key: hydrate(item, active) for key, item in candidate.items()}

        try:
            reference = ArtifactReference.model_validate(candidate["artifact_ref"])
        except Exception as exc:
            raise ArtifactReferenceError(f"Invalid artifact reference: {exc}") from exc
        if reference.step_id not in previous_step_results:
            raise ArtifactReferenceError(
                f"Artifact reference names unavailable direct dependency "
                f"{reference.step_id!r}"
            )
        identity = (reference.step_id, tuple(reference.path))
        if identity in active:
            raise ArtifactReferenceError(f"Cyclic artifact reference {identity!r}")
        selected = previous_step_results[reference.step_id]
        for segment in reference.path:
            if isinstance(segment, int):
                if segment < 0:
                    raise ArtifactReferenceError(
                        f"Artifact reference {identity!r} has negative list position {segment}"
                    )
                if not isinstance(selected, list) or not -len(selected) <= segment < len(selected):
                    raise ArtifactReferenceError(
                        f"Artifact reference {identity!r} has invalid list position {segment}"
                    )
                selected = selected[segment]
            else:
                if not isinstance(selected, dict) or segment not in selected:
                    raise ArtifactReferenceError(
                        f"Artifact reference {identity!r} has missing field {segment!r}"
                    )
                selected = selected[segment]
        return hydrate(copy.deepcopy(selected), (*active, identity))

    return hydrate(value, ())
