"""
jarviscore.integrations.connectors.quickbooks
===============================================
QuickBooksConnector — P&L, invoices, expenses from QuickBooks Online.

Uses intuit-oauth and python-quickbooks. Credentials from env:
  QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REFRESH_TOKEN, QBO_REALM_ID

Usage:
    from jarviscore.integrations.connectors.quickbooks import QuickBooksConnector
    qbo = QuickBooksConnector()
    pl = qbo.get_pl(start_date="2025-01-01", end_date="2025-01-31")
"""
from __future__ import annotations
import logging, os
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class QuickBooksConnector:
    """QuickBooks Online connector via python-quickbooks."""

    def __init__(self) -> None:
        self._client_id = os.environ.get("QBO_CLIENT_ID")
        self._client_secret = os.environ.get("QBO_CLIENT_SECRET")
        self._refresh_token = os.environ.get("QBO_REFRESH_TOKEN")
        self._realm_id = os.environ.get("QBO_REALM_ID")
        self._sandbox = os.environ.get("QBO_SANDBOX", "false").lower() == "true"

    def _client(self):
        try:
            from intuitlib.client import AuthClient
            from quickbooks import QuickBooks
        except ImportError:
            raise ImportError("Install: pip install python-quickbooks intuitlib")
        auth = AuthClient(
            client_id=self._client_id,
            client_secret=self._client_secret,
            environment="sandbox" if self._sandbox else "production",
            redirect_uri="https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl",
        )
        auth.refresh_token = self._refresh_token
        return QuickBooks(auth_client=auth, refresh_token=self._refresh_token,
                          company_id=self._realm_id, minorversion=65)

    def get_pl(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Fetch Profit & Loss report.

        Args:
            start_date: ISO date string "YYYY-MM-DD"
            end_date:   ISO date string "YYYY-MM-DD"

        Returns:
            {"status": "success", "report": {...raw QBO report dict...}}
        """
        try:
            from quickbooks.reports import Report
            client = self._client()
            report = Report.get(
                "ProfitAndLoss",
                qb=client,
                params={"start_date": start_date, "end_date": end_date},
            )
            return {"status": "success", "report": report.to_dict()}
        except Exception as exc:
            logger.error("[QBO] get_pl failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def list_invoices(self, status: str = "open") -> List[Dict[str, Any]]:
        """List invoices. status: 'open' | 'paid' | 'all'."""
        try:
            from quickbooks.objects import Invoice
            client = self._client()
            invoices = Invoice.all(qb=client)
            result = []
            for inv in invoices:
                if status == "open" and inv.Balance == 0:
                    continue
                if status == "paid" and inv.Balance > 0:
                    continue
                result.append({
                    "id": inv.Id,
                    "doc_number": inv.DocNumber,
                    "customer": inv.CustomerRef.name if inv.CustomerRef else None,
                    "total": inv.TotalAmt,
                    "balance": inv.Balance,
                    "due_date": getattr(inv, "DueDate", None),
                })
            return result
        except Exception as exc:
            logger.error("[QBO] list_invoices failed: %s", exc)
            return []

    def list_expenses(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
        """List expense transactions (Purchases) in a date range."""
        try:
            from quickbooks.objects import Purchase
            client = self._client()
            purchases = Purchase.all(qb=client)
            result = []
            for p in purchases:
                txn_date = getattr(p, "TxnDate", "")
                if start_date and txn_date < start_date:
                    continue
                if end_date and txn_date > end_date:
                    continue
                result.append({
                    "id": p.Id,
                    "date": txn_date,
                    "amount": p.TotalAmt,
                    "account": p.AccountRef.name if p.AccountRef else None,
                    "memo": getattr(p, "PrivateNote", ""),
                })
            return result
        except Exception as exc:
            logger.error("[QBO] list_expenses failed: %s", exc)
            return []
