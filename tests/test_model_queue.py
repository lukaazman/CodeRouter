import json
import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class WorkerHost:
    def __init__(self):
        self.api_key = "test-key"
        self.work_queue = queue.Queue()

    def _run_is_current(self, run_id):
        return True


class ModelQueueTests(unittest.TestCase):
    def test_discovery_filters_paid_models_and_sends_no_project_data(self):
        payload = {
            "data": [
                {"id": "paid/model", "pricing": {"prompt": "0.000001", "completion": "0"}},
                {"id": "free/no-suffix", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "zeta:free"},
                {"id": "contradictory:free", "pricing": {"prompt": "0.1", "completion": "0"}},
                {"id": "missing/pricing"},
            ]
        }
        with mock.patch.object(wrapper, "urlopen", return_value=FakeResponse(payload)) as opener:
            models = wrapper.discover_free_models("test-key")

        request = opener.call_args.args[0]
        self.assertEqual(models, ["free/no-suffix", "zeta:free"])
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(opener.call_args.kwargs["timeout"], wrapper.MODEL_DISCOVERY_TIMEOUT_SECONDS)
        self.assertNotIn("project", request.full_url.lower())
        self.assertNotIn("prompt", request.full_url.lower())

    def test_ordering_is_deterministic_and_discovery_failure_keeps_static_queue(self):
        discovered = ["zeta:free", "paid/model", "alpha:free", "alpha:free"]
        ordered = wrapper.order_free_model_queue(discovered)
        self.assertEqual(ordered[:2], ["alpha:free", "zeta:free"])
        self.assertEqual(ordered[2:], wrapper.MODEL_FALLBACKS)
        self.assertEqual(
            wrapper.order_free_model_queue([], ["paid/model", "known:free"]),
            ["known:free"],
        )

        queue_candidates, note = wrapper.build_free_model_queue(
            "test-key",
            discovery_fn=mock.Mock(side_effect=TimeoutError("bounded timeout")),
        )
        self.assertEqual(queue_candidates, wrapper.MODEL_FALLBACKS)
        self.assertIn("discovery failed", note.lower())

    def test_first_free_candidate_failure_continues_to_second_candidate(self):
        events = queue.Queue()
        response = '{"summary":"ok","files":[]}'
        with mock.patch.object(
            wrapper,
            "call_openrouter",
            side_effect=[RuntimeError("transient provider failure"), response],
        ) as call:
            result, model = wrapper.call_openrouter_with_fallback(
                api_key="test-key",
                instructions="safe instruction",
                files=[],
                session_messages=[],
                log_queue=events,
                run_id="run-1",
                event_is_current=lambda: True,
                model_queue=["first:free", "second:free"],
            )

        self.assertEqual(model, "second:free")
        self.assertEqual(result["files"], [])
        self.assertEqual(
            [item.args[1] for item in call.call_args_list],
            ["first:free", "second:free"],
        )
        queued = []
        while not events.empty():
            queued.append(events.get_nowait())
        self.assertTrue(any(item[1] == "fallback" for item in queued))
        self.assertTrue(all(item[0] == "run-1" for item in queued))

    def test_paid_queue_candidate_is_never_called(self):
        events = queue.Queue()
        with mock.patch.object(wrapper, "call_openrouter") as call:
            with self.assertRaisesRegex(RuntimeError, "explicitly free"):
                wrapper.call_openrouter_with_fallback(
                    api_key="test-key",
                    instructions="safe instruction",
                    files=[],
                    session_messages=[],
                    log_queue=events,
                    run_id="run-paid",
                    model_queue=["paid/model"],
                )
        call.assert_not_called()
        self.assertTrue(events.empty())

    def test_invalidated_run_events_are_not_emitted_or_accepted(self):
        lifecycle = wrapper.RunLifecycle()
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = wrapper.create_run_snapshot(
                temp_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="stale-run",
            )
            lifecycle.activate(snapshot)
            events = queue.Queue()
            is_current = lambda: lifecycle.accepts(snapshot.run_id)
            self.assertTrue(wrapper.queue_run_event(events, snapshot.run_id, "log", "before", is_current=is_current))
            lifecycle.invalidate()
            self.assertFalse(wrapper.queue_run_event(events, snapshot.run_id, "log", "after", is_current=is_current))
            event = events.get_nowait()
            self.assertFalse(wrapper.event_matches_run(event, lifecycle.active_run_id, lifecycle.closed))
            self.assertTrue(events.empty())

    def test_worker_path_does_not_call_tk(self):
        host = WorkerHost()
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = wrapper.create_run_snapshot(
                Path(temp_dir),
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="worker-run",
            )
            with (
                mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
                mock.patch.object(wrapper, "collect_files", return_value=[]),
                mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
                mock.patch.object(wrapper, "build_free_model_queue", return_value=(["safe:free"], None)),
                mock.patch.object(
                    wrapper,
                    "call_openrouter_with_fallback",
                    return_value=({"summary": "no changes", "files": []}, "safe:free"),
                ),
                mock.patch.object(wrapper.tk, "Tk", side_effect=AssertionError("worker called Tk")),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe instruction")

        self.assertFalse(host.work_queue.empty())
        queued = []
        while not host.work_queue.empty():
            queued.append(host.work_queue.get_nowait())
        self.assertTrue(all(item[0] == "worker-run" for item in queued))


if __name__ == "__main__":
    unittest.main()
