"""GAIT-style immutable Git audit trail.

Every automation session:
  1. Creates a branch: automation-{timestamp}-{sanitized_ip}
  2. Writes JSON "turn" files sequentially: 00_input.json, 01_baseline.json, …
  3. Commits after every major step — creating a forensic record of
     "what data the AI saw, what it decided, and what happened" that lives
     forever in the audit repo even if the session is long over.

The audit repo is a plain git repository mounted at /app/audit-repo.
Each branch = one automation session. Never force-pushed, never rebased.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import git

from app.config import settings
import app.metrics as m

logger = logging.getLogger(__name__)


def _sanitize_branch(text: str) -> str:
    """Make text safe for a git branch name component."""
    return re.sub(r"[^a-zA-Z0-9._-]", "-", text)


class AuditSession:
    """Represents one open automation session on its own git branch.

    Callers call record_turn() after each major step, then close() at the end.
    Each record_turn() writes a file and commits it — the branch is a linear
    history of every decision made during the session.
    """

    def __init__(
        self,
        repo: git.Repo,
        branch: str,
        session_dir: Path,
        session_id: str,
    ) -> None:
        self.repo = repo
        self.branch = branch
        self.session_dir = session_dir
        self.session_id = session_id
        self._turn_counter = 0

    def record_turn(
        self,
        name: str,
        data: Any,
        as_text: bool = False,
    ) -> Path:
        """Persist a turn artifact and commit it to the audit branch.

        Args:
            name:     Human-readable step name, e.g. "baseline" or "proposed_action".
            data:     Serialisable data (dict/list) or plain string if as_text=True.
            as_text:  Write raw text (e.g. prompt strings) instead of JSON.

        Returns:
            Path to the written file.
        """
        idx = f"{self._turn_counter:02d}"
        self._turn_counter += 1
        ext = ".txt" if as_text else ".json"
        filename = f"{idx}_{name}{ext}"
        fpath = self.session_dir / filename

        if as_text:
            fpath.write_text(str(data), encoding="utf-8")
        else:
            fpath.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )

        rel = str(fpath.relative_to(Path(self.repo.working_dir)))
        self.repo.index.add([rel])
        self.repo.index.commit(
            f"[{self.session_id}] turn: {name}",
            author=git.Actor(
                settings.audit_git_user_name,
                settings.audit_git_user_email,
            ),
            committer=git.Actor(
                settings.audit_git_user_name,
                settings.audit_git_user_email,
            ),
        )
        m.automation_audit_commits_total.inc()
        logger.debug(
            "GAIT committed %s → branch %s",
            filename,
            self.branch,
        )
        return fpath

    def close(self, outcome: str, success: bool) -> None:
        """Write a final outcome turn and seal the session."""
        self.record_turn(
            "outcome",
            {
                "outcome": outcome,
                "success": success,
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "session_id": self.session_id,
                "branch": self.branch,
            },
        )
        logger.info(
            "GAIT session %s closed — outcome=%s success=%s branch=%s",
            self.session_id,
            outcome,
            success,
            self.branch,
        )


class GitAuditTrail:
    """Manages the automation audit git repository.

    One instance lives for the lifetime of the service (module-level singleton).
    Thread-safety note: git operations are serialised by the APScheduler
    max_instances=1 constraint; approval endpoint tasks are short and unlikely
    to conflict, but if concurrency grows consider a threading.Lock here.
    """

    def __init__(self) -> None:
        self._repo: git.Repo | None = None
        self._main_branch: str = "main"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Open or create the audit git repository. Safe to call on every startup."""
        audit_path = Path(settings.audit_repo_path)
        audit_path.mkdir(parents=True, exist_ok=True)

        if (audit_path / ".git").exists():
            self._repo = git.Repo(str(audit_path))
            self._main_branch = self._repo.active_branch.name
            logger.info(
                "GAIT: opened existing audit repo at %s (branch=%s, commits=%d)",
                audit_path,
                self._main_branch,
                len(list(self._repo.iter_commits())),
            )
            return

        # First-time init
        self._repo = git.Repo.init(str(audit_path))
        self._configure_git_identity()

        readme = audit_path / "README.md"
        readme.write_text(
            "# Convergence Automation Audit Trail\n\n"
            "This repository stores **immutable** records of every automation "
            "session run by the Convergence AutoAgent (Phase 5).\n\n"
            "## Structure\n"
            "Each automation session lives on its own branch:\n"
            "```\n"
            "automation-YYYYMMDD-HHMMSS-{sanitized_ip}/\n"
            "  sessions/automation-YYYYMMDD-HHMMSS-{sanitized_ip}/\n"
            "    00_input.json          — threat intel data that triggered the session\n"
            "    01_baseline.json       — VictoriaMetrics snapshot before any action\n"
            "    02_claude_prompt.txt   — exact prompt sent to Claude\n"
            "    03_proposed_action.json — Claude's structured action proposal\n"
            "    04_decision.json       — dry_run / pending / auto_approve decision\n"
            "    05_execution_result.json — result of pfSense action (if executed)\n"
            "    06_verification.json   — post-action metrics comparison\n"
            "    07_outcome.json        — final sealed outcome\n"
            "```\n\n"
            "## Audit queries\n"
            "```bash\n"
            "# List all sessions\n"
            "git branch -a\n\n"
            "# Review a specific session\n"
            "git checkout automation-20260225-143021-1-2-3-4\n"
            "ls sessions/\n"
            "cat sessions/automation-*/03_proposed_action.json\n"
            "```\n",
            encoding="utf-8",
        )
        self._repo.index.add(["README.md"])
        self._repo.index.commit(
            "chore: initialize GAIT audit repository",
            author=git.Actor(
                settings.audit_git_user_name,
                settings.audit_git_user_email,
            ),
            committer=git.Actor(
                settings.audit_git_user_name,
                settings.audit_git_user_email,
            ),
        )
        self._main_branch = self._repo.active_branch.name
        logger.info("GAIT: initialized new audit repo at %s", audit_path)

    def _configure_git_identity(self) -> None:
        with self._repo.config_writer() as cfg:  # type: ignore[union-attr]
            cfg.set_value("user", "name", settings.audit_git_user_name)
            cfg.set_value("user", "email", settings.audit_git_user_email)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def open_session(self, ip: str, session_id: str) -> AuditSession:
        """Create a new audit branch and return an open AuditSession.

        Args:
            ip:          The IP address being evaluated (for branch naming).
            session_id:  Unique session identifier, e.g. "20260225-143021-1-2-3-4".
        """
        if self._repo is None:
            raise RuntimeError("GitAuditTrail.initialize() must be called first")

        branch_name = f"automation-{_sanitize_branch(session_id)}"

        # Always branch from main so branches are independent
        self._repo.git.checkout(self._main_branch)

        # Guard against duplicate branch names (shouldn't happen with timestamp IDs)
        existing = [h.name for h in self._repo.heads]
        if branch_name in existing:
            branch_name = f"{branch_name}-{int(time.time())}"

        new_branch = self._repo.create_head(branch_name)
        new_branch.checkout()

        session_dir = (
            Path(self._repo.working_dir) / "sessions" / branch_name
        )
        session_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "GAIT: opened session %s on branch %s",
            session_id,
            branch_name,
        )
        return AuditSession(
            repo=self._repo,
            branch=branch_name,
            session_dir=session_dir,
            session_id=session_id,
        )

    def list_sessions(self, limit: int = 50) -> list[dict]:
        """Return metadata about recent audit sessions (most recent first)."""
        if self._repo is None:
            return []
        sessions = []
        for head in self._repo.heads:
            if not head.name.startswith("automation-"):
                continue
            commit = head.commit
            sessions.append(
                {
                    "branch": head.name,
                    "last_commit": commit.message.strip(),
                    "committed_at": datetime.fromtimestamp(
                        commit.committed_date, tz=timezone.utc
                    ).isoformat(),
                    "files": len(list(commit.tree.traverse())),
                }
            )
        sessions.sort(key=lambda s: s["committed_at"], reverse=True)
        return sessions[:limit]

    @property
    def initialized(self) -> bool:
        return self._repo is not None


# Module-level singleton — imported by scheduler and main
trail = GitAuditTrail()
