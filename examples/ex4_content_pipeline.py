"""
Example 4 — Content Production Pipeline
========================================
Profile  : CustomAgent
Mode     : Distributed (SWIM P2P + WorkflowEngine)
Workflow : research → write → seo → publish  (sequential, depends_on)

This example shows CustomAgent in workflow mode: agents implement execute_task()
directly with pure Python logic — no LLM code generation. Cross-step data flows
through RedisMemoryAccessor, which reads step outputs stored by the WorkflowEngine.

Phases exercised
----------------
Phase 1  : LocalBlobStorage saves drafts, SEO metadata, and final article at
           each stage. Blob paths are predictable for CI/CD verification.
Phase 4  : MailboxManager — PublisherAgent sends completion notification to
           ResearcherAgent on publish.
Phase 5  : record_step_execution() called per step; Prometheus histogram visible.
Phase 7  : Reactive WorkflowEngine dispatches steps in dependency order;
           WorkflowState serialised to Redis between steps for crash recovery.
Phase 8  : UnifiedMemory per agent; RedisMemoryAccessor used by WriterAgent and
           SEOAgent to read previous step outputs; LongTermMemory.compress()
           called after publish to update style notes for future runs.
Phase 9  : Auto-injected self._redis_store, self._blob_storage, self.mailbox.

Prerequisites
-------------
    docker compose -f docker-compose.infra.yml up -d
    cp .env.example .env  # set CLAUDE_API_KEY
    pip install -e ".[redis,prometheus]"
    python examples/ex4_content_pipeline.py

Verification
------------
    redis-cli keys "*content-pipeline*"
    ls -la blob_storage/content/
    redis-cli get ltm:content-pipeline      # LTM summary after publish
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import CustomAgent
from jarviscore.memory import UnifiedMemory
from jarviscore.context import RedisMemoryAccessor
from jarviscore.telemetry.metrics import record_step_execution

WORKFLOW_ID = "content-pipeline"
REDIS_URL   = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TOPIC       = "The Future of AI Agents in 2026"


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — RESEARCH AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class ResearchAgent(CustomAgent):
    """
    Gathers background material on the topic.
    No LLM — produces structured research notes in pure Python.
    Saves raw research notes to blob.
    """
    role = "researcher"
    capabilities = ["research", "information_gathering"]

    async def setup(self):
        await super().setup()
        # Phase 9: stores injected before setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="research",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._logger.info(f"[{self.role}] setup complete")

    async def execute_task(self, task: dict) -> dict:
        topic = task.get("task", TOPIC)
        t_start = time.time()

        # Simulate research — produce structured notes
        research = {
            "topic": topic,
            "sources_checked": 12,
            "key_themes": [
                "Autonomous decision-making without human oversight",
                "Multi-agent collaboration and swarm intelligence",
                "Tool use: web, code execution, file manipulation",
                "Memory persistence: episodic + long-term",
                "Agentic frameworks: JarvisCore, LangGraph, AutoGen",
            ],
            "statistics": [
                "40% of enterprise software will include agentic AI by 2027 (Gartner)",
                "AI agent market expected to reach $47B by 2030",
                "Leading use-cases: customer support, coding, research, ops automation",
            ],
            "notable_projects": [
                "Devin (Cognition) — software engineering agent",
                "Claude Computer Use — desktop automation",
                "JarvisCore — P2P multi-agent framework",
                "AutoGPT — pioneer autonomous agent project",
            ],
            "research_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # Phase 1: save raw research to blob
        if self._blob_storage:
            import json
            blob_path = f"content/research/{WORKFLOW_ID}.json"
            await self._blob_storage.save(blob_path, json.dumps(research, indent=2))
            self._logger.info(f"[{self.role}] research saved to blob: {blob_path}")

        # Phase 8: log to episodic ledger
        if self.memory.episodic:
            await self.memory.episodic.append({
                "event": "research_completed",
                "topic": topic,
                "sources": research["sources_checked"],
                "ts": time.time(),
            })

        # Phase 5: record step execution metrics
        duration = time.time() - t_start
        record_step_execution(duration=duration, status="completed")

        return {"status": "success", "output": research}


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — WRITER AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class WriterAgent(CustomAgent):
    """
    Drafts the article from research notes.
    Uses RedisMemoryAccessor to read the research step output.
    """
    role = "writer"
    capabilities = ["writing", "content_creation"]

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="write",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

        # Phase 8: load LTM style notes from previous runs
        self._style_notes = ""
        if self.memory.ltm:
            ltm_data = await self.memory.ltm.load_summary()
            if ltm_data:
                self._style_notes = ltm_data
                self._logger.info(f"[{self.role}] LTM style notes loaded from prior run")

    async def execute_task(self, task: dict) -> dict:
        topic = task.get("task", TOPIC)
        t_start = time.time()

        # Phase 8: RedisMemoryAccessor reads research output from Redis.
        # accessor.get() strips the outer Redis hash wrapper; the inner
        # value is the full execute_task return: {"status": ..., "output": {...}}
        research = {}
        if self._redis_store:
            accessor = RedisMemoryAccessor(self._redis_store, WORKFLOW_ID)
            raw = accessor.get("research")
            research = raw.get("output", raw) if isinstance(raw, dict) else {}

        # Build article from research (template-based for reliability)
        themes    = research.get("key_themes", []) if research else []
        stats     = research.get("statistics", []) if research else []
        projects  = research.get("notable_projects", []) if research else []

        themes_md = "\n".join(f"- {t}" for t in themes) or "- AI agents are becoming more capable"
        stats_md  = "\n".join(f"- {s}" for s in stats) or "- Market growing rapidly"
        proj_md   = "\n".join(f"- {p}" for p in projects) or "- Multiple frameworks available"

        style_hint = f"\n\n<!-- Style notes: {self._style_notes[:100]} -->" if self._style_notes else ""

        draft = f"""# {topic}

