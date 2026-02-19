"""Git-based knowledge base versioning."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_REPO_DIR = "/app/repo"
_KB_PATH = "workspace/analysis/knowledge_base.md"
_GIT_USER = "Finance Agent"
_GIT_EMAIL = "agent@local"
_git_available: bool | None = None


@dataclass
class KBVersion:
    sha: str
    date: str
    message: str


async def _run_git(*args: str, cwd: str = _REPO_DIR) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout)."""
    cmd = ["git", "-C", cwd, "-c", f"user.name={_GIT_USER}", "-c", f"user.email={_GIT_EMAIL}"]
    cmd.extend(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0 and stderr:
            logger.debug("git %s stderr: %s", args[0], stderr.decode(errors="replace").strip())
        return proc.returncode or 0, stdout.decode(errors="replace").strip()
    except Exception:
        logger.debug("git command failed: %s", " ".join(cmd), exc_info=True)
        return 1, ""


async def commit_kb(repo_dir: str = _REPO_DIR) -> bool:
    """Stage and commit knowledge_base.md. Returns True if a commit was created."""
    global _git_available
    if _git_available is False:
        return False
    if _git_available is None:
        rc, _ = await _run_git("rev-parse", "--git-dir", cwd=repo_dir)
        _git_available = rc == 0
        if not _git_available:
            logger.info("Git repo not available at %s, KB versioning disabled", repo_dir)
            return False

    rc, _ = await _run_git("add", "--", _KB_PATH, cwd=repo_dir)
    if rc != 0:
        logger.debug("git add failed (rc=%d)", rc)
        return False

    # Check if there are staged changes for the KB file
    rc, _ = await _run_git("diff", "--cached", "--quiet", "--", _KB_PATH, cwd=repo_dir)
    if rc == 0:
        # No changes staged
        return False

    rc, _ = await _run_git("commit", "-m", "Update knowledge base", "--", _KB_PATH, cwd=repo_dir)
    if rc != 0:
        logger.debug("git commit failed (rc=%d)", rc)
        return False

    logger.info("Knowledge base committed to git")
    return True


async def get_versions(repo_dir: str = _REPO_DIR, limit: int = 50) -> list[KBVersion]:
    """Get git log for knowledge_base.md."""
    rc, output = await _run_git(
        "log",
        f"-{limit}",
        "--format=%H|%ai|%s",
        "--",
        _KB_PATH,
        cwd=repo_dir,
    )
    if rc != 0 or not output:
        return []

    versions = []
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            versions.append(KBVersion(sha=parts[0], date=parts[1], message=parts[2]))
    return versions


async def get_version_content(sha: str, repo_dir: str = _REPO_DIR) -> str | None:
    """Get knowledge_base.md content at a specific commit."""
    rc, output = await _run_git("show", f"{sha}:{_KB_PATH}", cwd=repo_dir)
    if rc != 0:
        return None
    return output
