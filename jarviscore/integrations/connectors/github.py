"""
jarviscore.integrations.connectors.github
===========================================
GitHubConnector — branch, PR, issue, and file operations via PyGithub.

Usage (in CoderSubAgent sandbox):
    from jarviscore.integrations.connectors.github import GitHubConnector
    gh = GitHubConnector(token=ctx.get("_github_token"))
    pr = gh.create_pr(repo="Prescott-Data/jarviscore-framework",
                      title="feat: add Slack connector",
                      body="Implements SlackConnector for agent use.",
                      head="feat/slack-connector")
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GitHubConnector:
    """GitHub repository connector using PyGithub."""

    def __init__(self, token: Optional[str] = None) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN")

    def _github(self):
        try:
            from github import Github
        except ImportError:
            raise ImportError("PyGithub not installed. Install with: pip install PyGithub")
        return Github(self._token)

    def _repo(self, repo: str):
        return self._github().get_repo(repo)

    # ── Branch operations ─────────────────────────────────────────────────────

    def create_branch(self, repo: str, branch: str, from_ref: str = "main") -> Dict[str, Any]:
        """
        Create a new branch off from_ref.

        Args:
            repo:     Full repo name, e.g. "Prescott-Data/jarviscore-framework"
            branch:   New branch name
            from_ref: Source branch or commit SHA (default: "main")

        Returns:
            {"status": "success", "branch": branch, "sha": head_sha}
        """
        try:
            r = self._repo(repo)
            source = r.get_branch(from_ref)
            r.create_git_ref(f"refs/heads/{branch}", source.commit.sha)
            return {"status": "success", "branch": branch, "sha": source.commit.sha}
        except Exception as exc:
            logger.error("[GitHub] create_branch failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ── PR operations ─────────────────────────────────────────────────────────

    def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        draft: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a pull request.

        Returns:
            {"status": "success", "number": pr_number, "url": pr_html_url}
        """
        try:
            r = self._repo(repo)
            pr = r.create_pull(title=title, body=body, head=head, base=base, draft=draft)
            logger.info("[GitHub] PR #%d created: %s", pr.number, title)
            return {"status": "success", "number": pr.number, "url": pr.html_url}
        except Exception as exc:
            logger.error("[GitHub] create_pr failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def list_prs(self, repo: str, state: str = "open") -> List[Dict[str, Any]]:
        """List pull requests. state: 'open', 'closed', or 'all'."""
        try:
            r = self._repo(repo)
            return [
                {"number": pr.number, "title": pr.title, "state": pr.state, "url": pr.html_url}
                for pr in r.get_pulls(state=state)
            ]
        except Exception as exc:
            logger.error("[GitHub] list_prs failed: %s", exc)
            return []

    # ── Issue operations ──────────────────────────────────────────────────────

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a GitHub issue.

        Returns:
            {"status": "success", "number": issue_number, "url": issue_html_url}
        """
        try:
            r = self._repo(repo)
            issue = r.create_issue(
                title=title,
                body=body,
                labels=labels or [],
                assignees=assignees or [],
            )
            logger.info("[GitHub] Issue #%d created: %s", issue.number, title)
            return {"status": "success", "number": issue.number, "url": issue.html_url}
        except Exception as exc:
            logger.error("[GitHub] create_issue failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ── File operations ───────────────────────────────────────────────────────

    def read_file(self, repo: str, path: str, ref: str = "main") -> str:
        """
        Read a file's content from a GitHub repository.

        Args:
            repo: Full repo name
            path: File path relative to repo root
            ref:  Branch, tag, or commit SHA

        Returns:
            File content as a string, or empty string on error.
        """
        try:
            r = self._repo(repo)
            content = r.get_contents(path, ref=ref)
            return content.decoded_content.decode("utf-8")
        except Exception as exc:
            logger.error("[GitHub] read_file failed: %s", exc)
            return ""

    def create_or_update_file(
        self,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str = "main",
    ) -> Dict[str, Any]:
        """
        Create or update a file in the repository.

        Returns:
            {"status": "success", "sha": commit_sha}
        """
        try:
            r = self._repo(repo)
            try:
                existing = r.get_contents(path, ref=branch)
                result = r.update_file(path, message, content, existing.sha, branch=branch)
                action = "updated"
            except Exception:
                result = r.create_file(path, message, content, branch=branch)
                action = "created"
            commit_sha = result["commit"].sha
            logger.info("[GitHub] File %s (%s): %s", path, action, commit_sha)
            return {"status": "success", "sha": commit_sha, "action": action}
        except Exception as exc:
            logger.error("[GitHub] create_or_update_file failed: %s", exc)
            return {"status": "error", "error": str(exc)}
