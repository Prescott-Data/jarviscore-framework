"""
ResearcherSubAgent — Information gathering and research specialist.

Doctrine:
  The researcher follows a 4-phase protocol:
  1. SEARCHING — casting a wide net across registry, web, and codebase
  2. EXTRACTING — deep-reading specific URLs and documents
  3. VERIFYING — confirming findings against multiple sources
  4. DONE — synthesizing results into structured output

  Evidence contract: the researcher CANNOT exit without actionable findings.
  If no findings, it must explain what was searched and what was not found.

Design principles:
  - Phase-based tool contracts (prevents tool misuse loops)
  - Multi-escalation search (registry → web → read_url → codebase)
  - Research sufficiency check (explicit verification before DONE)
  - URL content caching (don't read the same URL twice within a session)
"""

import logging
import os
from typing import Any, Dict, List, Optional

from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.kernel.state import KernelState

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
    - read_file: Read a local file with pagination (thinking)
    - grep_codebase: Search codebase for patterns (thinking)
    - note_finding: Record a research finding with source (thinking)
    - check_sufficiency: Verify if research is sufficient to answer (thinking)

    The researcher gathers information from multiple sources, tracks
    findings with provenance, and checks sufficiency before declaring done.
    """

    SYSTEM_PROMPT = """\
You are a RESEARCH SPECIALIST in a multi-agent orchestration framework.
Your job: find accurate, actionable information from real sources. Not opinions. Not guesses. EVIDENCE.

## 4-PHASE PROTOCOL (follow in order)

### Phase 1: SEARCHING
Cast a wide net. Use multiple search strategies:
- search_registry for existing working code/functions
- web_search for external documentation and APIs
- grep_codebase for patterns in the local codebase
Goal: identify the 2-3 most promising leads.

### Phase 2: EXTRACTING
Deep-read the best leads:
- read_url to extract full content from web pages
- read_file to read local documentation/code files
- note_finding to record each discovered fact with its source
Goal: extract specific, usable information (endpoints, schemas, auth methods, code patterns).

### Phase 3: VERIFYING
Cross-reference findings:
- check_sufficiency to verify you have enough information
- If insufficient, go back to Phase 1 with refined queries
Goal: ensure findings are accurate and complete.

### Phase 4: DONE
Synthesize and report:
- DONE summary must include ALL findings with sources
- RESULT must contain structured data (API specs, code patterns, etc.)
- If you found NOTHING useful, say so explicitly — don't fabricate

## CRITICAL RULES

1. **EVIDENCE OR NOTHING** — Every finding must have a source. No guessing.
2. **CITE SOURCES** — Use note_finding for every useful piece of information.
3. **NO PREMATURE DONE** — Do NOT call DONE until check_sufficiency passes.
4. **DEPTH OVER BREADTH** — 2 deep, verified findings > 10 shallow ones.
5. **STRUCTURED OUTPUT** — RESULT should contain structured data the coder can use:
   - API specs: {"endpoint": "...", "method": "...", "auth": "...", "params": {...}}
   - Code patterns: {"pattern": "...", "example": "...", "source": "..."}
