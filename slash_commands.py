"""Slash command registry: built-in commands plus user/project custom commands.

Custom commands are Markdown prompt files, compatible with the layouts other
code agents use:

    <project>/.claude/commands/*.md      <project>/.coderouter/commands/*.md
    ~/.claude/commands/*.md              ~/.coderouter/commands/*.md
    ~/.codex/prompts/*.md

Optional YAML-ish frontmatter (``description:``, ``argument-hint:``) is read;
the body becomes the prompt. ``$ARGUMENTS`` expands to everything after the
command name and ``$1``..``$9`` to positional arguments. Subdirectories become
namespaces (``frontend/review.md`` -> ``/frontend:review``).
"""

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

CUSTOM_COMMAND_MAX_BYTES = 32 * 1024
CUSTOM_COMMAND_MAX_FILES = 200
COMMAND_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    usage: str = ""
    kind: str = "builtin"  # builtin | custom
    source: str = ""
    body: str = ""
    argument_hint: str = ""
    aliases: tuple = field(default_factory=tuple)

    @property
    def label(self):
        return "/" + self.name


BUILTIN_COMMANDS = (
    SlashCommand("help", "List every command and shortcut"),
    SlashCommand("ask", "Answer a question about the project without editing files", "<question>"),
    SlashCommand("status", "Current task state and recent transitions"),
    SlashCommand("model", "Model routing; /model auto, /model reset, /model <id>:free", "[auto|reset|<id>:free]"),
    SlashCommand("permissions", "Approval mode, gates and allow/deny rules"),
    SlashCommand("review", "Focus the pending changes"),
    SlashCommand("clear", "Start a new chat and clear model context", aliases=("new", "reset")),
    SlashCommand("compact", "Summarise older conversation turns to free context", "[focus]"),
    SlashCommand("resume", "Restore a saved conversation", "[session id]"),
    SlashCommand("sessions", "List saved conversations"),
    SlashCommand("history", "Open the task history panel"),
    SlashCommand("init", "Draft an AGENTS.md for this project"),
    SlashCommand("memory", "Show loaded memory files; /memory add <note>", "[add <note>]"),
    SlashCommand("diff", "Show the pending diff or the git working tree diff"),
    SlashCommand("apply", "Apply all pending changes"),
    SlashCommand("reject", "Discard pending changes, or only the listed files", "[paths]"),
    SlashCommand("undo", "Undo the last apply"),
    SlashCommand("rewind", "Undo applies one by one (up to 10 back)", "[count]"),
    SlashCommand("commit", "Commit applied changes with git", "[message]"),
    SlashCommand("git", "Branch, dirty files and last commit"),
    SlashCommand("branch", "Create or switch to a git branch", "<name>"),
    SlashCommand("auto-commit", "Commit automatically after each apply", "[on|off]"),
    SlashCommand("todos", "Show the plan checklist"),
    SlashCommand("cost", "Token estimate, usage and cost", aliases=("usage",)),
    SlashCommand("context", "What fills the context window, by category"),
    SlashCommand("approval", "Approval mode: suggest, auto-edit, full-auto", "[suggest|auto-edit|full-auto]"),
    SlashCommand("allow", "Add an allow rule, e.g. Bash(pytest*)", "<rule>"),
    SlashCommand("deny", "Add a deny rule, e.g. Read(secrets/**)", "<rule>"),
    SlashCommand("style", "Output style: concise, default, explanatory", "[name]"),
    SlashCommand("effort", "Reasoning effort: low, medium, high", "[level]"),
    SlashCommand("temperature", "Sampling temperature 0-1", "[value]"),
    SlashCommand("theme", "Theme: dark, light, system", "[name]"),
    SlashCommand("motion", "Motion: full, reduced, system", "[mode]"),
    SlashCommand("plan", "Plan gate on or off (off = run straight to changes)", "[on|off]"),
    SlashCommand("hooks", "List configured hooks"),
    SlashCommand("sandbox", "Run commands without network: off or network-off", "[mode]"),
    SlashCommand("profile", "Apply a named settings profile from config", "[name]"),
    SlashCommand("config", "Open settings"),
    SlashCommand("commands", "List custom commands and where they were loaded from"),
    SlashCommand("export", "Export a redacted task report"),
    SlashCommand("verify", "Open verification", "[command]"),
    SlashCommand("add", "Add read-only context files"),
    SlashCommand("image", "Attach an image for vision models"),
    SlashCommand("code-review", "Review the git working tree (or a base branch) with a free model", "[base]", aliases=("cr",)),
    SlashCommand("security-review", "Security review of the working tree or a base branch", "[base]"),
    SlashCommand("pr-description", "Draft a pull request title and body from the diff", "[base]", aliases=("pr",)),
    SlashCommand("test", "Detect and run the project's tests; /test after-apply on|off", "[after-apply on|off]"),
    SlashCommand("restart", "Restart CodeRouter (applies theme changes)"),
    SlashCommand("mention", "Insert @path for a file into the prompt", "<path>"),
    SlashCommand("copy", "Copy the last agent reply to the clipboard"),
    SlashCommand("save", "Save this conversation as Markdown", "[file]"),
    SlashCommand("rename", "Rename this conversation", "<title>"),
    SlashCommand("doctor", "Check Python, Tk, git, key and config"),
    SlashCommand("skills", "List skills; /skill <name> pins one for the next runs", aliases=("skill",)),
    SlashCommand("agents", "List agents; /agent <name> activates a persona, /agent off", aliases=("agent",)),
    SlashCommand("output-style", "List file output styles or pick one", "[name]"),
    SlashCommand("models", "List the free models found on OpenRouter"),
    SlashCommand("fetch", "Add a web page as read-only context", "<url>"),
    SlashCommand("mcp", "MCP servers and tools; /mcp enable <name>, /mcp restart", "[enable <name>|restart]"),
    SlashCommand("stop", "Stop the active run"),
    SlashCommand("exit", "Close CodeRouter", aliases=("quit",)),
)


