"""Safe, explicit Git operations for Madhav.

This module deliberately exposes Git operations as Python functions.  It never
passes natural-language input to a shell and never uses a shell command.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Iterable


DEFAULT_TIMEOUT = 30
_repository_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()

_SECRET_NAME_PATTERNS = (
    re.compile(r"(^|/)(?:\.env(?:\..*)?|.*\.env)$", re.IGNORECASE),
    re.compile(r"(^|/).*(?:credential|secret|password|passwd|token|apikey|api_key).*", re.IGNORECASE),
    re.compile(r"(^|/).*\.(?:pem|key|p12|pfx|jks)$", re.IGNORECASE),
    re.compile(r"(^|/)(?:id_rsa|id_dsa|id_ecdsa|id_ed25519)(?:\.pub)?$", re.IGNORECASE),
)


class GitToolError(RuntimeError):
    """An expected, user-facing Git operation error."""


def _project_directory(project_dir: str | os.PathLike[str] | None = None) -> Path:
    configured = project_dir or os.environ.get("MADHAV_PROJECT_DIR") or os.getcwd()
    path = Path(configured).expanduser().resolve()
    if not path.is_dir():
        raise GitToolError(f"Project directory does not exist: {path}")
    return path


def _run_git(args: list[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitToolError("Git is not installed or is not available on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitToolError(f"Git command timed out after {timeout} seconds.") from exc


def repository_root(project_dir: str | os.PathLike[str] | None = None) -> Path:
    """Return the Git root for the configured/current directory."""
    directory = _project_directory(project_dir)
    result = _run_git(["rev-parse", "--show-toplevel"], directory)
    if result.returncode != 0:
        detail = result.stderr.strip() or "the directory is not inside a Git repository"
        raise GitToolError(f"Git repository validation failed: {detail}")
    return Path(result.stdout.strip()).resolve()


def _lock_for(root: Path) -> threading.Lock:
    with _locks_guard:
        return _repository_locks.setdefault(root, threading.Lock())


def _git_text(args: list[str], root: Path) -> str:
    result = _run_git(args, root)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise GitToolError(detail)
    return result.stdout.strip()


def _git_raw(args: list[str], root: Path) -> str:
    result = _run_git(args, root)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise GitToolError(detail)
    return result.stdout


def _status_entries(root: Path) -> list[tuple[str, str]]:
    """Return status codes and repository-relative paths without quote parsing.

    Porcelain v2 with NUL termination is machine-readable: ordinary records
    contain a fixed header followed by the path, while rename records contain
    the destination path followed by the original path.  Staging the
    destination is sufficient for both ordinary changes and renames.
    """
    output = _git_raw(["status", "--porcelain=v2", "-z", "--untracked-files=all"], root)
    entries: list[tuple[str, str]] = []
    records = output.split("\x00")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue

        record_type = record[0]
        if record_type == "1":
            fields = record.split(" ", 8)
            if len(fields) == 9:
                entries.append((fields[1], fields[8]))
        elif record_type == "2":
            fields = record.split(" ", 9)
            if len(fields) == 10:
                entries.append((fields[1], fields[9]))
                # The next NUL-delimited field is the rename source path.
                index += 1
        elif record_type == "?":
            if record.startswith("? "):
                entries.append(("??", record[2:]))
    return entries


def is_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in _SECRET_NAME_PATTERNS)


def check_status(project_dir: str | os.PathLike[str] | None = None) -> str:
    root = repository_root(project_dir)
    branch = current_branch(root)
    status = _git_text(["status", "--short", "--branch", "--untracked-files=all"], root)
    return f"Repository: {root}\nBranch: {branch}\n{status or 'Working tree clean.'}"


def list_changed_files(project_dir: str | os.PathLike[str] | None = None) -> dict[str, object]:
    root = repository_root(project_dir)
    entries = _status_entries(root)
    changed = [path for code, path in entries if not code.startswith("??")]
    untracked = [path for code, path in entries if code.startswith("??")]
    return {"repository": str(root), "changed": changed, "untracked": untracked}


def current_branch(project_dir: str | os.PathLike[str] | None = None) -> str:
    root = project_dir if isinstance(project_dir, Path) else repository_root(project_dir)
    return _git_text(["branch", "--show-current"], root) or "(detached HEAD)"


def recent_commits(count: int = 5, project_dir: str | os.PathLike[str] | None = None) -> str:
    if not isinstance(count, int) or not 1 <= count <= 50:
        raise GitToolError("Commit count must be an integer from 1 to 50.")
    root = repository_root(project_dir)
    return _git_text(["log", f"-{count}", "--oneline", "--decorate"], root) or "No commits found."


def _safe_stage_paths(root: Path) -> tuple[list[str], list[str]]:
    safe, secrets = [], []
    for _, path in _status_entries(root):
        (secrets if is_sensitive_path(path) else safe).append(path)
    return safe, secrets


def _staged_paths(root: Path) -> list[str]:
    output = _git_raw(["diff", "--cached", "--name-only", "-z"], root)
    return [path for path in output.split("\x00") if path]


def list_staged_files(project_dir: str | os.PathLike[str] | None = None) -> dict[str, object]:
    root = repository_root(project_dir)
    staged = _staged_paths(root)
    return {
        "repository": str(root),
        "staged": staged,
        "secret_files": [path for path in staged if is_sensitive_path(path)],
    }


def stage_changes(project_dir: str | os.PathLike[str] | None = None, paths: Iterable[str] | None = None) -> dict[str, object]:
    root = repository_root(project_dir)
    safe, secrets = _safe_stage_paths(root) if paths is None else ([], [])
    if paths is not None:
        status_paths = {path for _, path in _status_entries(root)}
        for path in paths:
            if not isinstance(path, str) or not path.strip() or Path(path).is_absolute() or "\x00" in path:
                raise GitToolError("Stage paths must be non-empty repository-relative paths.")
            normalized_path = path.replace("\\", "/")
            if normalized_path not in status_paths:
                raise GitToolError(f"Path is not a currently changed repository file: {path}")
            (secrets if is_sensitive_path(normalized_path) else safe).append(normalized_path)
    if not safe:
        return {"repository": str(root), "staged": [], "skipped_secrets": secrets, "message": "No safe files to stage."}
    with _lock_for(root):
        result = _run_git(["add", "--", *safe], root)
        if result.returncode != 0:
            raise GitToolError(result.stderr.strip() or "Git could not stage the requested files.")
    return {"repository": str(root), "staged": safe, "skipped_secrets": secrets}


def create_commit(
    message: str,
    project_dir: str | os.PathLike[str] | None = None,
    *,
    confirmed: bool = False,
) -> str:
    if not confirmed:
        raise GitToolError("Commit confirmation is required before creating a commit.")
    if not isinstance(message, str) or not message.strip():
        raise GitToolError("A non-empty commit message is required.")
    if "\x00" in message or len(message.strip()) > 500:
        raise GitToolError("Commit message is invalid or too long.")
    root = repository_root(project_dir)
    staged = _staged_paths(root)
    if not staged:
        raise GitToolError("No staged changes to commit.")
    secret_files = [path for path in staged if is_sensitive_path(path)]
    if secret_files:
        raise GitToolError(
            "Refusing to commit possible secret files: " + ", ".join(secret_files)
        )
    with _lock_for(root):
        result = _run_git(["commit", "-m", message.strip()], root)
    if result.returncode != 0:
        raise GitToolError((result.stderr or result.stdout).strip() or "Git commit failed.")
    return (result.stdout or "Commit created successfully.").strip()


def _remote_info(root: Path) -> tuple[str, str]:
    branch = current_branch(root)
    branch_remote = _run_git(["config", "--get", f"branch.{branch}.remote"], root)
    remote = branch_remote.stdout.strip() if branch_remote.returncode == 0 else ""
    if not remote:
        remotes = _git_text(["remote"], root)
        remote = remotes.splitlines()[0] if remotes else ""
    if not remote:
        raise GitToolError("No configured Git remote was found for the current branch.")
    return branch, remote


def push_current_branch(
    project_dir: str | os.PathLike[str] | None = None,
    *,
    confirmed: bool = False,
) -> str:
    if not confirmed:
        raise GitToolError("Push confirmation is required before pushing changes.")
    root = repository_root(project_dir)
    branch, remote = _remote_info(root)
    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root)
    if upstream.returncode != 0:
        raise GitToolError(f"Branch '{branch}' has no configured upstream on remote '{remote}'. Configure it explicitly before pushing.")
    with _lock_for(root):
        result = _run_git(["push", remote, branch], root, timeout=120)
    if result.returncode != 0:
        raise GitToolError((result.stderr or result.stdout).strip() or "Git push failed.")
    return (result.stdout or f"Pushed {branch} to {remote}.").strip()


def add_commit_push(
    message: str,
    project_dir: str | os.PathLike[str] | None = None,
    *,
    confirmed: bool = False,
) -> dict[str, object]:
    if not confirmed:
        raise GitToolError("Commit and push confirmation is required before changing the repository or remote.")
    if not message or not message.strip():
        raise GitToolError("A non-empty commit message is required.")
    staged = stage_changes(project_dir)
    if not staged["staged"]:
        raise GitToolError(staged.get("message", "No safe files were staged."))
    commit_output = create_commit(message, project_dir, confirmed=True)
    push_output = push_current_branch(project_dir, confirmed=True)
    return {"staged": staged, "commit": commit_output, "push": push_output}

