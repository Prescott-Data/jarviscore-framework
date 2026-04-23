"""
jarviscore.integrations.seed_registry
========================================
Bulk-registers all 18 connected-app atom functions into the JarvisCore
FunctionRegistry so CoderSubAgent can JIT-compile {System}Capabilities
bundles for any of the Sky platform's provider integrations.

Run once on startup, or call seed_registry() programmatically:

    from jarviscore.integrations.seed_registry import seed_registry
    from jarviscore.execution.code_registry import FunctionRegistry

    registry = FunctionRegistry()
    report = seed_registry(registry)
    print(report)

Sources:
  - 7 providers imported from collabra-function-registry (verified stage)
  - 11 providers written as new atoms (candidate stage, promote after first use)
"""
from __future__ import annotations

import ast
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Location of all atom files
_ATOMS_DIR = Path(__file__).parent / "atoms"

# ─────────────────────────────────────────────────────────────────────────────
# Provider metadata — maps system_name → {category, capabilities, status, auth_type}
# The atom .py files are under atoms/{system_name}/{function_name}.py
# ─────────────────────────────────────────────────────────────────────────────

PROVIDER_META: Dict[str, Dict[str, Any]] = {
    # ── FROM COLLABRA (verified — production-tested) ──────────────────────────
    "slack": {
        "category": "communication",
        "auth_type": "oauth2",
        "status": "verified",
        "capabilities": ["messaging", "channels", "users", "reactions"],
    },
    "github": {
        "category": "development",
        "auth_type": "oauth2",
        "status": "verified",
        "capabilities": ["issues", "pull_requests", "repositories", "files", "comments"],
    },
    "linear": {
        "category": "development",
        "auth_type": "oauth2",
        "status": "verified",
        "capabilities": ["issues", "teams", "projects", "search"],
    },
    "jira": {
        "category": "development",
        "auth_type": "basic_auth",
        "status": "verified",
        "capabilities": ["issues", "projects", "tickets"],
    },
    "notion": {
        "category": "productivity",
        "auth_type": "oauth2",
        "status": "verified",
        "capabilities": ["pages", "blocks", "databases", "search"],
    },
    "google_drive": {
        "category": "productivity",
        "auth_type": "oauth2",
        "status": "verified",
        "capabilities": ["files", "folders", "upload", "download", "sharing"],
    },
    "airtable": {
        "category": "productivity",
        "auth_type": "api_key",
        "status": "verified",
        "capabilities": ["records", "tables", "bases", "search"],
    },

    # ── NEW ATOMS (candidate — will promote to verified after first successful run) ─
    "gmail": {
        "category": "communication",
        "auth_type": "oauth2",
        "status": "candidate",
        "capabilities": ["email_send", "email_read", "drafts"],
    },
    "sendgrid": {
        "category": "communication",
        "auth_type": "api_key",
        "status": "candidate",
        "capabilities": ["email_send", "stats"],
    },
    "brevo": {
        "category": "communication",
        "auth_type": "api_key",
        "status": "candidate",
        "capabilities": ["email_send", "contacts"],
    },
    "mailchimp": {
        "category": "communication",
        "auth_type": "api_key",
        "status": "candidate",
        "capabilities": ["subscribers", "campaigns", "lists"],
    },
    "google_sheets": {
        "category": "productivity",
        "auth_type": "oauth2",
        "status": "candidate",
        "capabilities": ["read", "write", "append"],
    },
    "google_calendar": {
        "category": "productivity",
        "auth_type": "oauth2",
        "status": "candidate",
        "capabilities": ["events", "create_event", "delete_event"],
    },
    "hubspot": {
        "category": "crm",
        "auth_type": "oauth2",
        "status": "candidate",
        "capabilities": ["contacts", "deals", "companies", "crm"],
    },
    "salesforce": {
        "category": "crm",
        "auth_type": "oauth2",
        "status": "candidate",
        "capabilities": ["contacts", "leads", "opportunities", "soql"],
    },
    "apollo": {
        "category": "crm",
        "auth_type": "api_key",
        "status": "candidate",
        "capabilities": ["people_search", "companies", "leads", "prospecting"],
    },
    "stripe": {
        "category": "finance",
        "auth_type": "api_key",
        "status": "candidate",
        "capabilities": ["invoices", "charges", "customers", "balance"],
    },
    "quickbooks": {
        "category": "finance",
        "auth_type": "oauth2",
        "status": "candidate",
        "capabilities": ["profit_and_loss", "invoices", "expenses", "balance_sheet"],
    },
    "serper": {
        "category": "search",
        "auth_type": "api_key",
        "status": "candidate",
        "capabilities": ["web_search", "news_search"],
    },
}


