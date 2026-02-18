"""
ContextManager — Token budget and priority-stack prompt builder.

Manages what goes into an LLM context window for Kernel calls.
Two responsibilities:

1. Token counting — estimates token usage from text (word-count heuristic,
   same fallback used by llm.py for providers that don't return usage).

2. Context building — assembles a prompt from a priority-ordered stack,
   trimming lower-priority sections when the budget is exhausted:

   Priority (highest → lowest, never trimmed → first trimmed):
     1. MISSION       — workflow_id, step_id, task description (fixed)
     2. CURRENT PLAN  — active reasoning / next steps
     3. SCRATCHPAD    — working notes from this turn
     4. LONG-TERM MEM — compressed prior summaries
     5. TOOL HISTORY  — sliding window of recent tool calls
     6. VARIABLES     — input data / step outputs (fills remainder)

3. Auto-summarisation trigger — when cumulative token use crosses
   the configured threshold, signals the Kernel to compress and archive.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Tokens-per-word heuristic (matches llm.py Gemini fallback)
_TOKENS_PER_WORD: float = 1.3


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
    """
    total_tokens: int = 80_000
    output_reserve: int = 4_000
    system_reserve: int = 8_000
    history_limit: int = 20_000
    summarization_threshold: float = 0.8

    @property
    def usable_tokens(self) -> int:
        """Tokens available for context content after reserves."""
        return self.total_tokens - self.output_reserve - self.system_reserve


class ContextManager:
    """
    Manages LLM token budgets and assembles prioritised prompt context.

    Used by the Kernel before each LLM call to ensure the assembled
    prompt fits within the model's context window.

    Example:
        cm = ContextManager(BudgetConfig(total_tokens=32_000))
        context_str = cm.build_context({
            "workflow_id": "wf-1",
            "step_id": "step2",
            "task": "Analyse sales data",
            "plan": "1. Query API  2. Aggregate  3. Report",
            "notes": "API returns JSON...",
            "ltm_summary": "Prior run: fetched 500 records",
            "tool_history": [...],
            "variables": {"input_data": "..."},
        })
        triggered = await cm.auto_summarize_if_needed(state, llm, memory)
    """

    def __init__(self, config: Optional[BudgetConfig] = None):
        self.config = config or BudgetConfig()
        self._used_tokens: int = 0

    # ------------------------------------------------------------------
    # Token counting
    # ------------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        """
        Estimate token count from text using word-count heuristic.

        Uses `words * 1.3` — the same fallback as llm.py for providers
        that don't return usage metadata. Avoids tiktoken dependency.

        Args:
            text: Any string.

        Returns:
            Estimated token count (always >= 0).
        """
        if not text:
            return 0
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
    # Context building
    # ------------------------------------------------------------------

    def build_context(self, state: Dict[str, Any]) -> str:
        """
        Assemble a prompt context string from the priority stack.

        Sections are added in priority order. When the remaining budget
        is exhausted, lower-priority sections are truncated or dropped.

        Args:
            state: Dict with any combination of:
                workflow_id, step_id, task  — MISSION (always included)
                plan        — current reasoning / next steps
                notes       — working scratchpad notes
                ltm_summary — compressed long-term memory
                tool_history — list of recent tool-call dicts
                variables   — dict of input/output data

        Returns:
            Assembled context string ready for inclusion in an LLM prompt.
        """
        budget = self.config.usable_tokens
        sections: List[str] = []

        # 1. MISSION — always included, counts against budget
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

        # 3. SCRATCHPAD (working notes)
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

        # 5. TOOL HISTORY (sliding window capped at history_limit)
        history: List[Any] = state.get("tool_history", [])
        if history and budget > 0:
            history_budget = min(budget, self.config.history_limit)
            history_block = self._build_history(history, history_budget)
            if history_block:
                cost = self.count_tokens(history_block)
                sections.append(history_block)
                budget -= cost

        # 6. VARIABLES (fills remainder)
        variables: Dict[str, Any] = state.get("variables", {})
        if variables and budget > 0:
            import json
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
        state: Dict[str, Any],
        llm,
        memory,
    ) -> bool:
        """
        Trigger LTM compression when cumulative token use is high.

        If `used_tokens >= total_tokens * summarization_threshold`, calls
        memory.ltm.compress() and saves the result, then resets the counter.

        Args:
            state: Current kernel state (tool_history used as input to compress).
            llm:   UnifiedLLMClient instance.
            memory: UnifiedMemory instance (must have ltm tier active).

        Returns:
            True if summarisation was triggered, False otherwise.
        """
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_mission(self, state: Dict[str, Any]) -> str:
        wf = state.get("workflow_id", "unknown")
        step = state.get("step_id", "unknown")
        task = state.get("task", "")
        return f"## Mission\nWorkflow: {wf}  |  Step: {step}\nTask: {task}"

    def _build_history(self, history: List[Any], token_budget: int) -> str:
        """Include as many recent history entries as fit within the budget."""
        import json
        lines = ["## Tool History (recent)"]
        used = self.count_tokens(lines[0])
        # Walk most-recent first, prepend so output is chronological
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
