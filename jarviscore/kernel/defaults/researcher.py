"""
6F: ResearcherSubAgent — Information gathering and research specialist.

The researcher searches for information, reads documentation, and
synthesizes findings into structured results.

Design decisions (from IA/CA analysis):
- Adopted: Phase-based tool contracts (CA — prevents tool misuse loops)
- Adopted: Multi-escalation search (IA — web_search → read_url → registry)
- Adopted: Research sufficiency check (avoiding IA's gap — explicit verification)
- Avoided: No research sufficiency check (IA bug — we add explicit sufficiency tracking)
- Avoided: Tight validation coupling (IA bug — keep validation simple)
"""

import logging
from typing import Any, Dict, List, Optional

from jarviscore.kernel.subagent import BaseSubAgent

logger = logging.getLogger(__name__)

# Research sufficiency thresholds
_MIN_SOURCES_FOR_SUFFICIENT = 2
_MIN_FACTS_FOR_SUFFICIENT = 1


class ResearcherSubAgent(BaseSubAgent):
    """
    Research subagent for the kernel.

    Tools:
    - search_registry: Search the function registry for existing code (thinking)
    - web_search: Search the web for information (thinking)
    - read_url: Read content from a URL (thinking)
    - note_finding: Record a research finding with source (thinking)
    - check_sufficiency: Verify if research is sufficient to answer (thinking)

    The researcher gathers information from multiple sources, tracks
    findings with provenance, and checks sufficiency before declaring done.
    Each finding is recorded with its source for evidence tracking.
    """

    def __init__(
        self,
        agent_id: str,
        llm_client,
        search_client=None,
        code_registry=None,
        redis_store=None,
        blob_storage=None,
    ):
        self.search_client = search_client
        self.code_registry = code_registry
        self._findings: List[Dict[str, Any]] = []
        self._sources: List[str] = []
        super().__init__(
            agent_id=agent_id,
            role="researcher",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a research specialist. You gather information from multiple "
            "sources, verify findings, and synthesize structured results.\n\n"
            "Workflow:\n"
            "1. Search the registry for existing relevant code/functions\n"
            "2. Use web_search for external information if needed\n"
            "3. Use read_url to dig deeper into specific sources\n"
            "4. Record each finding with note_finding\n"
            "5. Use check_sufficiency to verify you have enough information\n"
            "6. Only DONE when sufficiency check passes\n\n"
            "Rules:\n"
            "- Always cite your sources\n"
            "- Record at least one finding before declaring done\n"
            "- Check sufficiency before finishing"
        )

    def setup_tools(self) -> None:
        self.register_tool(
            "search_registry",
            self._tool_search_registry,
            "Search function registry. Params: {\"query\": \"<search terms>\", \"system\": \"<optional system>\"}",
            phase="thinking",
        )
        self.register_tool(
            "web_search",
            self._tool_web_search,
            "Search the web. Params: {\"query\": \"<search terms>\"}",
            phase="thinking",
        )
        self.register_tool(
            "read_url",
            self._tool_read_url,
            "Read content from URL. Params: {\"url\": \"<url>\"}",
            phase="thinking",
        )
        self.register_tool(
            "note_finding",
            self._tool_note_finding,
            "Record a finding. Params: {\"finding\": \"<text>\", \"source\": \"<source>\", \"confidence\": 0.8}",
            phase="thinking",
        )
        self.register_tool(
            "check_sufficiency",
            self._tool_check_sufficiency,
            "Check if research is sufficient. Params: {}",
            phase="thinking",
        )

    def _tool_search_registry(
        self, query: str, system: Optional[str] = None
    ) -> Dict[str, Any]:
        """Search the function registry for relevant code."""
        if not self.code_registry:
            return {"status": "unavailable", "results": []}

        try:
            results = self.code_registry.search(
                capabilities=[query] if query else None,
                system=system,
                limit=5,
            )
            source = f"registry::{query}"
            if source not in self._sources:
                self._sources.append(source)
            return {"status": "success", "count": len(results), "results": results}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_web_search(self, query: str) -> Dict[str, Any]:
        """Search the web for information."""
        if not self.search_client:
            return {"status": "unavailable", "results": []}

        try:
            results = self.search_client.search(query)
            if hasattr(results, "__await__"):
                results = await results
            source = f"web::{query}"
            if source not in self._sources:
                self._sources.append(source)
            return {"status": "success", "results": results}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_read_url(self, url: str) -> Dict[str, Any]:
        """Read content from a URL."""
        if not self.search_client:
            return {"status": "unavailable", "content": ""}

        try:
            content = self.search_client.read_url(url)
            if hasattr(content, "__await__"):
                content = await content
            source = f"url::{url}"
            if source not in self._sources:
                self._sources.append(source)
            return {"status": "success", "content": content}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _tool_note_finding(
        self, finding: str, source: str, confidence: float = 0.5
    ) -> Dict[str, Any]:
        """Record a research finding with source attribution."""
        entry = {
            "finding": finding,
            "source": source,
            "confidence": max(0.0, min(1.0, confidence)),
            "index": len(self._findings),
        }
        self._findings.append(entry)
        if source not in self._sources:
            self._sources.append(source)
        return {"recorded": True, "index": entry["index"], "total_findings": len(self._findings)}

    def _tool_check_sufficiency(self) -> Dict[str, Any]:
        """Check if research has gathered enough information."""
        has_enough_sources = len(self._sources) >= _MIN_SOURCES_FOR_SUFFICIENT
        has_enough_facts = len(self._findings) >= _MIN_FACTS_FOR_SUFFICIENT
        sufficient = has_enough_sources and has_enough_facts

        return {
            "sufficient": sufficient,
            "sources_count": len(self._sources),
            "findings_count": len(self._findings),
            "sources_needed": max(0, _MIN_SOURCES_FOR_SUFFICIENT - len(self._sources)),
            "findings_needed": max(0, _MIN_FACTS_FOR_SUFFICIENT - len(self._findings)),
        }

    @property
    def findings(self) -> List[Dict[str, Any]]:
        """All research findings from this run."""
        return list(self._findings)

    @property
    def sources(self) -> List[str]:
        """All sources consulted during this run."""
        return list(self._sources)

    async def run(self, task, context=None, max_turns=8, model=None):
        """Run with fresh findings."""
        self._findings = []
        self._sources = []
        return await super().run(task, context, max_turns, model)
