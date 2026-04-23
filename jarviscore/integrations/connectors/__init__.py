"""
JarvisCore operational connectors — real-world integrations for agents.

All connectors use Nexus credentials via connection_id — never raw secrets.
They are callable from CoderSubAgent sandbox code:

    from jarviscore.integrations.connectors.slack import SlackConnector
    slack = SlackConnector(connection_id=ctx["_nexus_connection_id"])
    slack.post_message(channel="#founders", text=approved_post)

Available connectors:
  - SlackConnector     — Slack workspace messaging
  - GitHubConnector    — GitHub repo operations (branches, PRs, issues, files)
  - GoogleDocsConnector — Google Docs read/write
  - EmailConnector      — SendGrid email dispatch
  - QuickBooksConnector — QuickBooks Online financial data
  - KRAConnector        — KRA iTax obligation and deadline queries
"""
from .slack import SlackConnector
from .github import GitHubConnector
from .google_docs import GoogleDocsConnector
from .email import EmailConnector
from .quickbooks import QuickBooksConnector
from .kra import KRAConnector

__all__ = [
    "SlackConnector",
    "GitHubConnector",
    "GoogleDocsConnector",
    "EmailConnector",
    "QuickBooksConnector",
    "KRAConnector",
]
