"""Local task history: records, persistence, and display formatting."""

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from constants import (
    APP_TITLE,
    HISTORY_BROWSER_MAX_REASONS,
    HISTORY_BROWSER_MAX_STEPS,
    HISTORY_BROWSER_MAX_TRANSITIONS,
    HISTORY_MAX_BYTES,
    HISTORY_MAX_PATH_CHARS,
    HISTORY_MAX_REASONS,
    HISTORY_MAX_RECORDS,
    HISTORY_MAX_TEXT_CHARS,
    HISTORY_MAX_TRANSITIONS,
    PLAN_MAX_FIELD_CHARS,
    PLAN_MAX_STEPS,
    SESSION_ID_MAX_CHARS,
    SESSION_PARENT_MAX_CHARS,
    TASK_STATE_PLANNING,
)
from redaction import SECRET_PATTERN, redact_sensitive_text
from run_types import ExecutionPlan, PlanStep


def _history_timestamp():
    return datetime.now(timezone.utc).isoformat()


def default_history_path():
    """Return the user-local history path, never a path inside the repository."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_TITLE / "history.json"


HISTORY_PATH = default_history_path()


def _history_bound_text(value, limit=HISTORY_MAX_TEXT_CHARS):
    redacted = redact_sensitive_text(str(value or ""))
    compact = " ".join(redacted.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


_HISTORY_LINEAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


def _history_lineage_id(value, *, fallback="", allow_empty=False, limit=SESSION_ID_MAX_CHARS):
    raw = str(value or "").strip()
    if not raw:
        if allow_empty:
            return ""
        raw = str(fallback or "").strip()
    if not raw:
        return None
    if len(raw) > limit or redact_sensitive_text(raw) != raw:
        return None
    if SECRET_PATTERN.search(raw) or not _HISTORY_LINEAGE_ID_PATTERN.fullmatch(raw):
        return None
    return raw


@dataclass(frozen=True)
class HistoryRecord:
    """Bounded, redacted metadata for one task; never a file/proposal snapshot."""

    task_id: str
    project_root: str
    request_summary: str
    plan_summary: str = ""
    plan_steps: tuple[PlanStep, ...] = ()
    selected_model: str = ""
    state_transitions: tuple[tuple[str, str, str], ...] = ()
    reasons: tuple[str, ...] = ()
    outcome: str = ""
    created_at: str = ""
    updated_at: str = ""
    session_id: str = ""
    parent_task_id: str = ""
    parent_session_id: str = ""

    @classmethod
    def start(cls, snapshot, initial_state=TASK_STATE_PLANNING, detail=""):
        now = _history_timestamp()
        task_id = str(snapshot.task_id or snapshot.run_id)
        return cls(
            task_id=task_id,
            project_root=str(snapshot.project_root),
            request_summary=_history_bound_text(snapshot.request_text),
            state_transitions=((
                _history_bound_text(initial_state, 64),
                _history_bound_text(detail),
                now,
            ),),
            outcome=_history_bound_text(initial_state, 64),
            created_at=now,
            updated_at=now,
            session_id=snapshot.session_id or task_id,
            parent_task_id=snapshot.parent_task_id,
            parent_session_id=snapshot.parent_session_id,
        ).sanitized()

    @property
    def plan(self):
        if not self.plan_summary and not self.plan_steps:
            return None
        return ExecutionPlan(self.plan_summary, self.plan_steps)

    def sanitized(self):
        safe_task_id = _history_bound_text(self.task_id, 128)
        safe_session_id = _history_lineage_id(self.session_id, fallback=safe_task_id)
        if safe_session_id is None:
            safe_session_id = _history_lineage_id(safe_task_id, allow_empty=True) or "legacy-session"
        safe_parent_task_id = _history_lineage_id(
            self.parent_task_id,
            allow_empty=True,
            limit=SESSION_PARENT_MAX_CHARS,
        )
        safe_parent_session_id = _history_lineage_id(
            self.parent_session_id,
            allow_empty=True,
            limit=SESSION_PARENT_MAX_CHARS,
        )
        if safe_parent_task_id is None or safe_parent_session_id is None or bool(safe_parent_task_id) != bool(safe_parent_session_id):
            safe_parent_task_id = ""
            safe_parent_session_id = ""
        steps = []
        for step in self.plan_steps[:PLAN_MAX_STEPS]:
            if isinstance(step, PlanStep):
                steps.append(
                    PlanStep(
                        _history_bound_text(step.id, 64),
                        _history_bound_text(step.title, PLAN_MAX_FIELD_CHARS),
                        _history_bound_text(step.detail, PLAN_MAX_FIELD_CHARS),
                    )
                )
        transitions = []
        for transition in self.state_transitions[-HISTORY_MAX_TRANSITIONS:]:
            if isinstance(transition, (tuple, list)) and len(transition) >= 3:
                transitions.append(
                    (
                        _history_bound_text(transition[0], 64),
                        _history_bound_text(transition[1]),
                        _history_bound_text(transition[2], 80),
                    )
                )
        reasons = []
        for reason in self.reasons[-HISTORY_MAX_REASONS:]:
            safe_reason = _history_bound_text(reason)
            if safe_reason and safe_reason not in reasons:
                reasons.append(safe_reason)
        return replace(
            self,
            task_id=safe_task_id,
            project_root=_history_bound_text(self.project_root, HISTORY_MAX_PATH_CHARS),
            request_summary=_history_bound_text(self.request_summary),
            plan_summary=_history_bound_text(self.plan_summary, PLAN_MAX_FIELD_CHARS),
            plan_steps=tuple(steps),
            selected_model=_history_bound_text(self.selected_model, 240),
            state_transitions=tuple(transitions),
            reasons=tuple(reasons),
            outcome=_history_bound_text(self.outcome, 64),
            created_at=_history_bound_text(self.created_at, 80),
            updated_at=_history_bound_text(self.updated_at, 80),
            session_id=safe_session_id,
            parent_task_id=safe_parent_task_id,
            parent_session_id=safe_parent_session_id,
        )

    def to_dict(self):
        record = self.sanitized()
        return {
            "task_id": record.task_id,
            "session_id": record.session_id,
            "parent_task_id": record.parent_task_id,
            "parent_session_id": record.parent_session_id,
            "project_root": record.project_root,
            "request_summary": record.request_summary,
            "plan_summary": record.plan_summary,
            "plan_steps": [
                {"id": step.id, "title": step.title, "detail": step.detail}
                for step in record.plan_steps
            ],
            "selected_model": record.selected_model,
            "state_transitions": [
                {"state": state, "detail": detail, "timestamp": timestamp}
                for state, detail, timestamp in record.state_transitions
            ],
            "reasons": list(record.reasons),
            "outcome": record.outcome,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return None
        task_id = str(value.get("task_id", "") or "").strip()
        project_root = str(value.get("project_root", "") or "").strip()
        if not task_id or not project_root:
            return None
        raw_session_id = value.get("session_id")
        session_id = _history_lineage_id(
            task_id if raw_session_id is None else raw_session_id,
            fallback=task_id,
        )
        parent_task_id = _history_lineage_id(
            value.get("parent_task_id", ""),
            allow_empty=True,
            limit=SESSION_PARENT_MAX_CHARS,
        )
        parent_session_id = _history_lineage_id(
            value.get("parent_session_id", ""),
            allow_empty=True,
            limit=SESSION_PARENT_MAX_CHARS,
        )
        if session_id is None or parent_task_id is None or parent_session_id is None:
            return None
        if bool(parent_task_id) != bool(parent_session_id):
            return None
        raw_steps = value.get("plan_steps", ())
        steps = []
        if isinstance(raw_steps, list):
            for item in raw_steps[:PLAN_MAX_STEPS]:
                if not isinstance(item, dict):
                    continue
                step_id = str(item.get("id", "") or "").strip()
                title = str(item.get("title", "") or "").strip()
                detail = str(item.get("detail", "") or "").strip()
                if step_id and title and detail:
                    steps.append(PlanStep(step_id, title, detail))
        raw_transitions = value.get("state_transitions", ())
        transitions = []
        if isinstance(raw_transitions, list):
            for item in raw_transitions[-HISTORY_MAX_TRANSITIONS:]:
                if not isinstance(item, dict):
                    continue
                state = str(item.get("state", "") or "").strip()
                detail = str(item.get("detail", "") or "").strip()
                timestamp = str(item.get("timestamp", "") or "").strip()
                if state and timestamp:
                    transitions.append((state, detail, timestamp))
        raw_reasons = value.get("reasons", ())
        reasons = []
        if isinstance(raw_reasons, list):
            reasons = [str(item) for item in raw_reasons[-HISTORY_MAX_REASONS:] if item]
        return cls(
            task_id=task_id,
            project_root=project_root,
            request_summary=str(value.get("request_summary", "") or ""),
            plan_summary=str(value.get("plan_summary", "") or ""),
            plan_steps=tuple(steps),
            selected_model=str(value.get("selected_model", "") or ""),
            state_transitions=tuple(transitions),
            reasons=tuple(reasons),
            outcome=str(value.get("outcome", "") or ""),
            created_at=str(value.get("created_at", "") or ""),
            updated_at=str(value.get("updated_at", "") or ""),
            session_id=session_id,
            parent_task_id=parent_task_id,
            parent_session_id=parent_session_id,
        ).sanitized()


class HistoryStore:
    """Fail-closed, bounded, atomic JSON storage for safe task metadata."""

    def __init__(self, path=None, max_records=HISTORY_MAX_RECORDS, max_bytes=HISTORY_MAX_BYTES):
        self.path = Path(path) if path is not None else default_history_path()
        self.max_records = max(1, int(max_records))
        self.max_bytes = max(1, int(max_bytes))

    def load(self):
        try:
            if not self.path.exists() or not self.path.is_file():
                return []
            if self.path.stat().st_size > self.max_bytes:
                return []
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            raw_records = payload.get("records") if isinstance(payload, dict) else None
            if not isinstance(raw_records, list):
                return []
            records = []
            for item in raw_records:
                record = HistoryRecord.from_dict(item)
                if record is not None:
                    records.append(record)
            return records[-self.max_records:]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []

    def _encoded(self, records):
        payload = {
            "version": 1,
            "records": [record.sanitized().to_dict() for record in records],
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def save(self, records):
        normalized = [record.sanitized() for record in records if isinstance(record, HistoryRecord)]
        normalized = normalized[-self.max_records:]
        while normalized:
            encoded = self._encoded(normalized)
            if len(encoded) <= self.max_bytes:
                break
            normalized.pop(0)
        else:
            encoded = self._encoded([])
            if len(encoded) > self.max_bytes:
                return False
        temporary_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary_path), str(self.path))
            temporary_path = None
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def append(self, record):
        if not isinstance(record, HistoryRecord):
            return False
        return self.save(self.load() + [record])

    def upsert(self, record):
        if not isinstance(record, HistoryRecord):
            return False
        records = [item for item in self.load() if item.task_id != record.task_id]
        records.append(record)
        return self.save(records)

    def get(self, task_id):
        target = str(task_id or "")
        for record in self.load():
            if record.task_id == target:
                return record
        return None


def history_project_root_status(record):
    """Return only filesystem availability for a historical project root."""
    if not isinstance(record, HistoryRecord) or not record.project_root:
        return "unavailable"
    try:
        return "available" if Path(record.project_root).is_dir() else "unavailable"
    except OSError:
        return "unavailable"


def history_record_label(record):
    """Build a short newest-first list label from safe metadata only."""
    if not isinstance(record, HistoryRecord):
        return "Unavailable history record"
    safe = record.sanitized()
    timestamp = (safe.updated_at or safe.created_at or "unknown")[:19].replace("T", " ")
    outcome = safe.outcome or "in progress"
    task_id = safe.task_id[:24]
    return f"{timestamp}  {outcome}  {task_id}"


def format_history_record(record):
    """Format a bounded, metadata-only history inspection view."""
    if not isinstance(record, HistoryRecord):
        return "No history record selected."
    safe = record.sanitized()
    lines = [
        f"Task id: {safe.task_id}",
        f"Session id: {safe.session_id}",
        f"Parent task: {safe.parent_task_id or '(none)'}",
        f"Parent session: {safe.parent_session_id or '(none)'}",
        f"Updated: {safe.updated_at or safe.created_at or 'unknown'}",
        f"Project root: {safe.project_root}",
        f"Root status: {history_project_root_status(safe)}",
        f"Request: {safe.request_summary or '(none)'}",
        f"Plan: {safe.plan_summary or '(none)'}",
    ]
    if safe.plan_steps:
        lines.append("Plan steps:")
        for step in safe.plan_steps[:HISTORY_BROWSER_MAX_STEPS]:
            lines.append(f"  {step.id}. {step.title} — {step.detail}")
    else:
        lines.append("Plan steps: (none)")
    lines.append(f"Selected model: {safe.selected_model or '(none)'}")
    lines.append(f"Outcome: {safe.outcome or '(in progress)'}")
    lines.append("Transitions:")
    if safe.state_transitions:
        for state, detail, timestamp in safe.state_transitions[-HISTORY_BROWSER_MAX_TRANSITIONS:]:
            suffix = f" — {detail}" if detail else ""
            lines.append(f"  {timestamp}  {state}{suffix}")
    else:
        lines.append("  (none)")
    lines.append("Reasons:")
    if safe.reasons:
        for reason in safe.reasons[-HISTORY_BROWSER_MAX_REASONS:]:
            lines.append(f"  - {reason}")
    else:
        lines.append("  (none)")
    return redact_sensitive_text("\n".join(lines))
