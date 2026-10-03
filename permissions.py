"""Bounded, redacted ledger of permission decisions made during runs."""

import json
import re
import threading
from dataclasses import dataclass

from constants import (
    HANDOFF_MAX_COUNT,
    HANDOFF_MAX_TEXT_CHARS,
    LOCAL_COMMAND_MAX_RESULT_CHARS,
    PERMISSION_CATEGORIES,
    PERMISSION_DECISIONS,
    PERMISSION_LEDGER_MAX_BYTES,
    PERMISSION_LEDGER_MAX_FIELD_CHARS,
    PERMISSION_LEDGER_MAX_RECORDS,
    PERMISSION_POLICY_OUTCOMES,
)
from redaction import SECRET_PATTERN, redact_sensitive_text
from run_types import RunSnapshot


def _permission_safe_field(value, limit=PERMISSION_LEDGER_MAX_FIELD_CHARS):
    safe = redact_sensitive_text(str(value or ""))
    if SECRET_PATTERN.search(safe):
        return ""
    safe = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", safe)
    safe = " ".join(safe.split())
    encoded = safe.encode("utf-8", errors="replace")[:limit]
    return encoded.decode("utf-8", errors="ignore")


def _permission_safe_identifier(value, allow_empty=True):
    safe = _permission_safe_field(value, PERMISSION_LEDGER_MAX_FIELD_CHARS)
    if not safe and allow_empty:
        return ""
    if not safe or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", safe):
        return ""
    return safe


@dataclass(frozen=True)
class PermissionDecision:
    """Immutable metadata for one explicit, user-visible permission decision."""

    category: str
    decision: str
    run_id: str
    task_id: str = ""
    session_id: str = ""
    timestamp: str = ""
    sequence: int = 0
    policy_outcome: str = "not_applicable"

    def __post_init__(self):
        category = str(self.category or "").casefold().strip()
        decision = str(self.decision or "").casefold().strip()
        policy_outcome = str(self.policy_outcome or "not_applicable").casefold().strip()
        if category not in PERMISSION_CATEGORIES:
            raise ValueError("Unsupported permission decision category.")
        if decision not in PERMISSION_DECISIONS:
            raise ValueError("Unsupported permission decision label.")
        if policy_outcome not in PERMISSION_POLICY_OUTCOMES:
            raise ValueError("Unsupported permission policy outcome.")
        run_id = _permission_safe_identifier(self.run_id, allow_empty=False)
        task_id = _permission_safe_identifier(self.task_id)
        session_id = _permission_safe_identifier(self.session_id)
        if not run_id or (
            str(self.run_id or "").strip() != run_id
            or (self.task_id and str(self.task_id).strip() != task_id)
            or (self.session_id and str(self.session_id).strip() != session_id)
        ):
            raise ValueError("Permission decision identity is unsafe.")
        timestamp = _permission_safe_field(self.timestamp, 64) or "unknown"
        if self.timestamp and str(self.timestamp).strip() != timestamp:
            raise ValueError("Permission decision timestamp is unsafe.")
        try:
            sequence = min(max(int(self.sequence), 0), HANDOFF_MAX_COUNT)
        except (TypeError, ValueError, OverflowError):
            sequence = 0
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "policy_outcome", policy_outcome)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "sequence", sequence)

    def to_dict(self):
        return {
            "category": self.category,
            "decision": self.decision,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "sequence": self.sequence,
            "policy_outcome": self.policy_outcome,
        }

    def summary_text(self):
        policy = "" if self.policy_outcome == "not_applicable" else f"/{self.policy_outcome}"
        return _permission_safe_field(
            f"{self.category}:{self.decision}{policy}#{self.sequence}",
            PERMISSION_LEDGER_MAX_FIELD_CHARS,
        )

    def timeline_text(self):
        return _permission_safe_field(
            "permission decision: "
            f"category={self.category}; decision={self.decision}; "
            f"policy={self.policy_outcome}; task={self.task_id or '(none)'}; "
            f"session={self.session_id or '(none)'}; timestamp={self.timestamp}; "
            f"sequence={self.sequence}",
            HANDOFF_MAX_TEXT_CHARS,
        )