6. **REPORT FAILURES** — If you searched and found nothing, report what you searched
   and what was not found. This is valuable information for the caller.
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
        self._read_urls: set = set()  # URL content cache (dedup)
        super().__init__(
            agent_id=agent_id,
            role="researcher",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

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
            "read_file",
            self._tool_read_file,
            "Read a local file with pagination. Params: {\"path\": \"<file_path>\", \"offset\": 0, \"limit\": 200}",
            phase="thinking",
        )
        self.register_tool(
            "grep_codebase",
            self._tool_grep_codebase,
            "Search codebase for a pattern. Params: {\"pattern\": \"<search pattern>\", \"path\": \"<optional dir>\"}",
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

    # ─────────────────────────────────────────────────────────────
    # Tools
    # ─────────────────────────────────────────────────────────────

    def _tool_search_registry(
        self, query: str, system: Optional[str] = None, **kwargs,
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

    async def _tool_web_search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search the web for information."""
        if not self.search_client:
            return {"status": "unavailable", "results": [],
                    "message": "No search client configured. Try read_file or grep_codebase instead."}

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

    async def _tool_read_url(self, url: str, **kwargs) -> Dict[str, Any]:
        """Read content from a URL (with session-scoped dedup)."""
        if not self.search_client:
            return {"status": "unavailable", "content": ""}

        # Dedup: don't read the same URL twice in one session
        if url in self._read_urls:
            return {
                "status": "cached",
                "content": "",
                "message": f"URL already read in this session. Use note_finding to record what you found."
            }

        try:
            # InternetSearch provides extract_content(), not read_url()
            result = self.search_client.extract_content(url, max_length=8000)
            if hasattr(result, "__await__"):
                result = await result

            self._read_urls.add(url)
            source = f"url::{url}"
            if source not in self._sources:
                self._sources.append(source)

            # extract_content returns {"url", "title", "content", "success", "word_count"}
            if isinstance(result, dict):
                if result.get("success"):
                    content = result.get("content", "")
                    title = result.get("title", "")
                    return {
                        "status": "success",
                        "title": title,
                        "content": content,
                        "word_count": result.get("word_count", 0),
                    }
                else:
                    return {"status": "error", "error": result.get("error", "Extraction failed")}
            else:
                # Fallback: raw string content
                content = str(result)
                if len(content) > 8000:
                    content = content[:8000] + "\n\n... [truncated]"
                return {"status": "success", "content": content}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _tool_read_file(
        self,
        path: str,
        offset: int = 0,
        limit: int = 200,
        **kwargs,
    ) -> Dict[str, Any]:
        """Read a local file with pagination.

        Returns lines from offset to offset+limit. Use offset to paginate
        through large files.
        """
        try:
            if not os.path.exists(path):
                return {"status": "error", "error": f"File not found: {path}"}
            if not os.path.isfile(path):
                return {"status": "error", "error": f"Not a file: {path}"}

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset:offset + limit]
            content = "".join(selected)

            source = f"file::{path}"
            if source not in self._sources:
                self._sources.append(source)

            return {
                "status": "success",
                "content": content,
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < total_lines,
                "next_offset": offset + limit if (offset + limit) < total_lines else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _tool_grep_codebase(
        self,
        pattern: str,
        path: str = ".",
        **kwargs,
    ) -> Dict[str, Any]:
        """Search codebase for a pattern using simple string matching.

        Returns matching file paths and line numbers. Limited to 20 results.
        """
        try:
            import subprocess
            result = subprocess.run(
                ["grep", "-rnI", "--include=*.py", "-l", pattern, path],
                capture_output=True, text=True, timeout=10,
            )
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()][:20]

            if not files:
                return {"status": "success", "matches": [], "message": "No matches found."}

            # Get context lines for top 5 matches
            matches = []
            for filepath in files[:5]:
                try:
                    ctx_result = subprocess.run(
                        ["grep", "-n", pattern, filepath],
                        capture_output=True, text=True, timeout=5,
                    )
                    lines = ctx_result.stdout.strip().split("\n")[:5]
                    matches.append({
                        "file": filepath,
                        "lines": lines,
                    })
                except Exception:
                    matches.append({"file": filepath, "lines": []})

            source = f"grep::{pattern}"
            if source not in self._sources:
                self._sources.append(source)

            return {
                "status": "success",
                "total_files": len(files),
                "matches": matches,
            }
        except FileNotFoundError:
            return {"status": "error", "error": "grep not available on this system"}
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": "Search timed out"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _tool_note_finding(
        self, finding: str, source: str, confidence: float = 0.5, **kwargs,
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

    def _tool_check_sufficiency(self, **kwargs) -> Dict[str, Any]:
        """Check if research has gathered enough information."""
        has_enough_sources = len(self._sources) >= _MIN_SOURCES_FOR_SUFFICIENT
        has_enough_facts = len(self._findings) >= _MIN_FACTS_FOR_SUFFICIENT
        sufficient = has_enough_sources and has_enough_facts

        guidance = ""
        if not sufficient:
            if not has_enough_sources:
                guidance += f"Need {_MIN_SOURCES_FOR_SUFFICIENT - len(self._sources)} more source(s). "
            if not has_enough_facts:
                guidance += f"Need {_MIN_FACTS_FOR_SUFFICIENT - len(self._findings)} more finding(s). "
            guidance += "Go back to Phase 1 (SEARCHING) with refined queries."
        else:
            guidance = "Research is sufficient. You may call DONE with your findings."

        return {
            "sufficient": sufficient,
            "sources_count": len(self._sources),
            "findings_count": len(self._findings),
            "sources": self._sources,
            "guidance": guidance,
        }

    @property
    def findings(self) -> List[Dict[str, Any]]:
        """All research findings from this run."""
        return list(self._findings)

    @property
    def sources(self) -> List[str]:
        """All sources consulted during this run."""
        return list(self._sources)

    async def run(self, task, context=None, max_turns=15, model=None, **kwargs):
        """Run with fresh findings and URL cache."""
        self._findings = []
        self._sources = []
        self._read_urls = set()
        return await super().run(task, context, max_turns, model, **kwargs)
