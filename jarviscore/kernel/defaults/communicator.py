"""
6F: CommunicatorSubAgent — Message drafting and peer communication specialist.

The communicator drafts messages, formats reports, and handles
inter-agent communication via the mailbox/peer system.

Design decisions (from IA/CA analysis):
- Adopted: Structured output formatting (both — clear report templates)
- Adopted: Audience-aware tone adjustment (IA — technical vs non-technical)
- Avoided: Over-complex message routing (keep it simple, kernel handles dispatch)
"""

import logging
from typing import Any, Dict, List, Optional

from jarviscore.kernel.subagent import BaseSubAgent

logger = logging.getLogger(__name__)


class CommunicatorSubAgent(BaseSubAgent):
    """
    Communication subagent for the kernel.

    Tools:
    - draft_message: Draft a message for a target audience (thinking)
    - format_report: Format structured data into a report (thinking)
    - send_to_peer: Send a message to another agent via mailbox (action)

    The communicator specializes in transforming raw data/findings into
    human-readable or agent-readable messages with appropriate tone
    and formatting.
    """

    def __init__(
        self,
        agent_id: str,
        llm_client,
        mailbox=None,
        redis_store=None,
        blob_storage=None,
    ):
        self.mailbox = mailbox
        self._drafts: List[Dict[str, Any]] = []
        super().__init__(
            agent_id=agent_id,
            role="communicator",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return (
            "You are a communication specialist. You draft clear, well-structured "
            "messages and reports tailored to the target audience.\n\n"
            "Workflow:\n"
            "1. Analyze the task and context to understand the audience\n"
            "2. Use draft_message to compose your message\n"
            "3. Use format_report if structured data needs formatting\n"
            "4. Use send_to_peer if the message needs to be delivered to another agent\n\n"
            "Rules:\n"
            "- Adjust tone for the audience (technical vs non-technical)\n"
            "- Keep messages concise and actionable\n"
            "- Include key data points, not raw dumps\n"
            "- Structure reports with clear sections"
        )

    def setup_tools(self) -> None:
        self.register_tool(
            "draft_message",
            self._tool_draft_message,
            "Draft a message. Params: {\"content\": \"<text>\", \"audience\": \"technical|non-technical\", \"format\": \"plain|markdown|json\"}",
            phase="thinking",
        )
        self.register_tool(
            "format_report",
            self._tool_format_report,
            "Format data into a report. Params: {\"title\": \"<title>\", \"sections\": [{\"heading\": \"...\", \"body\": \"...\"}], \"format\": \"markdown|plain\"}",
            phase="thinking",
        )
        self.register_tool(
            "send_to_peer",
            self._tool_send_to_peer,
            "Send message to a peer agent. Params: {\"peer_role\": \"<role>\", \"message\": \"<text>\", \"priority\": \"normal|high\"}",
            phase="action",
        )

    def _tool_draft_message(
        self,
        content: str,
        audience: str = "technical",
        format: str = "plain",
    ) -> Dict[str, Any]:
        """Draft a message for a target audience."""
        draft = {
            "version": len(self._drafts) + 1,
            "content": content,
            "audience": audience,
            "format": format,
        }
        self._drafts.append(draft)
        return {"version": draft["version"], "length": len(content), "status": "drafted"}

    def _tool_format_report(
        self,
        title: str,
        sections: Optional[List[Dict[str, str]]] = None,
        format: str = "markdown",
    ) -> Dict[str, Any]:
        """Format structured data into a report."""
        sections = sections or []

        if format == "markdown":
            parts = [f"# {title}", ""]
            for section in sections:
                heading = section.get("heading", "Section")
                body = section.get("body", "")
                parts.append(f"## {heading}")
                parts.append(body)
                parts.append("")
            report = "\n".join(parts)
        else:
            parts = [title, "=" * len(title), ""]
            for section in sections:
                heading = section.get("heading", "Section")
                body = section.get("body", "")
                parts.append(heading)
                parts.append("-" * len(heading))
                parts.append(body)
                parts.append("")
            report = "\n".join(parts)

        draft = {
            "version": len(self._drafts) + 1,
            "content": report,
            "audience": "technical",
            "format": format,
        }
        self._drafts.append(draft)
        return {"version": draft["version"], "report": report, "sections_count": len(sections)}

    async def _tool_send_to_peer(
        self,
        peer_role: str,
        message: str,
        priority: str = "normal",
    ) -> Dict[str, Any]:
        """Send a message to a peer agent via the mailbox."""
        if not self.mailbox:
            return {"status": "error", "error": "No mailbox configured"}

        try:
            result = self.mailbox.send(
                to_role=peer_role,
                message=message,
                priority=priority,
            )
            if hasattr(result, "__await__"):
                result = await result
            return {"status": "sent", "peer": peer_role, "priority": priority}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @property
    def drafts(self) -> List[Dict[str, Any]]:
        """All message drafts from this run."""
        return list(self._drafts)

    async def run(self, task, context=None, max_turns=4, model=None):
        """Run with fresh drafts list."""
        self._drafts = []
        return await super().run(task, context, max_turns, model)
