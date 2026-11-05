"""Extra memory/instruction files beyond the AGENTS.md hierarchy.

Project: CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, AGENTS.override.md,
.coderouter/AGENTS.md. User-global: ~/.coderouter/AGENTS.md,
~/.claude/CLAUDE.md, ~/.codex/AGENTS.md. Everything is bounded, UTF-8 only,
redacted and treated as read-only guidance.
"""

from pathlib import Path

from coderouter.redaction import redact_sensitive_text

MEMORY_MAX_FILE_BYTES = 32 * 1024
MEMORY_MAX_TOTAL_BYTES = 64 * 1024
PROJECT_MEMORY_FILES = (
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.override.md",
    ".coderouter/AGENTS.md",
)
USER_MEMORY_FILES = (
    ".coderouter/AGENTS.md",
    ".claude/CLAUDE.md",
    ".codex/AGENTS.md",
)
DEFAULT_MEMORY_TARGET = "AGENTS.md"


def _read_bounded(path, budget, secrets):
    try:
        if not path.is_file() or path.is_symlink():
            return ""
        raw = path.read_bytes()
    except OSError:
        return ""
    if len(raw) > MEMORY_MAX_FILE_BYTES or len(raw) > budget:
        return ""
    try:
        text = raw.decode("utf-8").lstrip("﻿")
    except UnicodeDecodeError:
        return ""
    if not text.strip() or "\x00" in text:
        return ""
    return redact_sensitive_text(text.rstrip(), list(secrets or ()))


def memory_candidates(project_root=None, home=None):
    home = Path(home) if home else Path.home()
    found = []
    for relative in USER_MEMORY_FILES:
        found.append(("user", f"~/{relative}", home / relative))
    if project_root:
        root = Path(project_root)
        for relative in PROJECT_MEMORY_FILES:
            found.append(("project", relative, root / relative))
    return found


def load_memory_files(project_root=None, home=None, secrets=None, include_user=True):
    """Return (context_text, loaded_labels)."""
    sections = []
    labels = []
    budget = MEMORY_MAX_TOTAL_BYTES
    seen = set()
    for scope, label, path in memory_candidates(project_root, home):
        if scope == "user" and not include_user:
            continue
        try:
            key = path.resolve()
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        text = _read_bounded(path, budget, secrets)
        if not text:
            continue
        budget -= len(text.encode("utf-8"))
        labels.append(label)
        sections.append(f"=== MEMORY ({scope}): {label} ===\n{text}")
    return "\n\n".join(sections), labels


def combine_instructions(project_instructions, memory_text):
    parts = [part for part in (project_instructions, memory_text) if part and part.strip()]
    return "\n\n".join(parts)


def parse_memory_note(prompt):
    """'#remember this' -> 'remember this'; None when the prompt is not a note."""
    if not isinstance(prompt, str):
        return None
    stripped = prompt.strip()
    if not stripped.startswith("#") or stripped.startswith("##") or "\n" in stripped:
        return None
    note = stripped[1:].strip()
    return note or None


def append_memory_note(project_root, note, filename=DEFAULT_MEMORY_TARGET):
    """Append a bullet to the project memory file. Returns the file path."""
    note = " ".join(str(note).split())
    if not note:
        raise ValueError("Memory note is empty.")
    root = Path(project_root).resolve()
    target = (root / filename).resolve()
    target.relative_to(root)
    existing = ""
    if target.exists():
        existing = target.read_text(encoding="utf-8")
    if "## Notes" not in existing:
        existing = existing.rstrip() + ("\n\n" if existing.strip() else "") + "## Notes\n"
    if not existing.endswith("\n"):
        existing += "\n"
    target.write_text(existing + f"- {note}\n", encoding="utf-8")
    return target


INIT_PROMPT = (
    "Analyse this project and create an AGENTS.md at the repository root for coding agents. "
    "Include: a one-paragraph overview, how to set up, build, run and test (exact commands), "
    "code layout with the role of each top-level module, coding conventions you can observe, "
    "and pitfalls. Keep it under 120 lines, concrete, no filler. If AGENTS.md exists, improve it "
    "instead of replacing useful content."
)
