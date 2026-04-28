"""
EpistemicLedger — Deterministic enforcement of reasoning consistency.

Unlike the ConvergenceGovernor (which detects stalls after the fact),
the EpistemicLedger prevents wasteful actions BEFORE they execute.

Three enforcement mechanisms:

1. Search Dedup    — Blocks semantically duplicate search queries.
                     Uses Jaccard similarity on word sets (no NLP needed).
2. URL Dedup       — Blocks re-reading the same web page.
                     Normalises URLs before comparison.
3. Knowledge Plateau — Detects when no new knowledge is being generated
                       across consecutive turns. Injects signal, does NOT
                       force exit (that's the ConvergenceGovernor's job).

Integration:
    Created per run() invocation inside BaseSubAgent.
    Called between DECIDE and ACT phases of the OODA loop.
    On redirect: tool call is NOT executed, correction injected into state.

Design constraints:
    - Pure deterministic logic. No LLM calls, no embeddings, no NLP.
    - Zero external dependencies.
    - False positives (blocking a legit action) are worse than false negatives
      (allowing a redundant action). Thresholds are conservative.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

# Words that add no discriminative value to search queries
_STOP_WORDS: FrozenSet[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "between", "out", "off", "over", "under",
    "again", "then", "once", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "and", "but", "or", "if", "while", "that", "this", "what", "which",
    "who", "whom", "these", "those", "it", "its", "about", "get", "using",
    "use", "find", "search",
})

# URL query params that are tracking artifacts, not content identifiers
_TRACKING_PARAMS: FrozenSet[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
})

# Tools that perform web searches
_SEARCH_TOOLS: FrozenSet[str] = frozenset({
    "search_internet", "search_internet_batch",
})

# Tools that read URLs
_URL_READ_TOOLS: FrozenSet[str] = frozenset({
    "read_web_content", "browser_navigate",
})

# Jaccard similarity threshold for search dedup.
# 0.7 = conservative — catches near-exact repeats, allows related-but-different.
_SEARCH_SIMILARITY_THRESHOLD: float = 0.7

# Consecutive turns without knowledge growth before signaling plateau
_PLATEAU_THRESHOLD: int = 3


@dataclass
class ValidationResult:
    """Result of an epistemic consistency check."""
    action: Literal["allow", "redirect"] = "allow"
    reason: str = ""
    injection: str = ""  # Text injected into state.thoughts on redirect


@dataclass
class _SearchRecord:
    """A previously executed search query."""
    turn: int
    raw_query: str
    word_set: FrozenSet[str]


class EpistemicLedger:
    """
    Deterministic reasoning consistency enforcer.

    Sits between DECIDE and ACT in the OODA loop. Blocks redundant
    actions before they consume tokens and wall-clock time.

    Usage (inside BaseSubAgent.run):
        ledger = EpistemicLedger()

        # Before tool execution:
        verdict = ledger.validate_action(tool_name, params, turn, state)
        if verdict.action == "redirect":
            state.add_thought(f"[EPISTEMIC] {verdict.injection}")
            continue

        # After tool execution:
        ledger.record_outcome(tool_name, params, result, turn, state)

        # After recording:
        plateau = ledger.check_plateau(state, turn)
        if plateau:
            state.add_thought(f"[EPISTEMIC] {plateau}")
    """

    def __init__(self):
        # Search dedup state
        self._search_history: List[_SearchRecord] = []

        # URL dedup state — normalised URL → turn number
        self._url_history: Dict[str, int] = {}

        # Knowledge plateau tracking — (turn, knowledge_count) pairs
        self._knowledge_snapshots: List[Tuple[int, int]] = []

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def validate_action(
        self,
        tool_name: str,
        params: Dict[str, Any],
        turn: int,
        state: Any,
    ) -> ValidationResult:
        """
        Validate a proposed tool call against epistemic history.

        Called BEFORE tool execution. Returns:
          - allow:    proceed normally
          - redirect: block this call, inject correction into state

        Only validates tools with known dedup semantics (search, URL read).
        All other tools pass through unconditionally.
        """
        if tool_name in _SEARCH_TOOLS:
            return self._validate_search(tool_name, params, turn)

        if tool_name in _URL_READ_TOOLS:
            return self._validate_url_access(tool_name, params, turn)

        return ValidationResult(action="allow")

    def record_outcome(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        turn: int,
        state: Any,
    ) -> None:
        """
        Record a successful tool outcome for future dedup.

        Called AFTER tool execution. Only records successful calls —
        failed searches don't block retries with similar queries.
        """
        # Only record successful outcomes
        if isinstance(result, dict) and result.get("status") == "error":
            return

        if tool_name in _SEARCH_TOOLS:
            self._record_search(tool_name, params, turn)

        if tool_name in _URL_READ_TOOLS:
            self._record_urls_from_params(params, turn)

        # Also extract URLs from tool results (e.g. url_ids resolved to URLs)
        self._record_urls_from_result(result, turn)

    def check_plateau(self, state: Any, turn: int) -> Optional[str]:
        """
        Check if knowledge has stopped growing.

        Returns a signal string if knowledge count hasn't increased
        for PLATEAU_THRESHOLD consecutive recording turns. Returns
        None if knowledge is still growing.
        """
        current = self._count_knowledge(state)
        self._knowledge_snapshots.append((turn, current))

        if len(self._knowledge_snapshots) < _PLATEAU_THRESHOLD:
            return None

        recent = self._knowledge_snapshots[-_PLATEAU_THRESHOLD:]
        baseline = recent[0][1]

        if all(count == baseline for _, count in recent):
            return (
                f"KNOWLEDGE_PLATEAU: No new findings for "
                f"{_PLATEAU_THRESHOLD} consecutive action turns. "
                f"Total knowledge items: {current}. "
                f"You likely have enough to produce a useful result. "
                f"Call DONE with what you have."
            )

        return None

    # ──────────────────────────────────────────────────────────────────
    # Search dedup
    # ──────────────────────────────────────────────────────────────────

    def _validate_search(
        self, tool_name: str, params: Dict[str, Any], turn: int
    ) -> ValidationResult:
        """Check proposed search queries against history."""
        queries = self._extract_queries(tool_name, params)

        for query in queries:
            word_set = self._normalize_query(query)
            if not word_set:
                continue

            # Check against all previous searches
            for record in self._search_history:
                similarity = self._jaccard(word_set, record.word_set)
                if similarity >= _SEARCH_SIMILARITY_THRESHOLD:
                    logger.info(
                        f"[EPISTEMIC] Blocked redundant search: "
                        f"'{query}' ≈ '{record.raw_query}' "
                        f"(Jaccard={similarity:.2f}, turn {record.turn})"
                    )
                    return ValidationResult(
                        action="redirect",
                        reason=(
                            f"REDUNDANT_SEARCH: '{query}' is {similarity:.0%} "
                            f"similar to '{record.raw_query}' (turn {record.turn})"
                        ),
                        injection=(
                            f"You already searched for '{record.raw_query}' on "
                            f"turn {record.turn}. Those results are in your tool "
                            f"history. Use what you found or try a fundamentally "
                            f"different query with different keywords."
                        ),
                    )

        return ValidationResult(action="allow")

    def _record_search(
        self, tool_name: str, params: Dict[str, Any], turn: int
    ) -> None:
        """Record successful search queries for future dedup."""
        queries = self._extract_queries(tool_name, params)
        for query in queries:
            word_set = self._normalize_query(query)
            if word_set:
                self._search_history.append(
                    _SearchRecord(turn=turn, raw_query=query, word_set=word_set)
                )

    @staticmethod
    def _extract_queries(tool_name: str, params: Dict[str, Any]) -> List[str]:
        """Extract search query strings from tool params."""
        if tool_name == "search_internet":
            q = params.get("query", "")
            return [q] if q else []
        elif tool_name == "search_internet_batch":
            return params.get("queries", [])
        return []

    @staticmethod
    def _normalize_query(query: str) -> FrozenSet[str]:
        """Normalise a search query to a word set for comparison."""
        # Lowercase, strip punctuation, split
        cleaned = re.sub(r"[^\w\s]", " ", query.lower())
        words = cleaned.split()
        # Remove stop words and very short tokens
        meaningful = frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 1)
        return meaningful

    @staticmethod
    def _jaccard(a: FrozenSet[str], b: FrozenSet[str]) -> float:
        """Jaccard similarity between two word sets."""
        if not a and not b:
            return 1.0
        union = a | b
        if not union:
            return 0.0
        return len(a & b) / len(union)

    # ──────────────────────────────────────────────────────────────────
    # URL dedup
    # ──────────────────────────────────────────────────────────────────

    def _validate_url_access(
        self, tool_name: str, params: Dict[str, Any], turn: int
    ) -> ValidationResult:
        """Check proposed URL reads against history."""
        urls = self._extract_urls_from_params(params)

        for url in urls:
            normalised = self._normalize_url(url)
            if normalised in self._url_history:
                prev_turn = self._url_history[normalised]
                logger.info(
                    f"[EPISTEMIC] Blocked redundant URL read: "
                    f"{url} (already read on turn {prev_turn})"
                )
                return ValidationResult(
                    action="redirect",
                    reason=(
                        f"REDUNDANT_URL: Already read '{url}' on turn {prev_turn}"
                    ),
                    injection=(
                        f"You already read this URL on turn {prev_turn}. "
                        f"The content is in your tool history. Extract what "
                        f"you need from the existing result or find a different page."
                    ),
                )

        return ValidationResult(action="allow")

    def _record_urls_from_params(
        self, params: Dict[str, Any], turn: int
    ) -> None:
        """Record URLs from tool params."""
        for url in self._extract_urls_from_params(params):
            normalised = self._normalize_url(url)
            if normalised not in self._url_history:
                self._url_history[normalised] = turn

    def _record_urls_from_result(self, result: Any, turn: int) -> None:
        """Extract and record URLs discovered in tool results."""
        if not isinstance(result, dict):
            return
        # Common patterns in tool results
        for key in ("url", "urls", "source_url", "page_url"):
            val = result.get(key)
            if isinstance(val, str) and val.startswith("http"):
                normalised = self._normalize_url(val)
                if normalised not in self._url_history:
                    self._url_history[normalised] = turn
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.startswith("http"):
                        normalised = self._normalize_url(item)
                        if normalised not in self._url_history:
                            self._url_history[normalised] = turn

    @staticmethod
    def _extract_urls_from_params(params: Dict[str, Any]) -> List[str]:
        """Extract URL strings from tool params."""
        urls = []
        # read_web_content(urls=[...])
        url_list = params.get("urls", [])
        if isinstance(url_list, list):
            urls.extend(u for u in url_list if isinstance(u, str))
        # browser_navigate(url="...")
        url_single = params.get("url", "")
        if isinstance(url_single, str) and url_single.startswith("http"):
            urls.append(url_single)
        return urls

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalise a URL for comparison (strip tracking params, fragments)."""
        try:
            parsed = urlparse(url.strip().lower())
            # Remove tracking params and fragment
            query_params = parse_qs(parsed.query)
            filtered = {
                k: v for k, v in query_params.items()
                if k not in _TRACKING_PARAMS
            }
            clean = parsed._replace(
                fragment="",
                query=urlencode(filtered, doseq=True) if filtered else "",
                path=parsed.path.rstrip("/") or "/",
            )
            return urlunparse(clean)
        except Exception:
            return url.strip().lower().rstrip("/")

    # ──────────────────────────────────────────────────────────────────
    # Knowledge plateau
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _count_knowledge(state: Any) -> int:
        """Count total unique knowledge items in state."""
        count = 0
        if hasattr(state, "internal_variables"):
            iv = state.internal_variables
            findings = iv.get("research_findings", [])
            if isinstance(findings, list):
                count += len(findings)
            specs = iv.get("api_specs", [])
            if isinstance(specs, list):
                count += len(specs)
        return count
