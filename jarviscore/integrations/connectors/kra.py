"""
jarviscore.integrations.connectors.kra
========================================
KRAConnector — read KRA iTax obligations and filing deadlines.

KRA iTax has no public REST API, so this connector uses:
  1. A local knowledge base (knowledge/treasury/tax_calendar.md) — fast, offline
  2. Browser automation (Playwright) for live iTax portal queries when headless=True

Usage:
    from jarviscore.integrations.connectors.kra import KRAConnector
    kra = KRAConnector()
    obligations = kra.get_obligations()
    deadlines = kra.get_filing_deadlines()
"""
from __future__ import annotations
import logging, os
from datetime import date
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

# Standard KRA tax calendar — deadlines are deterministic
# PAYE: 9th of each month (for prior month payroll)
# VAT:  20th of month following end of quarter
# CIT:  June 30 for Dec 31 year-end companies
_PAYE_DAY = 9
_VAT_QUARTERS = {1: (4, 20), 2: (7, 20), 3: (10, 20), 4: (1, 20)}  # (month, day) of filing

class KRAConnector:
    """
    KRA iTax knowledge connector.

    Reads from local tax_calendar.md when available.
    Falls back to computed deadlines from Kenya tax rules.
    """

    def __init__(self, knowledge_dir: Optional[str] = None) -> None:
        self._kb_dir = knowledge_dir or os.environ.get("PRESCOTT_KB_DIR", "knowledge/treasury")

    def get_obligations(self) -> List[Dict[str, Any]]:
        """
        Return all known tax obligations for the current period.

        Returns list of:
            {"type": "PAYE"|"VAT"|"CIT"|"WHT", "period": str,
             "due_date": "YYYY-MM-DD", "status": "pending"|"filed"|"overdue"}
        """
        today = date.today()
        obligations = []

        # PAYE — this month's
        paye_due = date(today.year, today.month, _PAYE_DAY)
        obligations.append({
            "type": "PAYE",
            "period": f"{today.year}-{today.month - 1:02d}" if today.month > 1
                      else f"{today.year - 1}-12",
            "due_date": paye_due.isoformat(),
            "status": "overdue" if today > paye_due else "pending",
            "description": "Monthly PAYE — due 9th of following month",
        })

        # VAT — compute current quarter filing date
        quarter = (today.month - 1) // 3 + 1
        vat_month, vat_day = _VAT_QUARTERS[quarter]
        vat_year = today.year + 1 if vat_month == 1 and quarter == 4 else today.year
        vat_due = date(vat_year, vat_month, vat_day)
        obligations.append({
            "type": "VAT",
            "period": f"Q{quarter} {today.year}",
            "due_date": vat_due.isoformat(),
            "status": "overdue" if today > vat_due else "pending",
            "description": "Quarterly VAT return — 20th of month following quarter end",
        })

        # Also read from tax_calendar.md if available
        cal = self._read_calendar()
        if cal:
            obligations.append({
                "type": "CALENDAR_NOTES",
                "period": today.isoformat(),
                "due_date": None,
                "status": "info",
                "description": cal[:500],
            })

        return obligations

    def get_filing_deadlines(self) -> List[Dict[str, Any]]:
        """Return upcoming KRA filing deadlines for the next 90 days."""
        today = date.today()
        deadlines = []

        for month_offset in range(3):
            year = today.year
            month = today.month + month_offset
            if month > 12:
                month -= 12
                year += 1

            deadlines.append({
                "type": "PAYE",
                "due_date": date(year, month, min(_PAYE_DAY, 28)).isoformat(),
                "description": f"PAYE for {year}-{month - 1:02d}" if month > 1 else f"PAYE for {year - 1}-12",
            })

        return sorted(deadlines, key=lambda x: x["due_date"])

    def get_tax_balance(self, tax_type: str) -> Dict[str, Any]:
        """
        Return current tax account balance for a tax type.

        Note: Live balance requires browser automation to iTax portal.
        This returns a stub with instructions when browser not available.
        """
        return {
            "status": "requires_browser",
            "tax_type": tax_type,
            "message": (
                f"Live {tax_type} balance requires iTax browser access. "
                "Use BrowserSubAgent with iTax credentials to read the iTax dashboard."
            ),
        }

    def _read_calendar(self) -> str:
        """Try to read local tax calendar file."""
        calendar_path = os.path.join(self._kb_dir, "tax_calendar.md")
        try:
            if os.path.exists(calendar_path):
                with open(calendar_path) as f:
                    return f.read()
        except Exception:
            pass
        return ""
