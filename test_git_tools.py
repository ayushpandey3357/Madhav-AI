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
    list_staged_files,
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

    specific_stage = stage_changes(repo, paths=["README.md"])
    check(specific_stage["staged"] == ["README.md"], "specific-file staging uses the exact validated path")
    run_git(repo, "reset")
    try:
        stage_changes(repo, paths=["."])
    except GitToolError as error:
        check("currently changed" in str(error), "directory path staging is rejected before it can include secrets")
    else:
        raise AssertionError("directory path staging unexpectedly succeeded")

    staged = stage_changes(repo)
    check("README.md" in staged["staged"], "modified file is staged")
    check("new file.py" in staged["staged"], "untracked file with spaces is staged")
    check("renamed file.txt" in staged["staged"], "renamed destination is staged")
    check(".env" in staged["skipped_secrets"], "secret-like file is not staged")
    cached = run_git(repo, "diff", "--cached", "--name-only")
    cached_paths = cached.splitlines()
    check("README.md" in cached_paths and "EADME.md" not in cached_paths, "the complete README.md path is in the Git index")
    check("new file.py" in cached, "the spaced filename is in the Git index")
    staged_listing = list_staged_files(repo)
    check("README.md" in staged_listing["staged"], "cached index inspection finds staged README.md")

    try:
        create_commit("should require confirmation", repo)
    except GitToolError as error:
        check("confirmation" in str(error).lower(), "unconfirmed commits are rejected")
    else:
        raise AssertionError("unconfirmed commit unexpectedly succeeded")

    commit_output = create_commit("fixed login bug", repo, confirmed=True)
    check("fixed login bug" in commit_output, "commit uses the supplied message")
    check("fixed login bug" in recent_commits(1, repo), "commit appears in recent history")

    try:
        create_commit("nothing staged", repo, confirmed=True)
    except GitToolError as error:
        check("no staged changes" in str(error).lower(), "no staged changes produces a clear error")
    else:
        raise AssertionError("empty index unexpectedly created a commit")

    (repo / "README.md").write_text("staged version\n", encoding="utf-8")
    stage_changes(repo, paths=["README.md"])
    (repo / "README.md").write_text("unstaged version\n", encoding="utf-8")
    create_commit("commit staged snapshot only", repo, confirmed=True)
    check(
        run_git(repo, "show", "HEAD:README.md") == "staged version",
        "commit includes the staged snapshot, not later unstaged edits",
    )
    check("README.md" in run_git(repo, "status", "--short"), "unstaged edits remain after commit")

    (repo / "rejected.txt").write_text("must remain staged\n", encoding="utf-8")
    stage_changes(repo, paths=["rejected.txt"])
    commit_count = run_git(repo, "rev-list", "--count", "HEAD")
    try:
        create_commit("rejected confirmation", repo)
    except GitToolError as error:
        check("confirmation" in str(error).lower(), "rejected confirmation prevents a commit")
    else:
        raise AssertionError("rejected confirmation unexpectedly created a commit")
    check(run_git(repo, "rev-list", "--count", "HEAD") == commit_count, "rejected confirmation leaves history unchanged")
    create_commit("accepted after rejection test", repo, confirmed=True)

    try:
        push_current_branch(repo, confirmed=True)
    except GitToolError as error:
        check("remote" in str(error).lower(), "push without a remote reports the actual configuration problem")
    else:
        raise AssertionError("push without an upstream unexpectedly succeeded")

    try:
        push_current_branch(repo)
    except GitToolError as error:
        check("confirmation" in str(error).lower(), "unconfirmed pushes are rejected")
    else:
        raise AssertionError("unconfirmed push unexpectedly succeeded")

    remote_directory = tempfile.TemporaryDirectory(prefix="madhav-git-remote-")
    bare_remote = Path(remote_directory.name) / "remote.git"
    run_git(repo.parent, "init", "--bare", str(bare_remote))
    run_git(repo, "remote", "add", "local", str(bare_remote))
    run_git(repo, "push", "--set-upstream", "local", current_branch(repo))
    (repo / "README.md").write_text("pushed update\n", encoding="utf-8")
    stage_changes(repo, paths=["README.md"])
    create_commit("prepare local push", repo, confirmed=True)
    push_output = push_current_branch(repo, confirmed=True)
    check("local" in push_output or "Everything up-to-date" in push_output, "push succeeds to a temporary bare remote")
    check("prepare local push" in run_git(bare_remote, "log", "--all", "--oneline"), "temporary bare remote received the commit")
    remote_directory.cleanup()

    run_git(repo, "remote", "remove", "local")
    run_git(repo, "remote", "add", "origin", "https://example.invalid/madhav-test.git")
    try:
        push_current_branch(repo, confirmed=True)
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
    "Commit with message Improve Git automation": "Improve Git automation",
    "Stage My Project.txt": "My Project.txt",
    "Commit my changes with message Fix README.md": "Fix README.md",
    "Show my last five commits.": "5",
    "What is git commit?": None,
}
for text, expected_query in detector_cases.items():
    request = detect_tool_request(text)
    actual_query = request.get("query") if request else None
    check(actual_query == expected_query, f"Git intent detection: {text}")

check("git_status" in TOOLS and "git_add_commit_push" in TOOLS, "Git functions are explicitly allowlisted")
print("Git automation tests passed.")