## Introduction

Artificial intelligence agents are transforming how software is built and operated.
Unlike traditional AI systems that respond to single queries, agents autonomously plan,
act, and adapt — completing complex multi-step tasks without constant human direction.{style_hint}

## Key Themes

{themes_md}

## Market Reality

{stats_md}

## Notable Projects Shaping the Space

{proj_md}

## The Technical Foundation

Modern AI agents rely on four core capabilities:

1. **Reasoning** — LLMs that can break down complex goals into sub-tasks
2. **Tool use** — web search, code execution, file I/O, API calls
3. **Memory** — short-term context + long-term storage for continuity
4. **Orchestration** — frameworks like JarvisCore that coordinate multi-agent workflows

## What Comes Next

The next 12–18 months will see AI agents move from experimental to production-grade
infrastructure. Expect tighter integration with enterprise systems, better safety
controls, and multi-agent collaboration becoming the norm rather than the exception.

## Conclusion

AI agents represent a fundamental shift in software architecture. Teams that invest
in agentic infrastructure today will have a significant competitive advantage
by the time the technology matures into mainstream adoption.

---
*Research-backed draft — {time.strftime('%Y-%m-%d')}*
"""

        # Phase 1: save draft to blob
        if self._blob_storage:
            slug = topic.replace(" ", "_").replace("/", "-")
            blob_path = f"content/drafts/{slug}.md"
            await self._blob_storage.save(blob_path, draft)
            self._logger.info(f"[{self.role}] draft saved: {blob_path}")

        # Phase 8: episodic log
        if self.memory.episodic:
            await self.memory.episodic.append({
                "event": "draft_written",
                "word_count": len(draft.split()),
                "ts": time.time(),
            })

        # Phase 5
        record_step_execution(duration=time.time() - t_start, status="completed")

        return {"status": "success", "output": {"draft": draft, "word_count": len(draft.split())}}


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — SEO AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class SEOAgent(CustomAgent):
    """
    Optimises the draft for search engines.
    Reads the draft via RedisMemoryAccessor, computes SEO metadata, saves to blob.
    """
    role = "seo"
    capabilities = ["seo", "content_optimization", "keyword_analysis"]

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="seo",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def execute_task(self, task: dict) -> dict:
        t_start = time.time()

        # Phase 8: read draft from write step via Redis
        draft_output = {}
        if self._redis_store:
            accessor = RedisMemoryAccessor(self._redis_store, WORKFLOW_ID)
            raw = accessor.get("write")
            draft_output = raw.get("output", raw) if isinstance(raw, dict) else {}

        draft = draft_output.get("draft", "") if isinstance(draft_output, dict) else ""
        word_count = draft_output.get("word_count", 0) if isinstance(draft_output, dict) else 0

        # Compute SEO metadata
        target_keywords = ["AI agents", "autonomous AI", "multi-agent systems", "AI orchestration"]
        keyword_density = {}
        for kw in target_keywords:
            count = draft.lower().count(kw.lower()) if draft else 0
            keyword_density[kw] = round(count / max(word_count, 1) * 100, 2)

        seo_metadata = {
            "title_tag": f"{TOPIC} | JarvisCore Framework",
            "meta_description": (
                "Discover how AI agents are reshaping software in 2026. "
                "Learn about autonomous agents, multi-agent collaboration, "
                "and production-ready orchestration frameworks."
            ),
            "target_keywords": target_keywords,
            "keyword_density": keyword_density,
            "readability_score": 72,        # Flesch score approximation
            "estimated_read_time_min": max(1, word_count // 200),
            "seo_score": 85,
            "recommendations": [
                "Add internal links to related posts",
                "Include a FAQ section for long-tail keywords",
                "Add an author bio for E-E-A-T signals",
            ],
        }

        # Phase 1: save SEO metadata to blob
        if self._blob_storage:
            import json
            blob_path = f"content/seo/{WORKFLOW_ID}-metadata.json"
            await self._blob_storage.save(blob_path, json.dumps(seo_metadata, indent=2))
            self._logger.info(f"[{self.role}] SEO metadata saved: {blob_path}")

        # Phase 8: episodic log
        if self.memory.episodic:
            await self.memory.episodic.append({
                "event": "seo_completed",
                "seo_score": seo_metadata["seo_score"],
                "ts": time.time(),
            })

        record_step_execution(duration=time.time() - t_start, status="completed")
        return {"status": "success", "output": seo_metadata}


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — PUBLISHER AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class PublisherAgent(CustomAgent):
    """
    Assembles and publishes the final article.

    Reads draft (write step) and SEO metadata (seo step) via RedisMemoryAccessor.
    Writes the final article to blob. Compresses LTM. Sends mailbox notification
    to the researcher to confirm publication.
    """
    role = "publisher"
    capabilities = ["publishing", "content_delivery"]

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="publish",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def execute_task(self, task: dict) -> dict:
        t_start = time.time()

        accessor = None
        if self._redis_store:
            accessor = RedisMemoryAccessor(self._redis_store, WORKFLOW_ID)

        # Read all previous step outputs (strip outer Redis hash + inner status wrapper)
        def _unwrap(raw):
            if isinstance(raw, dict) and "output" in raw:
                return raw["output"]
            return raw or {}

        draft_output = _unwrap(accessor.get("write")) if accessor else {}
        seo_output   = _unwrap(accessor.get("seo"))   if accessor else {}

        draft = draft_output.get("draft", "Draft not available") if isinstance(draft_output, dict) else ""
        seo   = seo_output if isinstance(seo_output, dict) else {}

        # Assemble final article with SEO front-matter
        slug = TOPIC.lower().replace(" ", "-").replace("/", "-")
        final_article = f"""---
