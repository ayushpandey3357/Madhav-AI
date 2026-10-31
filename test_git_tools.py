"""Safe Git automation tests using only temporary repositories."""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from main import TOOLS, detect_tool_request
from tools.git_tools import (
    GitToolError,
    check_status,
    create_commit,
    current_branch,
    list_changed_files,
    push_current_branch,
    recent_commits,
    repository_root,
    stage_changes,
)


def run_git(directory, *args):
    result = subprocess.run(["git", *args], cwd=directory, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result.stdout.strip()


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    print(f"[PASS] {description}")


with tempfile.TemporaryDirectory(prefix="madhav-git-test-") as temporary:
    repo = Path(temporary)
    run_git(repo, "init")
    run_git(repo, "config", "user.name", "Madhav Test")
    run_git(repo, "config", "user.email", "madhav-test@example.invalid")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    (repo / "main.py").write_text("print('initial')\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (repo / "tracked file.txt").write_text("initial\n", encoding="utf-8")
    run_git(repo, "add", "--", "README.md", "main.py", ".gitignore", "tracked file.txt")
    run_git(repo, "commit", "-m", "initial commit")

    (repo / "README.md").write_text("modified\n", encoding="utf-8")
    (repo / "main.py").write_text("print('modified')\n", encoding="utf-8")
    (repo / "tracked file.txt").write_text("modified\n", encoding="utf-8")
    (repo / ".gitignore").unlink()
    run_git(repo, "mv", "tracked file.txt", "renamed file.txt")
    (repo / "new file.py").write_text("print('new')\n", encoding="utf-8")
    (repo / ".env").write_text("TOKEN=do-not-stage\n", encoding="utf-8")

    check(repository_root(repo) == repo.resolve(), "repository validation finds the temporary Git root")
    files = list_changed_files(repo)
    changed = files["changed"]
    untracked = files["untracked"]
    check("README.md" in changed, "README.md keeps its complete filename")
    check("main.py" in changed, "modified Python files are listed")
    check(".gitignore" in changed, "deleted dotfiles are listed")
    check("renamed file.txt" in changed, "renamed files use the destination path")
    check("new file.py" in untracked, "untracked files with spaces are listed")
    check("EADME.md" not in changed, "README.md is never truncated")
    check(current_branch(repo), "current branch is reported")
    check("initial commit" in recent_commits(5, repo), "recent commits are reported")
    check("README.md" in check_status(repo), "status includes changed files")

    staged = stage_changes(repo)
    check("README.md" in staged["staged"], "modified file is staged")
    check("new file.py" in staged["staged"], "untracked file with spaces is staged")
    check("renamed file.txt" in staged["staged"], "renamed destination is staged")
    check(".env" in staged["skipped_secrets"], "secret-like file is not staged")
    cached = run_git(repo, "diff", "--cached", "--name-only")
    cached_paths = cached.splitlines()
    check("README.md" in cached_paths and "EADME.md" not in cached_paths, "the complete README.md path is in the Git index")
    check("new file.py" in cached, "the spaced filename is in the Git index")

    commit_output = create_commit("fixed login bug", repo)
    check("fixed login bug" in commit_output, "commit uses the supplied message")
    check("fixed login bug" in recent_commits(1, repo), "commit appears in recent history")

    try:
        push_current_branch(repo)
    except GitToolError as error:
        check("remote" in str(error).lower(), "push without a remote reports the actual configuration problem")
    else:
        raise AssertionError("push without an upstream unexpectedly succeeded")

    run_git(repo, "remote", "add", "origin", "https://example.invalid/madhav-test.git")
    try:
        push_current_branch(repo)
    except GitToolError as error:
        check("upstream" in str(error).lower(), "push without an upstream reports the actual configuration problem")
    else:
        raise AssertionError("push without an upstream unexpectedly succeeded")

    try:
        repository_root(repo / "missing")
    except GitToolError:
        print("[PASS] invalid repository path is rejected")
    else:
        raise AssertionError("invalid repository path was accepted")

detector_cases = {
    "Commit my changes with message fixed login bug.": "fixed login bug",
    "Show my last five commits.": "5",
    "What is git commit?": None,
}
for text, expected_query in detector_cases.items():
    request = detect_tool_request(text)
    actual_query = request.get("query") if request else None
    check(actual_query == expected_query, f"Git intent detection: {text}")

check("git_status" in TOOLS and "git_add_commit_push" in TOOLS, "Git functions are explicitly allowlisted")
print("Git automation tests passed.")

