"""Per-model health telemetry used to rank free model candidates."""

import os
import threading
import time
from dataclasses import dataclass

from constants import (
    MODEL_HEALTH_CANCELLED,
    MODEL_HEALTH_DISCOVERY_ID,
    MODEL_HEALTH_FAILURE,
    MODEL_HEALTH_MAX_LATENCY_MS,
    MODEL_HEALTH_MAX_REASON_CHARS,
    MODEL_HEALTH_MAX_RECORDS,
    MODEL_HEALTH_STATUSES,
    MODEL_HEALTH_SUCCESS,
)
from redaction import redact_sensitive_text


def _health_bound_text(value, limit=MODEL_HEALTH_MAX_REASON_CHARS, secrets=None):
    redaction_secrets = list(secrets or ())
    redaction_secrets.append(os.environ.get("OPENROUTER_API_KEY", ""))
    safe = redact_sensitive_text(str(value or ""), redaction_secrets)
    compact = " ".join(safe.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


@dataclass(frozen=True)
class ModelHealthRecord:
    """In-memory metadata for one discovery or explicitly free-model attempt."""

    model_id: str
    latency_ms: int
    status: str
    reason: str

    def status_text(self):
        return f"{self.model_id}: {self.status} {self.latency_ms}ms ({self.reason})"


class ModelHealthTracker:
    """Thread-safe, bounded health telemetry with no persistence boundary."""

    def __init__(self, clock=None, max_records=MODEL_HEALTH_MAX_RECORDS):
        self._clock = clock or time.monotonic
        self.max_records = max(1, int(max_records))
        self._lock = threading.RLock()
        self._records = []

    @property
    def records(self):
        with self._lock:
            return tuple(self._records)

    @property
    def history(self):
        return self.records

    def now(self):
        return self._clock()

    def begin(self):
        return self.now()

    def begin_attempt(self):
        return self.begin()

    def _bounded_latency(self, latency_ms):
        try:
            value = float(latency_ms)
        except (TypeError, ValueError):
            value = 0.0
        return max(0, min(int(round(value)), MODEL_HEALTH_MAX_LATENCY_MS))

    def record(
        self,
        model_id,
        latency_ms,
        status,
        reason="",
        is_current=None,
        secrets=None,
    ):
        if is_current is not None and not is_current():
            return None
        normalized_status = str(status or "").casefold()
        if normalized_status not in MODEL_HEALTH_STATUSES:
            normalized_status = MODEL_HEALTH_FAILURE
        safe_model_id = _health_bound_text(model_id, 240, secrets=secrets)
        if not safe_model_id:
            safe_model_id = MODEL_HEALTH_DISCOVERY_ID
        record = ModelHealthRecord(
            model_id=safe_model_id,
            latency_ms=self._bounded_latency(latency_ms),
            status=normalized_status,
            reason=_health_bound_text(reason, secrets=secrets) or "unspecified",
        )
        with self._lock:
            if is_current is not None and not is_current():
                return None
            self._records.append(record)
            del self._records[:-self.max_records]
        return record

    def finish(
        self,
        model_id,
        started_at,
        status,
        reason="",
        is_current=None,
        secrets=None,
    ):
        if is_current is not None and not is_current():
            return None
        try:
            elapsed_ms = max(0.0, (self.now() - started_at) * 1000.0)
        except (TypeError, ValueError):
            elapsed_ms = 0.0
        return self.record(
            model_id=model_id,
            latency_ms=elapsed_ms,
            status=status,
            reason=reason,
            is_current=is_current,
            secrets=secrets,
        )

    def finish_attempt(self, model_id, started_at, status, reason="", is_current=None, secrets=None):
        return self.finish(model_id, started_at, status, reason, is_current, secrets)

    def record_attempt(self, model_id, started_at, status, reason="", is_current=None, secrets=None):
        return self.finish_attempt(model_id, started_at, status, reason, is_current, secrets)

    def record_discovery(self, started_at, status, reason="", is_current=None, secrets=None):
        return self.finish(
            MODEL_HEALTH_DISCOVERY_ID,
            started_at,
            status,
            reason,
            is_current=is_current,
            secrets=secrets,
        )

    def latest(self, model_id):
        target = str(model_id or "").casefold()
        with self._lock:
            for record in reversed(self._records):
                if record.model_id.casefold() == target:
                    return record
        return None

    def preference_key(self, model_id):
        record = self.latest(model_id)
        if record is None:
            return (1, MODEL_HEALTH_MAX_LATENCY_MS + 1)
        status_rank = {
            MODEL_HEALTH_SUCCESS: 0,
            MODEL_HEALTH_CANCELLED: 1,
            MODEL_HEALTH_FAILURE: 2,
        }.get(record.status, 1)
        latency = record.latency_ms if record.status == MODEL_HEALTH_SUCCESS else MODEL_HEALTH_MAX_LATENCY_MS + 1
        return status_rank, latency

    def selection_reason(self, model_id):
        record = self.latest(model_id)
        if record is None:
            return "health-unknown"
        return f"health-{record.status}-{record.latency_ms}ms"


# Short aliases keep the small telemetry layer discoverable for callers/tests.
HealthRecord = ModelHealthRecord
HealthTracker = ModelHealthTracker
