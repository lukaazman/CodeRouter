import json
import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class DeterministicClock:
    def __init__(self, *values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


def free_record(model_id, context_length=4096, coding=True):
    return {
        "id": model_id,
        "pricing": {"prompt": "0", "completion": "0"},
        "context_length": context_length,
        "coding_signals": ["coding"] if coding else [],
    }


def valid_edit_response():
    return '{"summary":"ok","files":[]}'


def valid_plan_response():
    return json.dumps(
        {
            "summary": "Keep the change bounded.",
            "steps": [
                {"id": "1", "title": "Inspect", "detail": "Preserve existing guards."},
            ],
        }
    )


class ModelHealthTrackerTests(unittest.TestCase):
    def test_tracker_records_bounded_redacted_metadata_and_cancel_status(self):
        raw_key = "health-api-key-123456"
        raw_bearer = "health-bearer-123456"
        tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(0.0, 0.75))
        started = tracker.begin()
        record = tracker.finish(
            "coder/example:free",
            started,
            wrapper.MODEL_HEALTH_SUCCESS,
            f"api_key={raw_key} Authorization: Bearer {raw_bearer}",
            secrets=[raw_key, raw_bearer],
        )
        self.assertEqual(record.latency_ms, 750)
        self.assertEqual(record.status, wrapper.MODEL_HEALTH_SUCCESS)
        self.assertNotIn(raw_key, record.reason)
        self.assertNotIn(raw_bearer, record.reason)

        cancelled = tracker.record(
            "cancelled:free",
            wrapper.MODEL_HEALTH_MAX_LATENCY_MS * 10,
            wrapper.MODEL_HEALTH_CANCELLED,
            "run cancelled",
        )
        self.assertEqual(cancelled.status, wrapper.MODEL_HEALTH_CANCELLED)
        self.assertEqual(cancelled.latency_ms, wrapper.MODEL_HEALTH_MAX_LATENCY_MS)
        self.assertEqual(len(tracker.records), 2)

    def test_discovery_health_is_timed_and_emitted_without_raw_errors(self):
        raw_key = "discovery-api-key-123456"
        tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(10.0, 10.25))
        events = queue.Queue()
        queue_candidates, note = wrapper.build_free_model_queue(
            raw_key,
            discovery_fn=lambda _api_key: [free_record("discovered:free")],
            static_models=[],
            health_tracker=tracker,
            log_queue=events,
            run_id="discovery-run",
            event_is_current=lambda: True,
        )
        self.assertEqual([str(item) for item in queue_candidates], ["discovered:free"])
        self.assertIsNone(note)
        self.assertEqual(tracker.records[0].model_id, wrapper.MODEL_HEALTH_DISCOVERY_ID)
        self.assertEqual(tracker.records[0].latency_ms, 250)
        event = events.get_nowait()
        self.assertEqual(event.kind, "model_health")
        self.assertIn("success", event.payload)
        self.assertNotIn(raw_key, event.payload)

        failure_tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(20.0, 20.5))
        failure_events = queue.Queue()
        with mock.patch.object(
            wrapper,
            "discover_free_models",
            side_effect=RuntimeError(f"Authorization: Bearer {raw_key}"),
        ):
            fallback, note = wrapper.build_free_model_queue(
                raw_key,
                discovery_fn=wrapper.discover_free_models,
                static_models=["known:free"],
                health_tracker=failure_tracker,
                log_queue=failure_events,
                run_id="discovery-failure-run",
                event_is_current=lambda: True,
            )
        self.assertEqual([str(item) for item in fallback], ["known:free"])
        self.assertIn("discovery failed", note)
        self.assertEqual(failure_tracker.records[0].status, wrapper.MODEL_HEALTH_FAILURE)
        self.assertNotIn(raw_key, failure_tracker.records[0].reason)
        self.assertNotIn(raw_key, failure_events.get_nowait().payload)

    def test_health_is_tie_breaker_after_existing_selector_preferences(self):
        tracker = wrapper.ModelHealthTracker()
        tracker.record("zeta:free", 300, wrapper.MODEL_HEALTH_FAILURE, "provider failed")
        tracker.record("alpha:free", 90, wrapper.MODEL_HEALTH_SUCCESS, "response parsed")
        candidates = [free_record("zeta:free"), free_record("alpha:free")]
        selected, reason = wrapper.select_free_model_candidate(
            candidates,
            task_context_tokens=512,
            health_tracker=tracker,
        )
        self.assertEqual(selected.model_id, "alpha:free")
        self.assertIn("health-success-90ms", reason)

    def test_health_never_makes_ineligible_models_eligible(self):
        tracker = wrapper.ModelHealthTracker()
        tracker.record("paid/model", 1, wrapper.MODEL_HEALTH_SUCCESS, "good")
        tracker.record("small:free", 1, wrapper.MODEL_HEALTH_SUCCESS, "good")
        candidates = [
            {"id": "paid/model", "pricing": {"prompt": "1", "completion": "1"}, "context_length": 8192},
            free_record("small:free", context_length=32),
        ]
        selected, reason = wrapper.select_free_model_candidate(
            candidates,
            task_context_tokens=512,
            health_tracker=tracker,
        )
        self.assertIsNone(selected)
        self.assertIn("no eligible", reason)

    def test_health_does_not_reorder_static_known_free_fallbacks(self):
        tracker = wrapper.ModelHealthTracker()
        tracker.record("second:free", 1, wrapper.MODEL_HEALTH_SUCCESS, "fast")
        tracker.record("first:free", 100, wrapper.MODEL_HEALTH_FAILURE, "failed")
        ranked = wrapper.rank_free_model_candidates(
            ["first:free", "second:free"],
            default_source=wrapper.MODEL_SOURCE_STATIC,
            health_tracker=tracker,
        )
        self.assertEqual([candidate.model_id for candidate in ranked], ["first:free", "second:free"])

    def test_edit_attempts_record_failure_then_success_and_emit_health_events(self):
        tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(0.0, 0.1, 1.0, 1.2))
        events = queue.Queue()
        calls = []

        def provider(_api_key, model, *_args, **_kwargs):
            calls.append(model)
            if len(calls) == 1:
                raise RuntimeError("provider unavailable")
            return valid_edit_response()

        with mock.patch.object(wrapper, "call_openrouter", side_effect=provider):
            result, model = wrapper.call_openrouter_with_fallback(
                "safe-key-123456",
                "request",
                [],
                [],
                events,
                "attempt-run",
                model_queue=["first:free", "second:free"],
                health_tracker=tracker,
            )
        self.assertEqual(result["files"], [])
        self.assertEqual(model, "second:free")
        self.assertEqual(calls, ["first:free", "second:free"])
        self.assertEqual(
            [(record.model_id, record.status, record.latency_ms) for record in tracker.records],
            [
                ("first:free", wrapper.MODEL_HEALTH_FAILURE, 100),
                ("second:free", wrapper.MODEL_HEALTH_SUCCESS, 200),
            ],
        )
        health_events = [event for event in list(events.queue) if event.kind == "model_health"]
        self.assertEqual(len(health_events), 2)
        self.assertTrue(all(event.run_id == "attempt-run" for event in health_events))

    def test_plan_attempt_uses_same_health_boundary_without_edit_events(self):
        tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(5.0, 5.4))
        events = queue.Queue()
        with mock.patch.object(wrapper, "call_openrouter_plan", return_value=valid_plan_response()):
            plan, model = wrapper.call_openrouter_plan_with_fallback(
                "safe-key-123456",
                "request",
                [],
                [],
                events,
                "plan-health-run",
                model_queue=["planner:free"],
                health_tracker=tracker,
            )
        self.assertEqual(plan.steps[0].id, "1")
        self.assertEqual(model, "planner:free")
        self.assertEqual(tracker.records[0].status, wrapper.MODEL_HEALTH_SUCCESS)
        self.assertEqual(tracker.records[0].reason, "plan response parsed")
        self.assertNotIn("proposal", [event.kind for event in list(events.queue)])

    def test_cancellation_after_first_failure_records_no_failure_and_no_second_attempt(self):
        tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(0.0, 0.5))
        events = queue.Queue()
        active = {"value": True}
        calls = []

        def provider(_api_key, model, *_args, **_kwargs):
            calls.append(model)
            active["value"] = False
            raise RuntimeError("first provider failure")

        with mock.patch.object(wrapper, "call_openrouter", side_effect=provider):
            with self.assertRaises(wrapper.RunCancelledError):
                wrapper.call_openrouter_with_fallback(
                    "safe-key-123456",
                    "request",
                    [],
                    [],
                    events,
                    "cancel-health-run",
                    event_is_current=lambda: active["value"],
                    model_queue=["first:free", "second:free"],
                    health_tracker=tracker,
                )
        self.assertEqual(calls, ["first:free"])
        self.assertEqual(tracker.records, ())
        self.assertFalse(any(event.kind == "model_health" for event in list(events.queue)))
        self.assertFalse(any(event.kind == "fallback" for event in list(events.queue)))

    def test_stale_discovery_does_not_update_health_or_emit_event(self):
        tracker = wrapper.ModelHealthTracker(clock=DeterministicClock(0.0, 1.0))
        events = queue.Queue()
        active = {"value": True}

        def discovery(_api_key):
            active["value"] = False
            return [free_record("late:free")]

        with self.assertRaises(wrapper.RunCancelledError):
            wrapper.build_free_model_queue(
                "safe-key-123456",
                discovery_fn=discovery,
                static_models=["known:free"],
                health_tracker=tracker,
                log_queue=events,
                run_id="stale-discovery-run",
                event_is_current=lambda: active["value"],
            )
        self.assertEqual(tracker.records, ())
        self.assertTrue(events.empty())


class ModelHealthUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_path = wrapper.CONFIG_PATH
        wrapper.CONFIG_PATH = Path(self.temp_dir.name) / "local_config.json"
        self.app = wrapper.CodeAgentApp(history_path=Path(self.temp_dir.name) / "history.json")
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def test_health_event_is_visible_but_stale_reset_and_close_events_are_ignored(self):
        with tempfile.TemporaryDirectory() as project_dir:
            snapshot = wrapper.create_run_snapshot(
                project_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="health-ui-run",
            )
            self.app.lifecycle.activate(snapshot)
            self.app.run_snapshot = snapshot
            wrapper.queue_run_event(
                self.app.work_queue,
                snapshot.run_id,
                "model_health",
                "coder:free: success 12ms (response parsed)",
            )
            self.app._poll_queue()
            self.assertIn("success 12ms", self.app.activity.get("1.0", tk.END))
            self.assertEqual(self.app.run_timeline[-1]["kind"], "model_health")

            late_run_id = snapshot.run_id
            wrapper.queue_run_event(self.app.work_queue, late_run_id, "model_health", "late reset")
            self.app.reset_session()
            self.app._poll_queue()
            self.assertNotIn("late reset", self.app.activity.get("1.0", tk.END))

            close_snapshot = wrapper.create_run_snapshot(
                project_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="health-close-run",
            )
            self.app.lifecycle.activate(close_snapshot)
            self.app.run_snapshot = close_snapshot
            wrapper.queue_run_event(self.app.work_queue, close_snapshot.run_id, "model_health", "late close")
            self.app.on_close()
            self.assertTrue(self.app.lifecycle.closed)


if __name__ == "__main__":
    unittest.main()