def _builtin_index():
    index = {}
    for command in BUILTIN_COMMANDS:
        index[command.name] = command
        for alias in command.aliases:
            index[alias] = command
    return index


BUILTIN_INDEX = _builtin_index()


def parse_frontmatter(text):
    """Return (meta, body). Only flat ``key: value`` pairs are supported."""
    meta = {}
    if not text.startswith("---"):
        return meta, text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return meta, "\n".join(lines[index + 1:]).lstrip("\n")
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return {}, text


def custom_command_dirs(project_root=None, home=None):
    """Directories searched for custom commands, lowest precedence first."""
    home = Path(home) if home else Path.home()
    dirs = [
        ("user", home / ".codex" / "prompts"),
        ("user", home / ".claude" / "commands"),
        ("user", home / ".coderouter" / "commands"),
    ]
    if project_root:
        root = Path(project_root)
        dirs += [
            ("project", root / ".claude" / "commands"),
            ("project", root / ".coderouter" / "commands"),
        ]
    return dirs


def _command_name_for(base, path):
    relative = path.relative_to(base).with_suffix("")
    parts = [part.lower().replace(" ", "-") for part in relative.parts]
    return ":".join(parts)


def load_custom_commands(project_root=None, home=None):
    """Load custom commands; later directories override earlier ones."""
    commands = {}
    loaded = 0
    for scope, base in custom_command_dirs(project_root, home):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if loaded >= CUSTOM_COMMAND_MAX_FILES:
                break
            try:
                if path.is_symlink() or path.stat().st_size > CUSTOM_COMMAND_MAX_BYTES:
                    continue
                text = path.read_text(encoding="utf-8").lstrip("﻿")
            except (OSError, UnicodeDecodeError):
                continue
            name = _command_name_for(base, path)
            if not COMMAND_NAME_PATTERN.match(name) or name in BUILTIN_INDEX:
                continue
            meta, body = parse_frontmatter(text)
            if not body.strip():
                continue
            first_line = next((line.strip("# ").strip() for line in body.splitlines() if line.strip()), "")
            description = meta.get("description") or first_line[:80] or "Custom command"
            commands[name] = SlashCommand(
                name=name,
                description=f"{description} ({scope})",
                usage=meta.get("argument-hint", ""),
                kind="custom",
                source=str(path),
                body=body.strip(),
                argument_hint=meta.get("argument-hint", ""),
            )
            loaded += 1
    return commands


