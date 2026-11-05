"""Skills, agents and output styles loaded from disk (Claude Code / Codex layouts).

Skills:  <project>/.claude/skills/<name>/SKILL.md, <project>/.coderouter/skills/...,
         ~/.claude/skills/..., ~/.coderouter/skills/..., ~/.codex/skills/...
         Frontmatter ``name`` and ``description``; a skill is added to the
         run context when its name or description words match the prompt
         (or always with ``/skill <name>``).
Agents:  .claude/agents/*.md, .coderouter/agents/*.md (+ user dirs). The body
         is a persona prompt applied to runs while the agent is active.
Styles:  .claude/output-styles/*.md, .coderouter/output-styles/*.md (+ user dirs).
"""

import re
from dataclasses import dataclass
from pathlib import Path

from slash_commands import parse_frontmatter

EXT_MAX_BYTES = 32 * 1024
EXT_MAX_ITEMS = 100
SKILL_CONTEXT_MAX_CHARS = 24 * 1024
STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "use", "when", "from", "into", "your", "you", "are",
    "any", "all", "how", "what", "can", "will", "about", "should", "skill", "code", "file", "files",
}


@dataclass(frozen=True)
class Extension:
    kind: str
    name: str
    description: str
    body: str
    source: str
    scope: str

    def keywords(self):
        words = re.findall(r"[a-z][a-z0-9+#-]{2,}", f"{self.name} {self.description}".lower())
        return {word for word in words if word not in STOPWORDS}


def _dirs(kind, project_root, home):
    home = Path(home) if home else Path.home()
    folder = {"skill": "skills", "agent": "agents", "style": "output-styles"}[kind]
    found = [("user", home / ".codex" / folder), ("user", home / ".claude" / folder), ("user", home / ".coderouter" / folder)]
    if project_root:
        root = Path(project_root)
        found += [("project", root / ".claude" / folder), ("project", root / ".coderouter" / folder)]
    return found


def _read(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > EXT_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8").lstrip("﻿")
    except (OSError, UnicodeDecodeError):
        return None


def load_extensions(kind, project_root=None, home=None, extra_dirs=()):
    """name -> Extension; project entries override user and plugin entries."""
    items = {}
    for scope, base in list(extra_dirs) + _dirs(kind, project_root, home):
        if not base.is_dir():
            continue
        candidates = sorted(base.glob("*/SKILL.md")) if kind == "skill" else sorted(base.glob("*.md"))
        for path in candidates[:EXT_MAX_ITEMS]:
            text = _read(path)
            if not text:
                continue
            meta, body = parse_frontmatter(text)
            default_name = path.parent.name if kind == "skill" else path.stem
            name = re.sub(r"[^a-z0-9_.-]+", "-", (meta.get("name") or default_name).lower()).strip("-")
            if not name or not body.strip():
                continue
            description = meta.get("description") or next(
                (line.strip("# ").strip() for line in body.splitlines() if line.strip()), ""
            )
            items[name] = Extension(kind, name, description[:300], body.strip(), str(path), scope)
    return items


def match_skills(skills, prompt, forced=(), limit=3):
    """Skills relevant to the prompt: forced first, then by keyword overlap."""
    words = set(re.findall(r"[a-z][a-z0-9+#-]{2,}", (prompt or "").lower())) - STOPWORDS
    chosen = [skills[name] for name in forced if name in skills]
    scored = []
    for skill in skills.values():
        if skill in chosen:
            continue
        overlap = len(skill.keywords() & words)
        if skill.name in (prompt or "").lower():
            overlap += 3
        if overlap >= 2:
            scored.append((overlap, skill.name, skill))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen += [item[2] for item in scored]
    return chosen[:max(limit, len(forced))]


def skills_context(skills):
    sections, used = [], 0
    for skill in skills:
        block = f"=== SKILL: {skill.name} ({skill.scope}) ===\n{skill.description}\n\n{skill.body}"
        if used + len(block) > SKILL_CONTEXT_MAX_CHARS:
            break
        sections.append(block)
        used += len(block)
    return "\n\n".join(sections)


def agent_context(agent):
    if agent is None:
        return ""
    return f"=== ACTIVE AGENT: {agent.name} ===\n{agent.body}"


def describe(items, empty):
    if not items:
        return empty
    return "\n".join(f"  {item.name} ({item.scope}) - {item.description}" for item in sorted(items.values(), key=lambda i: i.name))