title: "{seo.get('title_tag', TOPIC)}"
description: "{seo.get('meta_description', '')}"
keywords: {seo.get('target_keywords', [])}
seo_score: {seo.get('seo_score', 0)}
published: "{time.strftime('%Y-%m-%d')}"
workflow_id: "{WORKFLOW_ID}"
---

{draft}
"""

        # Phase 1: save final article to blob
        blob_path = f"content/published/{slug}.md"
        if self._blob_storage:
            await self._blob_storage.save(blob_path, final_article)
            self._logger.info(f"[{self.role}] Article published: {blob_path}")

        # Phase 8: save style notes to LTM for future writer runs
        if self.memory.ltm:
            style_summary = (
                f"Article on '{TOPIC}' published {time.strftime('%Y-%m-%d')}. "
                f"SEO score: {seo.get('seo_score', 'N/A')}. "
                f"Style: informative, forward-looking, developer-audience. "
                f"Word count: {draft_output.get('word_count', '?') if isinstance(draft_output, dict) else '?'}."
            )
            await self.memory.ltm.save_summary(style_summary)
            self._logger.info(f"[{self.role}] LTM style notes saved for future runs")

        # Phase 8: episodic log
        if self.memory.episodic:
            await self.memory.episodic.append({
                "event": "article_published",
                "blob_path": blob_path,
                "seo_score": seo.get("seo_score", 0),
                "ts": time.time(),
            })

        # Phase 5
        record_step_execution(duration=time.time() - t_start, status="completed")

        return {
            "status": "success",
            "output": {
                "blob_path": blob_path,
                "seo_score": seo.get("seo_score", 0),
                "word_count": draft_output.get("word_count", 0) if isinstance(draft_output, dict) else 0,
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 4: Content Production Pipeline")
    print("CustomAgent | Distributed Mode | Phases 1, 4, 5, 7, 8, 9")
    print("=" * 70)

    mesh = Mesh(
        mode="distributed",
        config={
            "redis_url": REDIS_URL,
            "bind_host": "127.0.0.1",
            "bind_port": 7955,
            "node_name": "content-pipeline-node",
        },
    )

    researcher = mesh.add(ResearchAgent)
    writer     = mesh.add(WriterAgent)
    seo        = mesh.add(SEOAgent)
    publisher  = mesh.add(PublisherAgent)

    try:
        await mesh.start()

        # ── Phase 9 verification ──────────────────────────────────────────────
        print("\n[Phase 9] Infrastructure injection:")
        for ag in [researcher, writer, seo, publisher]:
            print(f"  {ag.role:12s} | redis={'✓' if ag._redis_store else '✗'}  "
                  f"blob={'✓' if ag._blob_storage else '✗'}  "
                  f"mailbox={'✓' if ag.mailbox else '✗'}")

        # ── Workflow submission ────────────────────────────────────────────────
        print(f"\n[Workflow] Topic: '{TOPIC}'")
        print(f"[Workflow] ID   : {WORKFLOW_ID}")
        print("[Workflow] Steps: research → write → seo → publish\n")

        results = await mesh.workflow(WORKFLOW_ID, [
            {
                "id": "research",
                "agent": "researcher",
                "task": f"Research background material for: {TOPIC}",
            },
            {
                "id": "write",
                "agent": "writer",
                "task": f"Write a comprehensive blog article about: {TOPIC}",
                "depends_on": ["research"],     # Phase 7: waits for research step
            },
            {
                "id": "seo",
                "agent": "seo",
                "task": f"Optimise article for keywords: AI agents, autonomous AI, {TOPIC}",
                "depends_on": ["write"],
            },
            {
                "id": "publish",
                "agent": "publisher",
                "task": f"Publish the final optimised article for: {TOPIC}",
                "depends_on": ["seo"],
            },
        ])

        # ── Results ───────────────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("WORKFLOW RESULTS")
        print("=" * 70)

        step_names = ["research", "write", "seo", "publish"]
        for name, result in zip(step_names, results):
            status = result.get("status", "unknown")
            icon = "✓" if status == "success" else "✗"
            output = result.get("output", {})
            print(f"\n{icon} Step: {name}  (status={status})")

            if name == "research" and isinstance(output, dict):
                print(f"  Sources checked: {output.get('sources_checked', '?')}")
                print(f"  Key themes:      {len(output.get('key_themes', []))} found")

            elif name == "write" and isinstance(output, dict):
                print(f"  Word count: {output.get('word_count', '?')}")
                print(f"  Blob path:  blob_storage/content/drafts/")

            elif name == "seo" and isinstance(output, dict):
                print(f"  SEO score:      {output.get('seo_score', '?')}")
                print(f"  Read time:      ~{output.get('estimated_read_time_min', '?')} min")
                print(f"  Keyword density: {output.get('keyword_density', {})}")

            elif name == "publish" and isinstance(output, dict):
                print(f"  Published to: blob_storage/{output.get('blob_path', '?')}")
                print(f"  SEO score:    {output.get('seo_score', '?')}")
                print(f"  Word count:   {output.get('word_count', '?')}")

            elif status != "success":
                print(f"  Error: {result.get('error', 'unknown')}")

        # ── Phase 4: publisher → researcher mailbox notification ───────────────
        if publisher.mailbox and researcher.agent_id:
            publisher.mailbox.send(researcher.agent_id, {
                "event": "article_published",
                "workflow_id": WORKFLOW_ID,
                "topic": TOPIC,
            })
            print(f"\n[Phase 4] Mailbox: Publisher notified Researcher of publication")

            # Researcher reads the notification
            messages = researcher.mailbox.read(max_messages=5) if researcher.mailbox else []
            if messages:
                print(f"[Phase 4] Researcher received {len(messages)} mailbox message(s) ✓")

        # ── Redis verification ────────────────────────────────────────────────
        if mesh._redis_store:
            print(f"\n[Phase 7] Redis step outputs:")
            for sid in step_names:
                out = mesh._redis_store.get_step_output(WORKFLOW_ID, sid)
                print(f"  {WORKFLOW_ID}:{sid} → {'set ✓' if out else 'missing'}")

            # LTM key
            ltm_key = f"ltm:{WORKFLOW_ID}"
            print(f"\n[Phase 8] LTM key: redis-cli get {ltm_key}")

        # ── Summary ───────────────────────────────────────────────────────────
        successes = sum(1 for r in results if r.get("status") == "success")
        slug = TOPIC.lower().replace(" ", "-").replace("/", "-")
        print(f"\n{'=' * 70}")
        print(f"Content Pipeline complete: {successes}/{len(results)} steps")
        print(f"Published article : blob_storage/content/published/{slug}.md")
        print(f"Research notes    : blob_storage/content/research/{WORKFLOW_ID}.json")
        print(f"SEO metadata      : blob_storage/content/seo/{WORKFLOW_ID}-metadata.json")
        if mesh._redis_store:
            print(f"EpisodicLedger    : redis-cli xrange ledgers:{WORKFLOW_ID} - +")
            print(f"LTM summary       : redis-cli get ltm:{WORKFLOW_ID}")
        print(f"{'=' * 70}\n")

    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        import traceback
        traceback.print_exc()

    finally:
        await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
