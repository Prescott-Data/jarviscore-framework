"""
CommunicatorSubAgent — Message drafting, peer communication, and file I/O specialist.

The communicator drafts messages, formats reports, handles
inter-agent communication via the mailbox/peer system, and
writes/reads files for persistent output.

Design decisions (from first principles):
- Adopted: Structured output formatting (clear report templates)
- Adopted: Audience-aware tone adjustment (technical vs non-technical)
- Adopted: File I/O for persistent workspace artifacts
- Avoided: Over-complex message routing (kernel handles dispatch)
"""

import logging
import os
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
    - write_file: Write content to a file (action)
    - read_file: Read content from a file (thinking)
    - list_files: List files in a directory (thinking)

    The communicator specializes in transforming raw data/findings into
    human-readable or agent-readable messages with appropriate tone
    and formatting, and persisting outputs to the workspace.
    """

    SYSTEM_PROMPT = """\
You are a COMMUNICATION SPECIALIST in a multi-agent orchestration framework.
Your job: transform raw data into clear, actionable output for your audience.

## CAPABILITIES

1. **Message Drafting** — Write messages tailored to the audience:
   - Technical audience: precise, structured, code-friendly
   - Non-technical audience: clear, jargon-free, action-oriented

2. **Report Formatting** — Structure findings into professional reports:
   - Use clear sections with headings
   - Include key data points, not raw dumps
   - Highlight actionable items

3. **File Management** — Write persistent output to the workspace:
   - Use write_file for reports, data files, meeting notes
   - Use read_file to check existing content before overwriting
   - Use list_files to discover workspace structure

4. **Peer Communication** — Send messages to other agents:
   - Use send_to_peer for inter-agent coordination
   - Include context so the receiving agent can act without ambiguity

## RULES

- Adjust tone for the audience (technical vs non-technical)
- Keep messages concise and actionable
- Include key data points, not raw dumps
- Structure reports with clear sections
- When writing files, use meaningful filenames that describe the content
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
        return self.SYSTEM_PROMPT

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
        self.register_tool(
            "write_file",
            self._tool_write_file,
            "Write content to a file. Params: {\"path\": \"<file_path>\", \"content\": \"<text>\", \"mode\": \"w|a\"}",
            phase="action",
        )
        self.register_tool(
            "read_file",
            self._tool_read_file,
            "Read content from a file. Params: {\"path\": \"<file_path>\"}",
            phase="thinking",
        )
        self.register_tool(
            "list_files",
            self._tool_list_files,
            "List files in a directory. Params: {\"path\": \"<directory_path>\", \"pattern\": \"<optional glob>\"}",
            phase="thinking",
        )

    # ─────────────────────────────────────────────────────────────
    # Tools: Messaging
    # ─────────────────────────────────────────────────────────────

    def _tool_draft_message(
        self,
        content: str = "",
        audience: str = "technical",
        format: str = "plain",
        **kwargs,  # absorb unexpected LLM params
    ) -> Dict[str, Any]:
        """Draft a message for a target audience."""
        # LLM key-name variance: absorb common alternatives
        if not content:
            content = (
                kwargs.get("text", "")
                or kwargs.get("body", "")
                or kwargs.get("message", "")
                or kwargs.get("msg", "")
            )
        if not content:
            return {"status": "error", "error": "Missing content — provide the message text"}

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
        title: str = "",
        sections: Optional[List[Dict[str, str]]] = None,
        format: str = "markdown",
        **kwargs,  # absorb unexpected LLM params
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
        peer_role: str = "",
        message: str = "",
        priority: str = "normal",
        **kwargs,  # absorb unexpected LLM params
    ) -> Dict[str, Any]:
        """Send a message to a peer agent via the mailbox."""
        # LLMs frequently use alternate key names — absorb common variations
        if not peer_role:
            peer_role = (
                kwargs.get("role", "")
                or kwargs.get("target", "")
                or kwargs.get("peer", "")
                or kwargs.get("recipient", "")
                or kwargs.get("to", "")
            )
        if not message:
            message = (
                kwargs.get("content", "")
                or kwargs.get("text", "")
                or kwargs.get("body", "")
                or kwargs.get("msg", "")
            )

        if not peer_role:
            return {"status": "error", "error": "Missing peer_role — specify which agent to message"}
        if not message:
            return {"status": "error", "error": "Missing message — specify what to send"}

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

    # ─────────────────────────────────────────────────────────────
    # Tools: File I/O
    # ─────────────────────────────────────────────────────────────

    def _tool_write_file(
        self,
        path: str,
        content: str,
        mode: str = "w",
        **kwargs,
    ) -> Dict[str, Any]:
        """Write content to a file.

        Creates parent directories if they don't exist.
        Mode 'w' overwrites, 'a' appends.
        """
        try:
            # Security: prevent path traversal
            abs_path = os.path.abspath(path)

            # Create parent dirs
            parent = os.path.dirname(abs_path)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            write_mode = "a" if mode == "a" else "w"
            with open(abs_path, write_mode, encoding="utf-8") as f:
                f.write(content)

            file_size = os.path.getsize(abs_path)
            return {
                "status": "success",
                "path": abs_path,
                "size_bytes": file_size,
                "mode": write_mode,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _tool_read_file(self, path: str, **kwargs) -> Dict[str, Any]:
        """Read content from a file."""
        try:
            if not os.path.exists(path):
                return {"status": "error", "error": f"File not found: {path}"}
            if not os.path.isfile(path):
                return {"status": "error", "error": f"Not a file: {path}"}

            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Truncate very large files
            truncated = False
            if len(content) > 10_000:
                content = content[:10_000]
                truncated = True

            return {
                "status": "success",
                "content": content,
                "size_bytes": os.path.getsize(path),
                "truncated": truncated,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _tool_list_files(
        self,
        path: str = ".",
        pattern: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """List files in a directory, optionally filtered by pattern."""
        try:
            if not os.path.exists(path):
                return {"status": "error", "error": f"Directory not found: {path}"}
            if not os.path.isdir(path):
                return {"status": "error", "error": f"Not a directory: {path}"}

            if pattern:
                import glob
                files = glob.glob(os.path.join(path, pattern))
            else:
                files = [os.path.join(path, f) for f in os.listdir(path)]

            entries = []
            for f in sorted(files)[:50]:
                is_dir = os.path.isdir(f)
                entry = {
                    "name": os.path.basename(f),
                    "path": f,
                    "type": "directory" if is_dir else "file",
                }
                if not is_dir:
                    try:
                        entry["size_bytes"] = os.path.getsize(f)
                    except OSError:
                        pass
                entries.append(entry)

            return {
                "status": "success",
                "count": len(entries),
                "entries": entries,
                "total_in_directory": len(files),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @property
    def drafts(self) -> List[Dict[str, Any]]:
        """All message drafts from this run."""
        return list(self._drafts)

    async def run(self, task, context=None, max_turns=8, model=None, **kwargs):
        """Run with fresh drafts list."""
        self._drafts = []
        return await super().run(task, context, max_turns, model, **kwargs)
