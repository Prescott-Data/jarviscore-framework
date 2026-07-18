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
        prior_step_value_limit:    Chars of each prior step output shown inline.
        context_value_limit:       Chars of each input-context value shown inline.
        belief_value_limit:        Chars of each belief-state value shown inline.
        memory_item_limit:         Chars of each finding / LTM item shown inline.
        internal_var_limit:        Chars of each internal variable shown inline.
        history_value_limit:       Chars of each tool-history input/output shown inline.
        state_keys_limit:          Max keys rendered per state dict (overflow is
                                   announced by name, never silently dropped).

    All char limits default to the historical values; every cut they cause
    is marked in the rendered context (see issue #55) — an agent that KNOWS
    data is missing asks for the rest; one that doesn't confabulates.
    """
    total_tokens: int = 80_000
    output_reserve: int = 4_000
    system_reserve: int = 8_000
    history_limit: int = 20_000
    summarization_threshold: float = 0.8
    prior_step_value_limit: int = 2000
    context_value_limit: int = 800
    belief_value_limit: int = 200
    memory_item_limit: int = 200
    internal_var_limit: int = 200
    history_value_limit: int = 600
    state_keys_limit: int = 10

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
    def _clip(value: Any, limit: int) -> str:
        """Render a value for the context window — cut honestly, never silently.

        Values within the limit render byte-identical to ``str(value)``.
        Longer values are cut WITH an explicit marker, because the agent
        reads these blocks as its world state: a model that knows data is
        missing asks for the rest; a model that doesn't confabulates.
        """
        text = str(value)
        if len(text) <= limit:
            return text
        return f"{text[:limit]}…[truncated: showing {limit} of {len(text)} chars]"

    @staticmethod
    def _visible_items(
        data: Dict[str, Any], limit: int
    ) -> Tuple[List[Tuple[str, Any]], str]:
        """Cap a state dict at *limit* keys — recency wins, overflow is named.

        Returns (visible_items, overflow_notice). The MOST RECENTLY inserted
        keys survive (dicts preserve insertion order; the newest state is the
        most likely to matter). Hidden keys are announced BY NAME so the agent
        keeps an index of its own state even when the values don't fit —
        silent key loss decided by insertion order was issue #56.
        """
        items = list(data.items())
        if len(items) <= limit:
            return items, ""
        visible = items[-limit:]
        hidden = [k for k, _ in items[:-limit]]
        notice = (
            f"…and {len(hidden)} earlier key(s) not shown: "
            + ", ".join(f"`{k}`" for k in hidden)
            + " (values hidden — re-derive or ask if needed)\n"
        )
        return visible, notice

    # ------------------------------------------------------------------
    # Context building — KernelState input (preferred)
    # ------------------------------------------------------------------

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
        """Build context from a KernelState Pydantic model."""
        budget = self.config.usable_tokens
        blocks: List[str] = []
        used = 0

        def _add_block(block: str, max_tokens: Optional[int] = None) -> bool:
            """Add a block if it fits within budget. Returns True if added."""
            nonlocal used
            cost = self.count_tokens(block)
            limit = min(budget - used, max_tokens) if max_tokens else budget - used
            if cost <= 0 or limit <= 0:
                return False
            if cost > limit:
                # Truncate to fit — honestly (issue #55)
                char_limit = int(limit * 4)  # ~4 chars per token
                original_len = len(block)
                block = (
                    block[:char_limit]
                    + f"\n…[block truncated to fit budget: showing {char_limit} of {original_len} chars]"
                )
                cost = self.count_tokens(block)
            blocks.append(block)
            used += cost
            return True

        # ═══ BLOCK 1: MISSION (Fixed — Never Trimmed) ═══
        mission = f"""## MISSION
**Workflow:** {state.workflow_id}
**Step:** {state.step_id}
**Task:** {state.task}
**Status:** {state.status}
**Turn:** {state.turn}
"""
        if state.last_error:
            mission += f"**CRITICAL ERROR TO FIX:** {state.last_error}\n"
        _add_block(mission)

        # ═══ BLOCK 2: FAILURE MEMORY (High Priority) ═══
        if state.failure_ledger:
            lines = ["## FAILURE MEMORY (Do Not Repeat)"]
            for entry in state.failure_ledger[-5:]:
                tool = entry.get("tool", "unknown")
                err_type = entry.get("error_type", "UNKNOWN")
                err_msg = self._clip(entry.get("error", ""), 180)
                lines.append(f"- `{tool}` → `{err_type}`: {err_msg}")
            lines.append("Rule: if tool+params already failed recently, choose a different strategy.")
            _add_block("\n".join(lines))

        # ═══ BLOCK 3: KNOWLEDGE ACCUMULATOR (High Priority) ═══
        # Surfaces accumulated research findings and API specs so the agent
        # can see what it has already discovered — prevents blind re-searching.
        findings = state.internal_variables.get("research_findings", [])
        api_specs_accum = state.internal_variables.get("api_specs", [])
        if findings or api_specs_accum:
            kb_block = "## WHAT I KNOW SO FAR\n"
            if isinstance(api_specs_accum, list) and api_specs_accum:
                kb_block += f"**API Specs Extracted:** {len(api_specs_accum)} endpoint(s)\n"
                for spec in api_specs_accum[-8:]:
                    if not isinstance(spec, dict):
                        continue
                    method = spec.get("method", "?")
                    path = spec.get("path") or spec.get("url") or "?"
                    summary_text = self._clip(spec.get("summary", ""), 80)
                    kb_block += f"  - `{method} {path}` — {summary_text}\n"
            if isinstance(findings, list) and findings:
                kb_block += f"**Research Findings:** {len(findings)} item(s)\n"
                for finding in findings[-5:]:
                    if isinstance(finding, dict):
                        kb_block += f"  - {self._clip(finding.get('summary', finding.get('content_preview', finding)), self.config.memory_item_limit)}\n"
                    else:
                        kb_block += f"  - {self._clip(finding, self.config.memory_item_limit)}\n"
            _add_block(kb_block, max_tokens=4000)

        # ═══ BLOCK 4: INPUT CONTEXT (High Priority) ═══
        if state.context:
            input_block = "## INPUT CONTEXT\n"
            # Prior step outputs get highest priority
            prior = state.context.get("previous_step_results", {})
            if prior:
                for step_id, step_result in prior.items():
                    output = step_result.get("output", step_result) if isinstance(step_result, dict) else step_result
                    output_str = self._clip(output, self.config.prior_step_value_limit)
                    input_block += f"**[Prior Step: {step_id}]**\n{output_str}\n\n"

            # Other context fields (skip internal keys)
            skip_keys = {"previous_step_results", "workflow_id", "step_id",
                          "system_prompt", "_jarvis_context", "_auth_credentials",
                          "_agent_default_kernel_role"}
            other = {k: v for k, v in state.context.items() if k not in skip_keys}
            if other:
                cleaned = self._scrub_dict(other)
                visible, overflow = self._visible_items(cleaned, self.config.state_keys_limit)
                for k, v in visible:
                    if hasattr(v, "model_json_schema"):
                        # Render Pydantic BaseModels as JSON schemas for the LLM
                        try:
                            import json
                            val_str = json.dumps(v.model_json_schema(), indent=2)
                        except Exception:
                            val_str = self._clip(v, self.config.context_value_limit)
                    else:
                        val_str = self._clip(v, self.config.context_value_limit)
                    input_block += f"- `{k}`: {val_str}\n"
                input_block += overflow
            _add_block(input_block, max_tokens=8000)

        # ═══ BLOCK 5: BELIEF STATE (Medium Priority) ═══
        if state.belief_state:
            belief_block = "## BELIEF STATE\n"
            visible, overflow = self._visible_items(state.belief_state, self.config.state_keys_limit)
            for k, v in visible:
                belief_block += f"- `{k}`: {self._clip(v, self.config.belief_value_limit)}\n"
            belief_block += overflow
            _add_block(belief_block, max_tokens=1000)

        # ═══ BLOCK 6: SCRATCHPAD / THOUGHTS (Medium Priority) ═══
        thoughts_content = ""
        if state.thoughts:
            thoughts_content = "\n".join(f"- {t}" for t in state.thoughts[-10:])
        if state.scratchpad_notes:
            thoughts_content += f"\n{state.scratchpad_notes}"
        if thoughts_content.strip():
            _add_block(f"## WORKING MEMORY\n{thoughts_content.strip()}", max_tokens=3000)

        # ═══ BLOCK 7: LONG-TERM MEMORY (Medium Priority) ═══
        ltm = state.internal_variables.get("long_term_memory", [])
        if ltm:
            ltm_block = "## LONG-TERM MEMORY (Compressed History)\n"
            for item in ltm[-5:]:
                if isinstance(item, dict):
                    ltm_block += f"- {self._clip(item.get('summary', str(item)), self.config.memory_item_limit)}\n"
                else:
                    ltm_block += f"- {self._clip(item, self.config.memory_item_limit)}\n"
            _add_block(ltm_block, max_tokens=2000)

        # ═══ BLOCK 8: TOOL HISTORY (Sliding Window) ═══
        history_budget = min(self.config.history_limit, budget - used - 2000)
        if history_budget > 0 and state.tool_history:
            history_block, history_tokens = self._format_tool_history(
                state.tool_history, history_budget
            )
            if history_block:
                blocks.append(history_block)
                used += history_tokens

        # ═══ BLOCK 9: VARIABLES (Fill Remaining) ═══
        remaining = budget - used
        if remaining > 500 and state.internal_variables:
            vars_block = "## INTERNAL STATE\n"
            # Skip keys that are surfaced by dedicated blocks above.
            # Filter FIRST, then cap — skipped keys must not consume the
            # visibility budget of real ones (issue #56).
            skip_var_keys = {"long_term_memory", "research_findings", "api_specs", "failure_ledger"}
            renderable = {
                key: value
                for key, value in state.internal_variables.items()
                if key not in skip_var_keys and not key.startswith("_")
            }
            visible, overflow = self._visible_items(renderable, self.config.state_keys_limit)
            for key, value in visible:
                value_str = self._clip(self._scrub_value(key, value), self.config.internal_var_limit)
                vars_block += f"- `{key}`: {value_str}\n"
            vars_block += overflow
            vars_cost = self.count_tokens(vars_block)
            if vars_cost < remaining:
                blocks.append(vars_block)
                used += vars_cost

        # ═══ BUDGET STATUS ═══
        budget_line = (
            f"\n---\n"
            f"**Context Budget:** {used}/{budget} tokens ({100*used//budget if budget else 0}% used)"
        )
        blocks.append(budget_line)

        return "\n\n".join(blocks)

    def _format_tool_history(
        self,
        history: List[Any],
        budget: int,
    ) -> Tuple[str, int]:
        """Format recent tool history to fit within budget.

        Works backwards (most recent first), then reverses for
        chronological output. Each entry is truncated to prevent
        a single large output from consuming the entire budget.
        """
        header = "## RECENT ACTIONS\n"
        header_tokens = self.count_tokens(header)
        formatted = []
        current = header_tokens

        # Process most-recent first (max 20 entries)
        for turn in reversed(history[-20:]):
            if hasattr(turn, "tool_name"):
                # KernelState.ToolResult model
                output_str = self._clip(turn.tool_output, self.config.history_value_limit)
                entry = (
                    f"**{turn.tool_name}** [{turn.status}]\n"
                    f"  Input: {self._clip(json.dumps(turn.tool_input, default=str), self.config.history_value_limit)}\n"
                    f"  Output: {output_str}"
                )
                if turn.error:
                    entry += f"\n  Error: {self._clip(turn.error, 200)}"
            elif isinstance(turn, dict):
                # Legacy dict format
                entry = f"- {json.dumps(turn, default=str)[:500]}"
            else:
                continue

            cost = self.count_tokens(entry)
            if current + cost > budget:
                break
            formatted.append(entry)
            current += cost

        if not formatted:
            return "", 0

        # Restore chronological order
        formatted.reverse()
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
        """Compress oldest tool history entries into long-term memory."""
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

        # Build summary (LLM or fallback)
        try:
            summary_prompt = (
                "Summarize these agent actions into 2-3 bullet points. "
                "Focus on WHAT was discovered and WHAT was attempted:\n"
            )
            for tr in old_entries:
                summary_prompt += f"- {tr.tool_name}: {str(tr.tool_output)[:100]}\n"

            if hasattr(llm, "generate"):
                result = await llm.generate(
                    messages=[{"role": "user", "content": summary_prompt}]
                )
                summary_text = result.get("content", "")[:500]
            else:
                # Fallback: mechanical summary
                tool_names = set(tr.tool_name for tr in old_entries)
                summary_text = f"Executed {len(old_entries)} actions: {', '.join(tool_names)}"
        except Exception as e:
            logger.warning(f"Summarization LLM call failed: {e}")
            tool_names = set(tr.tool_name for tr in old_entries)
            summary_text = f"Executed {len(old_entries)} actions: {', '.join(tool_names)}"

        # Store in long-term memory
        if "long_term_memory" not in state.internal_variables:
            state.internal_variables["long_term_memory"] = []
        state.internal_variables["long_term_memory"].append({
            "summary": summary_text,
            "turns_compressed": len(old_entries),
            "timestamp": time.time(),
        })

        # Trim history
        state.tool_history = remaining
        logger.info(f"Compressed {len(old_entries)} turns into long-term memory")
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