def seed_registry(
    registry,
    systems: Optional[List[str]] = None,
    overwrite_verified: bool = False,
) -> Dict[str, Any]:
    """
    Bulk-register all atom functions into the FunctionRegistry.

    Args:
        registry:           FunctionRegistry instance
        systems:            Optional list of system names to seed (default: all 18)
        overwrite_verified: If False (default), skip atoms already at verified/golden stage

    Returns:
        Report dict with registered, skipped, failed counts and details
    """
    target_systems = systems or list(PROVIDER_META.keys())
    report = {
        "registered": [],
        "skipped": [],
        "failed": [],
        "total_atoms": 0,
    }

    for system in target_systems:
        meta = PROVIDER_META.get(system)
        if not meta:
            logger.warning("[Seed] Unknown system: %s — skipping", system)
            report["skipped"].append({"system": system, "reason": "not in PROVIDER_META"})
            continue

        atom_dir = _ATOMS_DIR / system
        if not atom_dir.exists():
            logger.warning("[Seed] No atom directory for system=%s at %s", system, atom_dir)
            report["skipped"].append({"system": system, "reason": "no atom directory"})
            continue

        atom_files = sorted(atom_dir.glob("*.py"))
        if not atom_files:
            logger.warning("[Seed] No .py atoms found for system=%s", system)
            report["skipped"].append({"system": system, "reason": "no atom .py files"})
            continue

        for atom_path in atom_files:
            function_name = atom_path.stem  # filename without .py
            report["total_atoms"] += 1

            # Skip if already at verified/golden and overwrite not requested
            if not overwrite_verified and registry.has_function(function_name):
                existing = registry.get_function_metadata(function_name)
                if existing and existing.get("registry_stage") in ("verified", "golden"):
                    logger.debug("[Seed] Skipping %s (already %s)", function_name, existing["registry_stage"])
                    report["skipped"].append({
                        "function": function_name,
                        "system": system,
                        "reason": f"already {existing['registry_stage']}",
                    })
                    continue

            # Read and validate syntax
            source = atom_path.read_text(encoding="utf-8")
            try:
                ast.parse(source)
            except SyntaxError as e:
                logger.error("[Seed] Syntax error in %s: %s", atom_path, e)
                report["failed"].append({"function": function_name, "system": system, "error": str(e)})
                continue

            # Build description from function signature
            description = _extract_description(function_name, source)

            # Determine capabilities for this specific function
            func_caps = _infer_capabilities(function_name, meta["capabilities"])

            atom_meta = {
                "system": system,
                "capabilities": func_caps,
                "description": description,
                "type": "api",
                "tags": [system, meta["category"]],
                "strategy": "sandbox",
                "source": "collabra_import" if meta["status"] == "verified" else "prescott_authored",
            }

            try:
                success = registry.register_function(
                    function_name=function_name,
                    function=source,
                    metadata=atom_meta,
                )
                if success:
                    # Collabra atoms start as verified, new ones as candidate
                    if meta["status"] == "verified":
                        registry.update_function_metadata(function_name, {
                            "registry_stage": "verified",
                            "success_count": 1,
                        })
                    report["registered"].append({
                        "function": function_name,
                        "system": system,
                        "stage": meta["status"],
                    })
                    logger.info("[Seed] Registered %s (%s/%s)", function_name, system, meta["status"])
                else:
                    report["failed"].append({"function": function_name, "system": system, "error": "register_function returned False"})
            except Exception as exc:
                logger.error("[Seed] Failed to register %s: %s", function_name, exc)
                report["failed"].append({"function": function_name, "system": system, "error": str(exc)})

    logger.info(
        "[Seed] Complete: %d registered, %d skipped, %d failed (of %d atoms)",
        len(report["registered"]), len(report["skipped"]),
        len(report["failed"]), report["total_atoms"],
    )
    return report


def _extract_description(function_name: str, source: str) -> str:
    """Extract or synthesise a description from the function source."""
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    return node.body[0].value.value[:200]
    except Exception:
        pass
    # Synthesise from name: "slack_send_message" → "Slack: send message"
    parts = function_name.split("_")
    if len(parts) >= 2:
        system = parts[0].title()
        action = " ".join(parts[1:])
        return f"{system}: {action}"
    return function_name


def _infer_capabilities(function_name: str, system_caps: List[str]) -> List[str]:
    """Infer which capabilities apply to this specific function based on name."""
    name_lower = function_name.lower()
    matched = []
    for cap in system_caps:
        if cap.replace("_", "") in name_lower.replace("_", ""):
            matched.append(cap)
    return matched if matched else system_caps[:2]


def print_seed_report(report: Dict[str, Any]) -> None:
    """Pretty-print a seed report to stdout."""
    print(f"\n{'='*60}")
    print(f"  ATOM SEED REPORT")
    print(f"{'='*60}")
    print(f"  Total atoms processed : {report['total_atoms']}")
    print(f"  Registered            : {len(report['registered'])}")
    print(f"  Skipped               : {len(report['skipped'])}")
    print(f"  Failed                : {len(report['failed'])}")
    print(f"{'='*60}")

    if report["registered"]:
        by_system: Dict[str, List[str]] = {}
        for r in report["registered"]:
            by_system.setdefault(r["system"], []).append(r["function"])
        print("\n  Registered by system:")
        for sys, fns in sorted(by_system.items()):
            stage = next((r["stage"] for r in report["registered"] if r["system"] == sys), "?")
            print(f"    {sys:20s} ({stage:10s}) → {len(fns)} atoms")

    if report["failed"]:
        print("\n  ⚠️  Failed:")
        for f in report["failed"]:
            print(f"    {f['function']} — {f['error']}")
    print()


if __name__ == "__main__":
    import sys
    # Allow running directly: python -m jarviscore.integrations.seed_registry
    logging.basicConfig(level=logging.INFO)
    from jarviscore.execution.code_registry import FunctionRegistry
    reg = FunctionRegistry()
    result = seed_registry(reg)
    print_seed_report(result)
    sys.exit(1 if result["failed"] else 0)
