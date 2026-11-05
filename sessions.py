"""Persistent conversations so a chat can be resumed after restart."""

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from history import user_data_dir
from redaction import redact_sensitive_text

SESSION_MAX_MESSAGES = 200
SESSION_MAX_MESSAGE_CHARS = 8000
SESSION_MAX_FILES = 100
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
COMPACT_KEEP_RECENT = 4


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Conversation:
    session_id: str
    project_root: str = ""
    title: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    messages: list = field(default_factory=list)  # [(role, content)]
    summary: str = ""  # compacted older context

    def add(self, role, content):
        text = redact_sensitive_text(str(content or ""))[:SESSION_MAX_MESSAGE_CHARS]
        self.messages.append((role, text))
        del self.messages[:-SESSION_MAX_MESSAGES]
        if not self.title and role == "user":
            self.title = " ".join(text.split())[:80]
        self.updated_at = _now()

    def model_messages(self):
        """Messages for the model, with the compacted summary first."""
        items = []
        if self.summary:
            items.append(("system", "Summary of earlier conversation: " + self.summary))
        items.extend(self.messages)
        return items

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "project_root": self.project_root,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "messages": [list(item) for item in self.messages],
        }

    @classmethod
    def from_dict(cls, data):
        messages = []
        for item in data.get("messages", []):
            if isinstance(item, (list, tuple)) and len(item) == 2 and all(isinstance(v, str) for v in item):
                messages.append((item[0], item[1]))
        return cls(
            session_id=str(data.get("session_id", "")),
            project_root=str(data.get("project_root", "")),
            title=str(data.get("title", "")),
            created_at=str(data.get("created_at", _now())),
            updated_at=str(data.get("updated_at", _now())),
            messages=messages[-SESSION_MAX_MESSAGES:],
            summary=str(data.get("summary", ""))[:SESSION_MAX_MESSAGE_CHARS],
        )


def new_session_id():
    return "s-" + uuid.uuid4().hex[:12]


class SessionStore:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else user_data_dir() / "sessions"

    def _path(self, session_id):
        if not SESSION_ID_PATTERN.match(session_id or ""):
            raise ValueError("Invalid session id.")
        return self.directory / f"{session_id}.json"

    def save(self, conversation):
        if not conversation.messages and not conversation.summary:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(conversation.session_id)
        payload = json.dumps(conversation.to_dict(), ensure_ascii=False, indent=1)
        handle, temp = tempfile.mkstemp(dir=str(self.directory), prefix=".session-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self._prune()
        return path

    def load(self, session_id):
        path = self._path(session_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return Conversation.from_dict(data)

    def list(self, project_root=None, limit=30):
        if not self.directory.is_dir():
            return []
        items = []
        for path in self.directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if project_root and data.get("project_root") and Path(data["project_root"]) != Path(project_root):
                continue
            items.append(Conversation.from_dict(data))
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[:limit]

    def latest(self, project_root=None):
        items = self.list(project_root, limit=1)
        return items[0] if items else None

    def _prune(self):
        files = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for stale in files[SESSION_MAX_FILES:]:
            try:
                stale.unlink()
            except OSError:
                pass


def compact_prompt(messages, focus=""):
    """Prompt asking a model to summarise older turns."""
    transcript = "\n".join(f"{role}: {content}" for role, content in messages)
    extra = f" Focus on: {focus}." if focus else ""
    return (
        "Summarise this coding-agent conversation so it can continue with less context. Keep decisions, "
        "file paths, open problems and user preferences; drop chatter. At most 200 words, plain text."
        + extra + "\n\n" + transcript
    )


def local_compact(messages, limit=1200):
    """Deterministic fallback summary used when no model is reachable."""
    lines = []
    for role, content in messages:
        text = " ".join(content.split())
        lines.append(f"{role}: {text[:160]}")
    joined = " | ".join(lines)
    return joined[:limit]


def split_for_compaction(messages, keep=COMPACT_KEEP_RECENT):
    if len(messages) <= keep:
        return [], list(messages)
    return list(messages[:-keep]), list(messages[-keep:])