class PermissionDecisionLedger:
    """Bounded in-memory ledger; no command or material fields are accepted."""

    def __init__(self, max_records=PERMISSION_LEDGER_MAX_RECORDS, max_bytes=PERMISSION_LEDGER_MAX_BYTES):
        self.max_records = max(1, int(max_records))
        self.max_bytes = max(256, int(max_bytes))
        self._records = []
        self._active_run_id = None
        self._active_task_id = ""
        self._active_session_id = ""
        self._closed = False
        self._lock = threading.RLock()

    @property
    def records(self):
        with self._lock:
            return tuple(self._records)

    @property
    def active_run_id(self):
        return self._active_run_id

    @property
    def active_task_id(self):
        return self._active_task_id

    @property
    def active_session_id(self):
        return self._active_session_id

    @property
    def closed(self):
        return self._closed

    def bind_snapshot(self, snapshot, preserve=False):
        if not isinstance(snapshot, RunSnapshot):
            self.detach()
            return False
        try:
            run_id = _permission_safe_identifier(snapshot.run_id, allow_empty=False)
            task_id = _permission_safe_identifier(snapshot.task_id)
            session_id = _permission_safe_identifier(snapshot.session_id)
        except (TypeError, ValueError):
            self.detach()
            return False
        if not run_id:
            self.detach()
            return False
        with self._lock:
            preserve_records = bool(
                preserve
                and not self._closed
                and self._active_task_id
                and self._active_task_id == task_id
                and self._active_session_id == session_id
            )
            if not preserve_records:
                self._records = []
            self._active_run_id = run_id
            self._active_task_id = task_id
            self._active_session_id = session_id
            self._closed = False
        return True

    def detach(self):
        with self._lock:
            self._records = []
            self._active_run_id = None
            self._active_task_id = ""
            self._active_session_id = ""
            self._closed = False

    def close(self):
        with self._lock:
            self._records = []
            self._active_run_id = None
            self._active_task_id = ""
            self._active_session_id = ""
            self._closed = True

    clear = detach

    def append(self, record, is_current=None):
        if not isinstance(record, PermissionDecision):
            return None
        if is_current is not None:
            try:
                if not is_current():
                    return None
            except Exception:
                return None
        with self._lock:
            if self._closed or not self._active_run_id:
                return None
            if record.run_id != self._active_run_id:
                return None
            if self._active_task_id and record.task_id and record.task_id != self._active_task_id:
                return None
            if self._active_session_id and record.session_id and record.session_id != self._active_session_id:
                return None
            candidate = list(self._records) + [record]
            while len(candidate) > self.max_records:
                candidate.pop(0)
            while candidate:
                encoded = json.dumps(
                    [item.to_dict() for item in candidate],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                if len(encoded) <= self.max_bytes:
                    break
                if len(candidate) == 1:
                    return None
                candidate.pop(0)
            self._records = candidate
            return record

    def records_for(self, run_id=None):
        with self._lock:
            if run_id is None:
                return tuple(self._records)
            return tuple(item for item in self._records if item.run_id == str(run_id))

    def records_for_task(self, task_id=None):
        target = str(task_id or "")
        with self._lock:
            if not target:
                return tuple(self._records)
            return tuple(item for item in self._records if item.task_id == target)

    def summary_text(self, run_id=None):
        items = self.records_for(run_id)
        if not items:
            return "none"
        return _permission_safe_field(
            " | ".join(item.summary_text() for item in items[-6:]),
            LOCAL_COMMAND_MAX_RESULT_CHARS,
        )

    def to_json(self, run_id=None):
        encoded = json.dumps(
            [item.to_dict() for item in self.records_for(run_id)],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError("Permission decision ledger exceeds its bound.")
        return encoded
