"""
jarviscore.integrations.connectors.google_docs
================================================
GoogleDocsConnector — create, read, and update Google Docs.

Uses google-api-python-client with service account or OAuth credentials
from GOOGLE_SERVICE_ACCOUNT_JSON env var.

Usage:
    from jarviscore.integrations.connectors.google_docs import GoogleDocsConnector
    docs = GoogleDocsConnector()
    doc = docs.create_doc(title="Investor Update May 2025", content=report_md)
"""
from __future__ import annotations
import logging, os
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class GoogleDocsConnector:
    """Google Docs connector via Google Drive API v3 + Docs API v1."""

    _SCOPES = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def __init__(self, credentials_json: Optional[str] = None) -> None:
        self._creds_json = credentials_json or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

    def _creds(self):
        try:
            import json
            from google.oauth2 import service_account
        except ImportError:
            raise ImportError("google-auth not installed. Install: pip install google-auth google-api-python-client")
        info = json.loads(self._creds_json)
        return service_account.Credentials.from_service_account_info(info, scopes=self._SCOPES)

    def _drive(self):
        from googleapiclient.discovery import build
        return build("drive", "v3", credentials=self._creds(), cache_discovery=False)

    def _docs_api(self):
        from googleapiclient.discovery import build
        return build("docs", "v1", credentials=self._creds(), cache_discovery=False)

    def create_doc(self, title: str, content: str) -> Dict[str, Any]:
        """Create a new Google Doc with plain text content. Returns doc_id and url."""
        try:
            drive = self._drive()
            metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
            doc = drive.files().create(body=metadata).execute()
            doc_id = doc["id"]
            # Insert content via Docs API
            self._insert_text(doc_id, content)
            url = f"https://docs.google.com/document/d/{doc_id}/edit"
            logger.info("[GDocs] Created doc '%s': %s", title, url)
            return {"status": "success", "doc_id": doc_id, "url": url}
        except Exception as exc:
            logger.error("[GDocs] create_doc failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def read_doc(self, doc_id: str) -> str:
        """Read plain text content from a Google Doc."""
        try:
            docs = self._docs_api()
            result = docs.documents().get(documentId=doc_id).execute()
            text_parts = []
            for elem in result.get("body", {}).get("content", []):
                for run in elem.get("paragraph", {}).get("elements", []):
                    t = run.get("textRun", {}).get("content", "")
                    if t:
                        text_parts.append(t)
            return "".join(text_parts)
        except Exception as exc:
            logger.error("[GDocs] read_doc failed: %s", exc)
            return ""

    def update_doc(self, doc_id: str, content: str) -> Dict[str, Any]:
        """Replace the content of an existing Google Doc."""
        try:
            docs = self._docs_api()
            # Get current end index to delete all content first
            result = docs.documents().get(documentId=doc_id).execute()
            end_index = result["body"]["content"][-1].get("endIndex", 1) - 1
            requests = []
            if end_index > 1:
                requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index}}})
            requests.append({"insertText": {"location": {"index": 1}, "text": content}})
            docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
            return {"status": "success", "doc_id": doc_id}
        except Exception as exc:
            logger.error("[GDocs] update_doc failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _insert_text(self, doc_id: str, text: str) -> None:
        docs = self._docs_api()
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
        ).execute()