def split_command(text):
    """'/name rest of args' -> ('name', 'rest of args'); None when not a command."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped.startswith("/") or len(stripped) < 2:
        return None
    head, _, rest = stripped[1:].partition(" ")
    if not COMMAND_NAME_PATTERN.match(head.lower()):
        return None
    return head.lower(), rest.strip()


def expand_custom_command(command, arguments=""):
    """Substitute $ARGUMENTS and $1..$9 in a custom command body."""
    try:
        positional = shlex.split(arguments)
    except ValueError:
        positional = arguments.split()
    body = command.body

    def positional_value(match):
        index = int(match.group(1)) - 1
        return positional[index] if 0 <= index < len(positional) else ""

    has_placeholder = "$ARGUMENTS" in body or re.search(r"\$[1-9]", body)
    body = body.replace("$ARGUMENTS", arguments)
    body = re.sub(r"\$([1-9])", positional_value, body)
    if arguments and not has_placeholder:
        body = f"{body}\n\n{arguments}"
    return body.strip()


class CommandRegistry:
    def __init__(self, project_root=None, home=None):
        self.project_root = project_root
        self.home = home
        self.custom = {}
        self.reload(project_root)

    def reload(self, project_root=None):
        if project_root is not None:
            self.project_root = project_root
        self.custom = load_custom_commands(self.project_root, self.home)
        return self.custom

    def resolve(self, name):
        return BUILTIN_INDEX.get(name) or self.custom.get(name)

    def all(self):
        seen = []
        for command in BUILTIN_COMMANDS:
            seen.append(command)
        seen.extend(sorted(self.custom.values(), key=lambda item: item.name))
        return seen

    def complete(self, typed, limit=8):
        """Commands whose name starts with what was typed after '/'."""
        if not typed.startswith("/") or " " in typed:
            return []
        prefix = typed[1:].lower()
        matches = [command for command in self.all() if command.name.startswith(prefix)]
        if not matches and prefix:
            matches = [command for command in self.all() if prefix in command.name]
        return matches[:limit]

    def help_text(self):
        lines = ["Commands"]
        for command in self.all():
            usage = f" {command.usage}" if command.usage else ""
            lines.append(f"  /{command.name}{usage} - {command.description}")
        lines += [
            "",
            "Shortcuts",
            "  Ctrl+Enter run · Ctrl+K commands · Ctrl+L new chat · Shift+Tab approval mode",
            "  Esc cancel/close · @path mention a file · #note save to memory · /name custom command",
        ]
        return "\n".join(lines)


def describe_custom_sources(project_root=None, home=None):
    lines = []
    for scope, base in custom_command_dirs(project_root, home):
        marker = "found" if base.is_dir() else "missing"
        lines.append(f"{scope}: {base} ({marker})")
    return lines


def env_home():
    return Path(os.environ.get("CODEROUTER_HOME") or Path.home())


def fuzzy_score(query, text):
    """Subsequence match score (higher is better); None when it does not match."""
    query = query.casefold().strip()
    text_folded = text.casefold()
    if not query:
        return 0
    if text_folded.startswith(query):
        return 1000 - len(text)
    if query in text_folded:
        return 500 - text_folded.index(query)
    position, score, streak = 0, 0, 0
    for char in query:
        found = text_folded.find(char, position)
        if found < 0:
            return None
        streak = streak + 1 if found == position else 0
        score += 10 + streak * 5 - (found - position)
        position = found + 1
    return score


def palette_matches(query, commands, limit=12):
    scored = []
    for command in commands:
        score = fuzzy_score(query, command.name)
        if score is None:
            description_score = fuzzy_score(query, command.description)
            if description_score is None or len(query) < 3:
                continue
            score = description_score - 400
        scored.append((score, command))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [command for _score, command in scored[:limit]]
