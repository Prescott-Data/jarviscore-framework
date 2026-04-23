"""
jarviscore.orchestration.shift_planner
=========================================
ShiftPlanner — reads team state and produces a structured WorkflowBuilder
for the current shift, replacing the ad-hoc JSON synthesis in
execute_autonomous_backlog().

ShiftPlanner is the "brain before the brain" — it does deterministic,
rule-based triage of the team's current state and composes a typed
workflow that agents then execute via WorkflowBuilder + mesh dispatch.

Supported modes (matching shift_warden.py / sky_team_service.py):
  auto              — full assessment, adaptive to backlog
  scrum             — forced team scrum regardless of what else is pending
  content_pipeline  — content-only: intel → angle → draft → qa → distribute
  close             — monthly financial close: parse → categorise → reconcile → report
  tax               — tax filing: PAYE or VAT computation + HITL review
  compliance        — KRA obligation check + outstanding returns audit
  self_directed     — agent reads backlog and self-selects next task

Usage (inside shift_brain.py):

    from jarviscore.orchestration.shift_planner import ShiftPlanner

    planner = ShiftPlanner(team="signal", mode="content_pipeline")
    wf = planner.build(context={"date": today, "content_calendar": cal_data})
    workflow_id = await wf.register(redis_store)
    results = await wf.execute(mesh)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, Optional

from .workflow_builder import WorkflowBuilder, Workflow

logger = logging.getLogger(__name__)


class ShiftPlanner:
    """
    Produces a typed WorkflowBuilder for the current shift mode and team.

    Args:
        team: "signal" | "treasury"
        mode: shift mode string (matches sky_team_service --mode choices)
    """

    def __init__(self, team: str, mode: str = "auto") -> None:
        self.team = team
        self.mode = mode
        self._today = date.today().isoformat()

    def build(self, context: Optional[Dict[str, Any]] = None) -> Workflow:
        """
        Compose and return a Workflow for this shift.

        Args:
            context: Optional dict with shift context (date, content_calendar,
                     backlog_items, financial_period, etc.)

        Returns:
            Workflow object ready for register() and execute()
        """
        ctx = context or {}
        builder_fn = self._get_builder(self.team, self.mode)
        wf = builder_fn(ctx)
        logger.info(
            "[ShiftPlanner] Built workflow: team=%s mode=%s steps=%d",
            self.team, self.mode, len(wf.steps)
        )
        return wf

    def _get_builder(self, team: str, mode: str):
        """Route to the correct builder based on team + mode."""
        if team == "signal":
            return {
                "auto":             self._signal_auto,
                "scrum":            self._signal_scrum,
                "content_pipeline": self._signal_content_pipeline,
                "self_directed":    self._signal_self_directed,
                # Passthrough modes for signal — fallback to auto
                "close":        self._signal_auto,
                "tax":          self._signal_auto,
                "compliance":   self._signal_auto,
            }.get(mode, self._signal_auto)
        elif team == "treasury":
            return {
                "auto":             self._treasury_auto,
                "close":            self._treasury_close,
                "tax":              self._treasury_tax,
                "compliance":       self._treasury_compliance,
                "scrum":            self._treasury_scrum,
                "self_directed":    self._treasury_auto,
                "content_pipeline": self._treasury_auto,
            }.get(mode, self._treasury_auto)
        else:
            logger.warning("[ShiftPlanner] Unknown team '%s' — falling back to signal_auto", team)
            return self._signal_auto

    # ─────────────────────────────────────────────────────────────────────────
    # Signal workflows
    # ─────────────────────────────────────────────────────────────────────────

    def _signal_auto(self, ctx: Dict) -> Workflow:
        """Full signal shift: intel scan → direction → content → QA → (optional) distribute."""
        return (
            WorkflowBuilder()
            .step("read_blockers", "compass",
                  "Read knowledge/ops/blockers.md and summarise all open blockers")
            .step("read_calendar", "compass",
                  "Read knowledge/signal/content_calendar.md and identify what is due today or this week")
            .step("intel", "sentinel",
                  "Scan Twitter/X, LinkedIn, HN for AI agent news and Prescott Data mention."
                  " Check top 3 competitors for new releases. Write intel brief.")
            .step("shift_brief", "compass",
                  "Using {read_blockers.result} and {read_calendar.result} and {intel.result}:"
                  " write shift brief to knowledge/ops/shift_{date}.md."
                  " Assign specific tasks to each team member.".format(date=self._today),
                  depends_on=["read_blockers", "read_calendar", "intel"])
            .step("draft", "quill",
                  "Using the shift brief and intel from {intel.result}:"
                  " draft the highest-priority content piece due today.",
                  depends_on=["intel", "shift_brief"])
            .step("qa", "warden",
                  "QA the draft from {draft.result} for brand voice, factual accuracy, and red lines.",
                  depends_on=["draft"])
            .build(title=f"Signal auto shift — {self._today}", team="signal")
        )

    def _signal_scrum(self, ctx: Dict) -> Workflow:
        """Forced weekly scrum — read all prior output, identify gaps, write scrum doc."""
        return (
            WorkflowBuilder()
            .step("read_all_output", "compass",
                  "Read all agent output files from the past 7 days in knowledge/signal/ and knowledge/ops/"
                  " — summarise what was completed and what is outstanding")
            .step("scrum_intel", "sentinel",
                  "Read knowledge/signal/seo_opportunities.md and competitor_tracker.md"
                  " — what is the most important intelligence item from the past week?")
            .step("scrum_content", "quill",
                  "Read knowledge/signal/content_library.md — what content was published this week?"
                  " What is still in draft?")
            .step("scrum_notes", "compass",
                  "Using {read_all_output.result}, {scrum_intel.result}, {scrum_content.result}:"
                  " write weekly scrum to knowledge/ops/weekly_scrum_{date}.md."
                  " For each agent: DONE, IN_PROGRESS, BLOCKED, NEXT.".format(date=self._today),
                  depends_on=["read_all_output", "scrum_intel", "scrum_content"])
            .step("set_next_week", "compass",
                  "Using scrum notes {scrum_notes.result}: assign next week's tasks to each agent."
                  " Write task files for sentinel, quill, warden, outpost, envoy.",
                  depends_on=["scrum_notes"])
            .build(title=f"Signal weekly scrum — {self._today}", team="signal")
        )

    def _signal_content_pipeline(self, ctx: Dict) -> Workflow:
        """Deterministic content pipeline: intel → angle → draft → QA → distribute ready."""
        topic = ctx.get("topic", "Prescott Data product update")
        return (
            WorkflowBuilder()
            .step("intel", "sentinel",
                  f"Research current conversation around: {topic}."
                  " Find 3 specific angles with data points or examples.")
            .step("angle", "compass",
                  f"Using intel from {{intel.result}}: select the best angle for a LinkedIn post on {topic}."
                  " Write a 2-sentence brief for Quill.",
                  depends_on=["intel"])
            .step("draft", "quill",
                  "Write LinkedIn post using brief from {angle.result}."
                  " 150-300 words, hook → example → CTA, max 3 hashtags.",
                  depends_on=["angle"])
            .step("qa", "warden",
                  "QA {draft.result}: brand voice, factual accuracy, red lines check."
                  " Return APPROVED or NEEDS_REVISION with specific edits.",
                  depends_on=["draft"])
            .step("queue", "dispatch",
                  "If {qa.result} is APPROVED: add post to knowledge/signal/scheduled_queue.md"
                  " with target channel LinkedIn and target date today.",
                  depends_on=["qa"])
            .build(title=f"Content pipeline: {topic[:50]} — {self._today}", team="signal")
        )

    def _signal_self_directed(self, ctx: Dict) -> Workflow:
        """Agent reads backlog and self-selects the most important task."""
        return (
            WorkflowBuilder()
            .step("assess_backlog", "compass",
                  "Read knowledge/ops/blockers.md, knowledge/signal/content_calendar.md,"
                  " and all agent task files. Identify the single most important unfinished task.")
            .step("execute_priority", "compass",
                  "Based on {assess_backlog.result}: assign and execute the highest-priority task."
                  " If it's a content task: route to quill. If intelligence: route to sentinel.",
                  depends_on=["assess_backlog"])
            .build(title=f"Signal self-directed — {self._today}", team="signal")
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Treasury workflows
    # ─────────────────────────────────────────────────────────────────────────

    def _treasury_auto(self, ctx: Dict) -> Workflow:
        """Full treasury auto shift: check obligations → process pending data → report."""
        period = ctx.get("period", self._today[:7])  # YYYY-MM
        return (
            WorkflowBuilder()
            .step("obligations", "kodi",
                  "Check knowledge/treasury/tax_calendar.md for any tax obligations due this week or next."
                  " List all upcoming KRA deadlines.")
            .step("parse_new", "ingram",
                  "Check data/statements/ for any new unprocessed statement files."
                  " Parse any new files and write to data/transactions/.")
            .step("categorise", "tally",
                  "Read latest Ingram output from data/transactions/."
                  " Categorise all uncategorised transactions. Flag ambiguous items.",
                  depends_on=["parse_new"])
            .step("reconcile", "ledger",
                  "Run reconciliation for {period} using Tally output {categorise.result}."
                  " Flag any gaps > KES 100.".format(period=period),
                  depends_on=["categorise"])
            .step("runway_update", "runway",
                  "Update burn_tracker.md using {reconcile.result}."
                  " Report current runway in base/optimistic/conservative scenarios.",
                  depends_on=["reconcile"])
            .build(title=f"Treasury auto shift — {self._today}", team="treasury")
        )

    def _treasury_close(self, ctx: Dict) -> Workflow:
        """Monthly financial close: full parse → categorise → reconcile → report pipeline."""
        month = ctx.get("month", self._today[:7])
        return (
            WorkflowBuilder()
            .step("parse", "ingram",
                  f"Parse all statement files for {month} from data/statements/."
                  " Write consolidated output to data/transactions/parsed_{month}.json.".format(month=month))
            .step("categorise", "tally",
                  f"Categorise all transactions in data/transactions/parsed_{month}.json."
                  " Separate VAT-eligible items. Flag all items over KES 50,000 for review.",
                  depends_on=["parse"])
            .step("reconcile", "ledger",
                  f"Full reconciliation for {month}: match all Tally output against bank statements."
                  " Write reconciliation report to knowledge/treasury/reconciliation_{month}.md.",
                  depends_on=["categorise"])
            .step("pl_report", "folio",
                  f"Generate P&L for {month} from reconciled data {{reconcile.result}}."
                  " Write to knowledge/treasury/pl_{month}.md with prior month comparison.",
                  depends_on=["reconcile"])
            .step("runway", "runway",
                  "Update runway from {pl_report.result}. Report months remaining (3 scenarios).",
                  depends_on=["pl_report"])
            .step("investor_update", "envoy",
                  "Draft investor update for {month} using {pl_report.result} and {runway.result}."
                  " Flag for muyukani review before sending.",
                  depends_on=["pl_report", "runway"])
            .build(title=f"Monthly close — {month}", team="treasury")
        )

    def _treasury_tax(self, ctx: Dict) -> Workflow:
        """Tax filing: compute PAYE or VAT, prepare filing package, HITL for approval."""
        tax_type = ctx.get("tax_type", "PAYE")
        period = ctx.get("period", self._today[:7])
        return (
            WorkflowBuilder()
            .step("gather_data", "tally",
                  f"From categorised transactions for {period}:"
                  f" extract all {tax_type}-relevant items. Subtotal by category.")
            .step("compute", "kodi",
                  f"Compute {tax_type} for {period} using {{gather_data.result}}."
                  f" Apply correct KRA rates. Write computation to"
                  f" knowledge/treasury/{tax_type.lower()}_{period}.md.",
                  depends_on=["gather_data"])
            .step("review_package", "folio",
                  f"Package {tax_type} computation {{compute.result}} for founder review."
                  f" Summarise: amount due, due date, computation basis.",
                  depends_on=["compute"])
            .build(title=f"{tax_type} computation — {period}", team="treasury")
        )

    def _treasury_compliance(self, ctx: Dict) -> Workflow:
        """KRA obligation audit: check all outstanding returns and compliance status."""
        return (
            WorkflowBuilder()
            .step("obligations_audit", "kodi",
                  "Read knowledge/treasury/tax_calendar.md."
                  " List all KRA obligations for the past 90 days."
                  " Flag any that were not filed or paid on time.")
            .step("outstanding_returns", "kodi",
                  "Check KRA iTax (via browser) for any outstanding returns or penalties."
                  " Log findings in knowledge/treasury/compliance_audit_{date}.md.".format(date=self._today),
                  depends_on=["obligations_audit"])
            .step("remediation_plan", "folio",
                  "Using {outstanding_returns.result}: draft remediation plan."
                  " For each outstanding item: amount, deadline, action required.",
                  depends_on=["outstanding_returns"])
            .build(title=f"KRA compliance audit — {self._today}", team="treasury")
        )

    def _treasury_scrum(self, ctx: Dict) -> Workflow:
        """Treasury weekly scrum — review prior week, set next week priorities."""
        return (
            WorkflowBuilder()
            .step("prior_week", "folio",
                  "Read all treasury output from the past 7 days."
                  " What was completed? What is outstanding?")
            .step("obligations_check", "kodi",
                  "What KRA obligations are due in the next 14 days?")
            .step("scrum_notes", "folio",
                  "Using {prior_week.result} and {obligations_check.result}:"
                  " write treasury weekly scrum to knowledge/treasury/scrum_{date}.md.".format(date=self._today),
                  depends_on=["prior_week", "obligations_check"])
            .build(title=f"Treasury scrum — {self._today}", team="treasury")
        )
