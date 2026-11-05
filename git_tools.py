"""Small git helpers. argv only, never a shell; every call is bounded."""

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_SECONDS = 15
GIT_DIFF_MAX_CHARS = 48 * 1024


@dataclass(frozen=True)
class GitStatus:
    is_repo: bool = False
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    changed: tuple = field(default_factory=tuple)
    last_commit: str = ""

    @property
    def dirty(self):
        return bool(self.changed)

    def label(self):
        if not self.is_repo:
            return ""
        marks = []
        if self.changed:
            marks.append(f"±{len(self.changed)}")
        if self.ahead:
            marks.append(f"↑{self.ahead}")
        if self.behind:
            marks.append(f"↓{self.behind}")
        return " ".join([self.branch or "detached"] + marks)


def git_available():
    return shutil.which("git") is not None


def run_git(root, *args, timeout=GIT_TIMEOUT_SECONDS, input_text=None):
    """Run git in root; returns (code, stdout, stderr)."""
    if not git_available():
        return 127, "", "git is not installed"
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            input=input_text,
            stdin=None if input_text is not None else subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def is_git_repo(root):
    if not root or not Path(root).is_dir():
        return False
    code, out, _ = run_git(root, "rev-parse", "--is-inside-work-tree")
    return code == 0 and out.strip() == "true"


def parse_porcelain_v2(text):
    branch, ahead, behind, changed = "", 0, 0, []
    for line in text.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
            if branch == "(detached)":
                branch = ""
        elif line.startswith("# branch.ab "):
            parts = line.split()
            try:
                ahead = int(parts[2].lstrip("+"))
                behind = abs(int(parts[3]))
            except (IndexError, ValueError):
                pass
        elif line.startswith(("1 ", "2 ")):
            parts = line.split(" ")
            path = parts[-1].split("\t")[0] if line.startswith("2 ") else parts[-1]
            changed.append((parts[1], path))
        elif line.startswith("? "):
            changed.append(("??", line[2:]))
        elif line.startswith("u "):
            changed.append(("UU", line.split(" ")[-1]))
    return branch, ahead, behind, tuple(changed)


def git_status(root):
    if not is_git_repo(root):
        return GitStatus()
    code, out, _ = run_git(root, "status", "--porcelain=v2", "--branch")
    if code != 0:
        return GitStatus(is_repo=True)
    branch, ahead, behind, changed = parse_porcelain_v2(out)
    code, last, _ = run_git(root, "log", "-1", "--format=%h %s")
    return GitStatus(True, branch, ahead, behind, changed, last.strip() if code == 0 else "")


def git_diff(root, staged=False, max_chars=GIT_DIFF_MAX_CHARS):
    args = ["diff", "--no-color", "--no-ext-diff"]
    if staged:
        args.append("--cached")
    code, out, err = run_git(root, *args)
    if code != 0:
        return f"(git diff failed: {err.strip()[:200]})"
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n… diff truncated at {max_chars} characters"
    return out


def git_review_diff(root, base="", max_chars=GIT_DIFF_MAX_CHARS):
    """Diff to review: against base (merge-base) or the working tree incl. untracked files."""
    if base:
        code, merge_base, err = run_git(root, "merge-base", "HEAD", base)
        if code != 0:
            return f"(cannot find merge base with {base}: {err.strip()[:200]})"
        code, out, err = run_git(root, "diff", "--no-color", "--no-ext-diff", merge_base.strip())
    else:
        code, out, err = run_git(root, "diff", "--no-color", "--no-ext-diff", "HEAD")
        if code != 0:
            code, out, err = run_git(root, "diff", "--no-color", "--no-ext-diff")
        _c, untracked, _e = run_git(root, "ls-files", "--others", "--exclude-standard")
        for path in untracked.splitlines()[:40]:
            target = Path(root) / path
            try:
                if target.stat().st_size <= 64 * 1024:
                    body = target.read_text(encoding="utf-8")
                    out += f"\n--- /dev/null\n+++ b/{path}\n" + "".join("+" + line + "\n" for line in body.splitlines())
            except (OSError, UnicodeDecodeError):
                continue
    if code != 0:
        return f"(git diff failed: {err.strip()[:200]})"
    if len(out) > max_chars:
        out = out[:max_chars] + f"\n… diff truncated at {max_chars} characters"
    return out


REVIEW_PROMPT = (
    "Review this diff like a senior engineer. List only real problems: bugs, security issues, data loss, "
    "missing error handling, broken tests, confusing names. For each: file:line, severity (high/medium/low), "
    "one-sentence problem, one-sentence fix. If it looks good, say so in one line. No praise, no filler.\n\n"
)


def git_commit(root, message, paths=None):
    """Stage paths (or all tracked + new changes) and commit. Returns (ok, text)."""
    message = (message or "").strip()
    if not message:
        return False, "Commit message is empty."
    if not is_git_repo(root):
        return False, "Not a git repository."
    add_args = ["add", "--"] + list(paths) if paths else ["add", "-A"]
    code, _, err = run_git(root, *add_args)
    if code != 0:
        return False, f"git add failed: {err.strip()[:300]}"
    code, out, err = run_git(root, "commit", "-F", "-", input_text=message + "\n")
    if code != 0:
        return False, (err or out).strip()[:400] or "git commit failed"
    return True, out.strip().splitlines()[0] if out.strip() else "Committed."


def suggest_commit_message(changed_paths, summary=""):
    """Local fallback message when no model drafts one."""
    summary = " ".join((summary or "").split())
    if summary:
        first = summary.split(". ")[0].rstrip(".")
        return first[:72]
    paths = list(changed_paths)
    if len(paths) == 1:
        return f"Update {paths[0]}"[:72]
    return f"Update {len(paths)} files"
