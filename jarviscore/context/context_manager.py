"""
ContextManager — Token budget and priority-stack prompt builder.

Manages what goes into an LLM context window for Kernel calls.
Two responsibilities:

1. Token counting — estimates token usage from text. Uses tiktoken
   when available (exact), falls back to word-count heuristic.

2. Context building — assembles a prompt from a priority-ordered stack,
   trimming lower-priority sections when the budget is exhausted:

   Priority (highest → lowest, never trimmed → first trimmed):
     1. MISSION       — workflow_id, step_id, task description (fixed)
     2. FAILURE MEMORY — recent failures (prevents repeat mistakes)
     3. CURRENT PLAN  — active reasoning / next steps
     4. SCRATCHPAD    — working notes from this turn
     5. LONG-TERM MEM — compressed prior summaries
     6. TOOL HISTORY  — sliding window of recent tool calls
     7. VARIABLES     — input data / step outputs (fills remainder)

3. Auto-summarisation trigger — when cumulative token use crosses
   the configured threshold, signals the Kernel to compress and archive.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from jarviscore.context.pressure import (
    LADDER,
    PRESSURE_STATE_KEY,
    PressureState,
    PressureTier,
    filter_input_context_keys,
    format_pressure_notice,
    format_step_references,
    prior_step_mode,
    set_pressure,
    should_render_block,
)

if TYPE_CHECKING:
    from jarviscore.kernel.state import KernelState

logger = logging.getLogger(__name__)

# ── Token counting ──────────────────────────────────────────────────

# Try tiktoken for exact counting; fall back to heuristic
try:
    import tiktoken
    _ENCODER = tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except ImportError:
    _ENCODER = None
    _HAS_TIKTOKEN = False

# Tokens-per-word heuristic (matches llm.py Gemini fallback)
_TOKENS_PER_WORD: float = 1.3

# Keys whose values must be scrubbed from context
_SENSITIVE_KEYS = frozenset({
    "password", "auth_header", "access_token", "refresh_token",
    "token", "api_key", "secret", "client_secret", "private_key",
})


@dataclass
class BudgetConfig:
    """
    Token budget configuration for a single Kernel LLM call.

    Attributes:
        total_tokens:              Hard limit for the context window.
        output_reserve:            Tokens reserved for the model's response.
        system_reserve:            Tokens reserved for the system prompt.
        history_limit:             Max tokens to spend on tool history.
        summarization_threshold:   Fraction of total_tokens at which
                                   auto-summarisation is triggered.

    Values are never cut to fit (issue #154). When the budget cannot hold
    everything, whole blocks stop being inlined in priority order and the
    withheld records are named, so the agent can retrieve them from the store
    they still live in. The per-value character limits below are retained for
    backward compatibility and no longer affect rendering.
    """
    total_tokens: int = 80_000
    output_reserve: int = 4_000
    system_reserve: int = 8_000
    history_limit: int = 20_000
    summarization_threshold: float = 0.8
    # Deprecated (issue #154): retained so existing configs keep importing.
    # Rendering no longer cuts values, so these have no effect.
    prior_step_value_limit: int = 2000
    context_value_limit: int = 800
    belief_value_limit: int = 200
    memory_item_limit: int = 200
    internal_var_limit: int = 200
    history_value_limit: int = 600
    state_keys_limit: int = 10
    summary_evidence_limit: int = 800
    # How many compressed-away turns stay retrievable in the archive.
    archive_window: int = 50
    # Long-term memory bound (issue #69). On overflow the OLDEST half is
    # merged into one labeled epoch summary; the newest entries keep full
    # fidelity. Incremental accumulation, never monolithic rewrite — the
    # context-collapse failure mode identified by ACE (arXiv:2510.04618).
    ltm_window: int = 20
    # How many LTM entries the context block renders.
    ltm_render_limit: int = 5
    # Token budget for the GOAL STATE block (issue #72) — the accumulated
    # facts and step history of a goal execution, rendered structured.
    goal_state_budget: int = 4000

    @property
    def usable_tokens(self) -> int:
        """Tokens available for context content after reserves."""
        return self.total_tokens - self.output_reserve - self.system_reserve


class ContextManager:
    """
    Manages LLM token budgets and assembles prioritised prompt context.

    Used by the Kernel before each LLM call to ensure the assembled
    prompt fits within the model's context window.

    Supports two input shapes:
      - KernelState (Pydantic model — preferred for OODA loop)
      - Dict[str, Any] (legacy — for backward compatibility)
    """

    def __init__(self, config: Optional[BudgetConfig] = None):
        self.config = config or BudgetConfig()
        self._used_tokens: int = 0

    # ------------------------------------------------------------------
    # Token counting
    # ------------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Uses tiktoken (exact) when available, falls back to word-count heuristic.
        """
        if not text:
            return 0
        if _HAS_TIKTOKEN and _ENCODER is not None:
            try:
                return len(_ENCODER.encode(text))
            except Exception:
                pass  # fall through to heuristic
        return max(1, int(len(text.split()) * _TOKENS_PER_WORD))

    def record_usage(self, tokens: int) -> None:
        """Accumulate token usage for threshold tracking."""
        self._used_tokens += tokens

    def reset_usage(self) -> None:
        """Reset cumulative token counter (e.g. after summarisation)."""
        self._used_tokens = 0

    @property
    def used_tokens(self) -> int:
        """Total tokens recorded via record_usage() since last reset."""
        return self._used_tokens

    # ------------------------------------------------------------------
    # Secret scrubbing
    # ------------------------------------------------------------------

    @staticmethod
    def _scrub_value(key: str, value: Any) -> Any:
        """Mask sensitive values in context."""
        key_lower = key.lower()
        if key_lower in _SENSITIVE_KEYS or "token" in key_lower or "secret" in key_lower:
            return "***"
        return value

    @staticmethod
    def _scrub_dict(data: Dict[str, Any]) -> Dict[str, Any]:
        """Scrub sensitive values from a dict."""
        cleaned = {}
        for k, v in data.items():
            if isinstance(v, dict):
                cleaned[k] = {ik: ContextManager._scrub_value(ik, iv) for ik, iv in v.items()}
            else:
                cleaned[k] = ContextManager._scrub_value(k, v)
        return cleaned

    # ------------------------------------------------------------------
    # Honest rendering helpers (issues #55, #56)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_recalled_block(recalled: Any) -> str:
        """Earlier sessions, presented as earlier sessions.

        Memory arrived under INPUT CONTEXT before, indistinguishable from the
        task, and the decision contract's first question ("what have I
        established?") read a stale diagnosis as established. Here it is named
        for what it is, and what it is not.
        """
        lines = [
            "## FROM EARLIER SESSIONS",
            "What this agent recorded before, retrieved by relevance to this task. "
            "It describes the past: things may have changed since, and anything "
            "that reads as a diagnosis of a failure is a hypothesis to re-test, "
            "not a fact to build on.",
        ]
        items = recalled if isinstance(recalled, list) else [recalled]
        for item in items:
            if isinstance(item, dict):
                text = item.get("content") or item.get("text") or item.get("summary") or ""
                when = item.get("timestamp") or item.get("created_at") or ""
                score = item.get("similarity_score")
                tag = f" ({when})" if when else ""
                rel = f" [relevance {score:.2f}]" if isinstance(score, (int, float)) else ""
                if str(text).strip():
                    lines.append(f"- {str(text).strip()}{tag}{rel}")
            elif str(item).strip():
                lines.append(f"- {str(item).strip()}")
        return "\n".join(lines) if len(lines) > 2 else ""

    def _build_goal_state_block(self, context: Dict[str, Any]) -> str:
        """Render a goal execution's accumulated state — structured (issue #72).

        Consumes the keys `context_for_next_step()` injects (`_goal`,
        `_goal_facts`, `_goal_facts_high_confidence`, `_completed_steps`,
        `_plan_revision`). Returns "" when the agent is not running under a
        goal — non-goal dispatches see zero change.
        """
        goal = context.get("_goal")
        facts = context.get("_goal_facts")
        completed = context.get("_completed_steps")
        if not goal and not facts and not completed:
            return ""

        lines = ["## GOAL STATE"]
        if goal:
            revision = context.get("_plan_revision", 0)
            rev_note = f" (plan revision {revision})" if revision else ""
            lines.append(f"**Goal:** {goal}{rev_note}")

        if isinstance(facts, dict) and facts:
            high_conf = context.get("_goal_facts_high_confidence") or {}
            lines.append(f"**Established facts ({len(facts)}):**")
            # High-confidence facts first — they are the plan's load-bearing truth
            ordered = sorted(facts.items(), key=lambda kv: kv[0] not in high_conf)
            for key, value in ordered:
                marker = " ✓" if key in high_conf else ""
                lines.append(f"- `{key}`{marker}: {value}")

        if isinstance(completed, list) and completed:
            lines.append(f"**Completed steps ({len(completed)}):**")
            for cs in completed:
                if isinstance(cs, dict):
                    sid = cs.get("step_id", "?")
                    verdict = cs.get("verdict", cs.get("status", "?"))
                    lines.append(f"- [{verdict}] `{sid}`: {cs.get('summary') or cs.get('task', '')}")
                else:
                    lines.append(f"- {cs}")

        return "\n".join(lines)


    def build_context(self, state: Any) -> str:
        """
        Assemble a priority-ordered prompt context string.

        Accepts either KernelState (Pydantic) or Dict. KernelState is
        preferred — it gives us structured tool history, failure memory,
        and belief state. Dict is kept for backward compatibility.
        """
        # Route to the appropriate builder
        if isinstance(state, dict):
            return self._build_context_from_dict(state)
        return self._build_context_from_state(state)

    def _build_context_from_state(self, state: "KernelState") -> str:
        """Build context from a KernelState Pydantic model.

        Blocks are composed once at full fidelity, then the least aggressive
        pressure tier that fits the budget is chosen. Values are never cut.
        """
        budget = self.config.usable_tokens
        candidates = self._compose_blocks(state)
        full_cost = sum(self.count_tokens(text) for _, text in candidates)

        for tier in LADDER:
            blocks = self._render_at_tier(state, candidates, tier)
            used = sum(self.count_tokens(text) for text in blocks)
            if used <= budget or tier is LADDER[-1]:
                break

        evicted = [key for key, _ in candidates if not should_render_block(key, tier)]
        pressure = PressureState(tier=tier, evicted=evicted, tokens=full_cost, budget=budget)
        if isinstance(state.internal_variables, dict):
            set_pressure(state.internal_variables, pressure)
        if tier is not PressureTier.NORMAL:
            blocks.insert(1, format_pressure_notice(pressure))

        blocks.append(
            f"\n---\n**Context Budget:** {used}/{budget} tokens "
            f"({100 * used // budget if budget else 0}% used)"
        )
        return "\n\n".join(blocks)

    def _render_at_tier(self, state: "KernelState", candidates, tier) -> List[str]:
        """Keep every block this tier allows, whole; reference the rest."""
        rendered: List[str] = []
        for key, text in candidates:
            if key == "input_context" and tier is not PressureTier.NORMAL:
                text = self._compose_input_context(state, tier)
                if not text:
                    continue
            if should_render_block(key, tier):
                rendered.append(text)
        if prior_step_mode(tier) == "references":
            prior = (state.context or {}).get("previous_step_results") or {}
            if prior:
                rendered.append(format_step_references(state.workflow_id, prior.keys()))
        return rendered

    def _compose_blocks(self, state: "KernelState") -> List[tuple]:
        """Every block the turn could show, at full fidelity, in priority order."""
        blocks: List[tuple] = []

        def add(key: str, text: str) -> None:
            if text and text.strip():
                blocks.append((key, text))

        mission = f"""## MISSION
**Workflow:** {state.workflow_id}
**Step:** {state.step_id}
**Task:** {state.task}
**Status:** {state.status}
**Turn:** {state.turn}
"""
        if state.last_error:
            mission += f"**CRITICAL ERROR TO FIX:** {state.last_error}\n"
        add("mission", mission)
        add("goal_state", self._build_goal_state_block(state.context or {}))

        if state.failure_ledger:
            lines = ["## FAILURE MEMORY (Do Not Repeat)"]
            for entry in state.failure_ledger[-5:]:
                tool = entry.get("tool", "unknown")
                err_type = entry.get("error_type", "UNKNOWN")
                lines.append(f"- `{tool}` → `{err_type}`: {entry.get('error', '')}")
            lines.append("Rule: if tool+params already failed recently, choose a different strategy.")
            add("failure_memory", "\n".join(lines))

        findings = state.internal_variables.get("research_findings", [])
        api_specs_accum = state.internal_variables.get("api_specs", [])
        if findings or api_specs_accum:
            kb_block = "## WHAT I KNOW SO FAR\n"
            if isinstance(api_specs_accum, list) and api_specs_accum:
                kb_block += f"**API Specs Extracted:** {len(api_specs_accum)} endpoint(s)\n"
                for spec in api_specs_accum:
                    if not isinstance(spec, dict):
                        continue
                    method = spec.get("method", "?")
                    path = spec.get("path") or spec.get("url") or "?"
                    kb_block += f"  - `{method} {path}` — {spec.get('summary', '')}\n"
            if isinstance(findings, list) and findings:
                kb_block += f"**Research Findings:** {len(findings)} item(s)\n"
                for finding in findings:
                    if isinstance(finding, dict):
                        kb_block += f"  - {finding.get('summary', finding.get('content_preview', finding))}\n"
                    else:
                        kb_block += f"  - {finding}\n"
            add("knowledge", kb_block)

        add("input_context", self._compose_input_context(state, PressureTier.NORMAL))

        recalled = (state.context or {}).get("_recalled")
        if recalled:
            add("recalled", self._build_recalled_block(recalled))

        if state.belief_state:
            belief_block = "## BELIEF STATE\n"
            for key, value in state.belief_state.items():
                belief_block += f"- `{key}`: {value}\n"
            add("belief_state", belief_block)

        thoughts_content = ""
        if state.thoughts:
            thoughts_content = "\n".join(f"- {thought}" for thought in state.thoughts[-10:])
        if state.scratchpad_notes:
            thoughts_content += f"\n{state.scratchpad_notes}"
        if thoughts_content.strip():
            add("working_memory", f"## WORKING MEMORY\n{thoughts_content.strip()}")

        ltm = state.internal_variables.get("long_term_memory", [])
        if ltm:
            ltm_block = "## LONG-TERM MEMORY (Compressed History)\n"
            render_limit = self.config.ltm_render_limit
            for item in ltm[-render_limit:]:
                ltm_block += f"- {item.get('summary', item) if isinstance(item, dict) else item}\n"
            hidden = len(ltm) - render_limit
            if hidden > 0:
                ltm_block += f"…and {hidden} older memories held in long-term memory\n"
            add("long_term_memory", ltm_block)

        if state.tool_history:
            history_block, _ = self._format_tool_history(
                state.tool_history, self.config.history_limit
            )
            add("tool_history", history_block)

        if state.internal_variables:
            skip_var_keys = {"long_term_memory", "research_findings", "api_specs",
                             "failure_ledger", PRESSURE_STATE_KEY}
            renderable = {
                key: value
                for key, value in state.internal_variables.items()
                if key not in skip_var_keys and not key.startswith("_")
            }
            if renderable:
                vars_block = "## INTERNAL STATE\n"
                for key, value in renderable.items():
                    vars_block += f"- `{key}`: {self._scrub_value(key, value)}\n"
                add("internal_variables", vars_block)

        return blocks

    def _compose_input_context(self, state: "KernelState", tier) -> str:
        """Input context, whole values only; bulk keys drop entirely under pressure."""
        if not state.context:
            return ""
        input_block = "## INPUT CONTEXT\n"
        prior = state.context.get("previous_step_results", {})
        if prior and prior_step_mode(tier) == "full":
            for step_id, step_result in prior.items():
                output = (step_result.get("output", step_result)
                          if isinstance(step_result, dict) else step_result)
                input_block += f"**[Prior Step: {step_id}]**\n{output}\n\n"

        skip_keys = {"previous_step_results", "workflow_id", "step_id",
                     "system_prompt", "_jarvis_context", "_auth_credentials",
                     "_agent_default_kernel_role",
                     "_goal", "_goal_id", "_goal_facts",
                     "_goal_facts_high_confidence", "_completed_steps",
                     "_plan_revision",
                     # Memory is rendered as what it is, in its own block. Under
                     # INPUT CONTEXT it read as part of the task.
                     "_recalled", "_athena_memory", "_ltm_summary"}
        other = {key: value for key, value in state.context.items() if key not in skip_keys}
        allowed = set(filter_input_context_keys(other.keys(), tier))
        cleaned = self._scrub_dict({k: v for k, v in other.items() if k in allowed})
        for key, value in cleaned.items():
            if hasattr(value, "model_json_schema"):
                try:
                    value = json.dumps(value.model_json_schema(), indent=2)
                except Exception:
                    pass
            input_block += f"- `{key}`: {value}\n"
        return input_block if input_block.strip() != "## INPUT CONTEXT" else ""

    def _format_tool_history(
        self,
        history: List[Any],
        budget: int,
    ) -> Tuple[str, int]:
        """Format recent tool history to fit within budget.

        Works backwards (most recent first), then reverses for chronological
        output. Entries are whole: a turn that does not fit is left out and
        stays retrievable via ``read_turn_result``, rather than being cut.
        """
        header = "## RECENT ACTIONS\n"
        header_tokens = self.count_tokens(header)
        formatted = []
        current = header_tokens
        withheld = 0

        # Process most-recent first (max 20 entries)
        for turn in reversed(history[-20:]):
            if hasattr(turn, "tool_name"):
                # KernelState.ToolResult model
                entry = (
                    f"**{turn.tool_name}** [{turn.status}]\n"
                    f"  Input: {json.dumps(turn.tool_input, default=str)}\n"
                    f"  Output: {turn.tool_output}"
                )
                if turn.error:
                    entry += f"\n  Error: {turn.error}"
            elif isinstance(turn, dict):
                # Legacy dict format
                entry = f"- {json.dumps(turn, default=str)}"
            else:
                continue

            cost = self.count_tokens(entry)
            if current + cost > budget:
                withheld += 1
                continue
            formatted.append(entry)
            current += cost

        if not formatted:
            return "", 0

        # Restore chronological order
        formatted.reverse()
        if withheld:
            formatted.append(
                f"…{withheld} earlier action(s) not inlined this turn — "
                "call TOOL: read_turn_result to read any of them in full."
            )
        return header + "\n\n".join(formatted), current

    # ------------------------------------------------------------------
    # Context building — Dict input (legacy backward compatibility)
    # ------------------------------------------------------------------

    def _build_context_from_dict(self, state: Dict[str, Any]) -> str:
        """Build context from a plain dict (legacy path)."""
        budget = self.config.usable_tokens
        sections: List[str] = []

        # 1. MISSION — always included
        mission = self._build_mission(state)
        budget -= self.count_tokens(mission)
        sections.append(mission)

        # 2. CURRENT PLAN
        plan = state.get("plan", "")
        if plan and budget > 0:
            block = f"## Current Plan\n{plan}"
            cost = self.count_tokens(block)
            if cost <= budget:
                sections.append(block)
                budget -= cost
            else:
                sections.append(self._truncate(block, budget))
                budget = 0

        # 3. SCRATCHPAD
        notes = state.get("notes", "")
        if notes and budget > 0:
            block = f"## Working Notes\n{notes}"
            cost = self.count_tokens(block)
            if cost <= budget:
                sections.append(block)
                budget -= cost
            else:
                sections.append(self._truncate(block, budget))
                budget = 0

        # 4. LONG-TERM MEMORY
        ltm = state.get("ltm_summary", "")
        if ltm and budget > 0:
            block = f"## Prior Context (Summary)\n{ltm}"
            cost = self.count_tokens(block)
            if cost <= budget:
                sections.append(block)
                budget -= cost
            else:
                sections.append(self._truncate(block, budget))
                budget = 0

        # 5. TOOL HISTORY
        history: List[Any] = state.get("tool_history", [])
        if history and budget > 0:
            history_budget = min(budget, self.config.history_limit)
            history_block = self._build_history_legacy(history, history_budget)
            if history_block:
                cost = self.count_tokens(history_block)
                sections.append(history_block)
                budget -= cost

        # 6. VARIABLES
        variables: Dict[str, Any] = state.get("variables", {})
        if variables and budget > 0:
            block = f"## Variables\n{json.dumps(variables, indent=2, default=str)}"
            cost = self.count_tokens(block)
            if cost <= budget:
                sections.append(block)
            else:
                sections.append(self._truncate(block, budget))

        return "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Auto-summarisation
    # ------------------------------------------------------------------

    async def auto_summarize_if_needed(
        self,
        state: Any,
        llm,
        memory,
    ) -> bool:
        """
        Trigger LTM compression when tool history is growing too large.

        For KernelState: compresses oldest 20% of tool_history into a
        text summary stored in internal_variables["long_term_memory"].

        For Dict: uses legacy threshold-based check.
        """
        # Handle KernelState
        if hasattr(state, "tool_history") and hasattr(state, "internal_variables"):
            return await self._summarize_state(state, llm)

        # Legacy dict path
        threshold = int(self.config.total_tokens * self.config.summarization_threshold)
        if self._used_tokens < threshold:
            return False
        if not memory or not getattr(memory, "ltm", None):
            logger.warning("auto_summarize triggered but memory.ltm not available")
            return False
        entries = state.get("tool_history", [])
        logger.info(
            f"Auto-summarise triggered ({self._used_tokens} >= {threshold} tokens), "
            f"compressing {len(entries)} entries"
        )
        summary = await memory.ltm.compress(entries, llm)
        await memory.ltm.save_summary(summary)
        self.reset_usage()
        return True

    async def _summarize_state(self, state: "KernelState", llm) -> bool:
        """Compress oldest tool history entries into long-term memory.

        Compression, not destruction (issue #59): the summary is built from a
        real evidence window per turn, the ORIGINALS are archived before the
        history is trimmed, the stored summary is labeled lossy, and a failed
        summarizer keeps the entries for the next cycle instead of replacing
        evidence with a tool-name list.
        """
        if len(state.tool_history) < 8:
            return False  # Not enough to compress

        # Calculate history token size
        history_text = ""
        for tr in state.tool_history:
            history_text += f"{tr.tool_name} {str(tr.tool_output)[:200]} "
        history_tokens = self.count_tokens(history_text)

        if history_tokens < self.config.history_limit * 0.8:
            return False  # Not at threshold yet

        logger.info("Auto-summarization triggered (tool history at 80%% capacity)")

        # Compress oldest 30% of entries
        num = len(state.tool_history)
        slice_idx = max(1, int(num * 0.3))
        old_entries = state.tool_history[:slice_idx]
        remaining = state.tool_history[slice_idx:]

        # Build summary from a real evidence base — an LLM asked to summarize
        # "WHAT was discovered" needs to actually see the discoveries.
        try:
            summary_prompt = (
                "Summarize these agent actions into 2-3 bullet points. "
                "Focus on WHAT was discovered and WHAT was attempted:\n"
            )
            for tr in old_entries:
                evidence = tr.tool_output
                summary_prompt += f"- {tr.tool_name}: {evidence}\n"

            if hasattr(llm, "generate"):
                result = await llm.generate(
                    messages=[{"role": "user", "content": summary_prompt}]
                )
                summary_text = result.get("content", "")
            else:
                # No LLM attached: mechanical summary, but the originals are
                # archived below — nothing is destroyed.
                tool_names = set(tr.tool_name for tr in old_entries)
                summary_text = f"Executed {len(old_entries)} actions: {', '.join(tool_names)}"
        except Exception as e:
            # A failed summarizer must not cost evidence: keep the entries
            # and let the next cycle retry. The old fallback replaced the
            # oldest 30% of the agent's history with a tool-name list.
            logger.warning(
                f"Summarization LLM call failed ({e}) — keeping tool history "
                f"intact for retry on the next cycle"
            )
            return False

        # Archive the originals BEFORE trimming — a summary is a view,
        # never the only copy. JSON-safe (checkpoints call model_dump_json).
        archive = state.internal_variables.setdefault("_archived_turns", [])
        for tr in old_entries:
            archive.append({
                "tool_name": tr.tool_name,
                "tool_input": json.loads(json.dumps(tr.tool_input, default=str)),
                "tool_output": str(tr.tool_output),
                "status": getattr(tr, "status", None),
                "error": getattr(tr, "error", None),
            })
        if len(archive) > self.config.archive_window:
            del archive[:-self.config.archive_window]

        # Store in long-term memory — labeled for what it is
        if "long_term_memory" not in state.internal_variables:
            state.internal_variables["long_term_memory"] = []
        state.internal_variables["long_term_memory"].append({
            "summary": f"[lossy summary of {len(old_entries)} turns — originals archived] {summary_text}",
            "turns_compressed": len(old_entries),
            "generation": 1,
            "archived": True,
            "timestamp": time.time(),
        })

        # Trim history
        state.tool_history = remaining
        logger.info(f"Compressed {len(old_entries)} turns into long-term memory")

        # Bound LTM itself — generational compaction (issue #69)
        await self._compact_ltm(state, llm)

        # Compression telemetry: entropy management must be visible, not
        # suspected. Rides in internal variables → rendered in INTERNAL STATE.
        stats = state.internal_variables.setdefault(
            "compression_stats",
            {"cycles": 0, "turns_compressed": 0, "epochs": 0, "max_generation": 1},
        )
        stats["cycles"] += 1
        stats["turns_compressed"] += len(old_entries)
        return True

    async def _compact_ltm(self, state: "KernelState", llm) -> bool:
        """Bound long_term_memory via generational epoch merges (issue #69).

        The failure mode this avoids is context collapse (ACE,
        arXiv:2510.04618): iteratively re-summarizing EVERYTHING erodes
        detail until memory is mush. Instead, on overflow only the OLDEST
        half is merged into one epoch summary — newest entries are never
        touched, so fidelity decays monotonically with age and recent
        memory stays verbatim. Generations are labeled so downstream
        reasoning can weight fidelity, and merged-away entries are archived
        first — compression, never destruction.
        """
        ltm = state.internal_variables.get("long_term_memory") or []
        if len(ltm) <= self.config.ltm_window:
            return False

        merge_count = max(2, self.config.ltm_window // 2)
        oldest = ltm[:merge_count]
        newest = ltm[merge_count:]

        def _text(item: Any) -> str:
            return item.get("summary", str(item)) if isinstance(item, dict) else str(item)

        def _gen(item: Any) -> int:
            return int(item.get("generation", 1)) if isinstance(item, dict) else 1

        generation = max(_gen(i) for i in oldest) + 1
        try:
            merge_prompt = (
                "Merge these agent memory entries into one dense record. "
                "Recall first: preserve every decision, discovery, error, and "
                "open question — drop only redundancy and filler:\n"
                + "\n".join(f"- {_text(i)}" for i in oldest)
            )
            if not hasattr(llm, "generate"):
                return False  # no LLM: keep entries; retry when one is attached
            result = await llm.generate(
                messages=[{"role": "user", "content": merge_prompt}]
            )
            epoch_text = result.get("content", "")
        except Exception as e:
            # A failed merge must not cost memory — keep entries, retry later.
            logger.warning(f"LTM epoch merge failed ({e}) — keeping entries for retry")
            return False

        # Archive the merged-away originals before replacing them.
        ltm_archive = state.internal_variables.setdefault("_archived_ltm", [])
        ltm_archive.extend(
            i if isinstance(i, dict) else {"summary": str(i)} for i in oldest
        )
        if len(ltm_archive) > self.config.archive_window:
            del ltm_archive[:-self.config.archive_window]

        epoch = {
            "summary": (
                f"[gen-{generation} epoch summary of {len(oldest)} older memories "
                f"— originals archived] {epoch_text}"
            ),
            "generation": generation,
            "merged_entries": len(oldest),
            "archived": True,
            "timestamp": time.time(),
        }
        state.internal_variables["long_term_memory"] = [epoch] + newest

        stats = state.internal_variables.setdefault(
            "compression_stats",
            {"cycles": 0, "turns_compressed": 0, "epochs": 0, "max_generation": 1},
        )
        stats["epochs"] += 1
        stats["max_generation"] = max(stats.get("max_generation", 1), generation)
        logger.info(
            f"LTM compacted: {len(oldest)} entries merged into gen-{generation} epoch"
        )
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_mission(self, state: Dict[str, Any]) -> str:
        wf = state.get("workflow_id", "unknown")
        step = state.get("step_id", "unknown")
        task = state.get("task", "")
        return f"## Mission\nWorkflow: {wf}  |  Step: {step}\nTask: {task}"

    def _build_history_legacy(self, history: List[Any], token_budget: int) -> str:
        """Include as many recent history entries as fit within the budget."""
        lines = ["## Tool History (recent)"]
        used = self.count_tokens(lines[0])
        selected = []
        for entry in reversed(history):
            line = f"- {json.dumps(entry, default=str)}"
            cost = self.count_tokens(line)
            if used + cost > token_budget:
                break
            selected.insert(0, line)
            used += cost
        if not selected:
            return ""
        return "\n".join(lines + selected)

    def _truncate(self, text: str, token_budget: int) -> str:
        """Truncate text to fit within the token budget (word boundary)."""
        words = text.split()
        max_words = max(1, int(token_budget / _TOKENS_PER_WORD))
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]) + " …[truncated]"
