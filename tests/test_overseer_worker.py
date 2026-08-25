import json
import os
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


def valid_overseer_response():
    return {
        "status": "approved",
        "summary": "Evidence is bounded and ready for inspection.",
        "next_step": {
            "title": "Review evidence",
            "detail": "Inspect the evidence and confirm the next prompt manually.",
            "scope": ["executor evidence"],
            "requires_user_confirmation": True,
        },
    }


class Response:
    def __init__(self, body):
        self.body = body
        self.closed = False

    def read(self, _size=-1):
        body, self.body = self.body, b""
        return body

    def close(self):
        self.closed = True


def sse_response(text):
    payload = {"choices": [{"delta": {"content": text}}]}
    body = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode("utf-8")
    return Response(body)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class OverseerWorkerUiTests(unittest.TestCase):
    def make_snapshot(self, root, run_id="executor-run"):
        return wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            task_id="executor-task",
            request_text="Inspect executor evidence.",
        )

    def make_app(self, temp_dir, adapter):
        app = wrapper.CodeAgentApp(
            history_path=Path(temp_dir) / "history.json",
            overseer_adapter=adapter,
        )
        snapshot = self.make_snapshot(Path(temp_dir))
        app._handoff_snapshot = snapshot
        app._handoff_created_at = "2026-01-01T00:00:00+00:00"
        app._handoff_stale = False
        app.task_state = wrapper.TASK_STATE_REVIEW
        app.run_timeline = []
        app._handoff_evidence_events = []
        return app, snapshot

    def test_terminal_gate_rejects_active_executor(self):
        called = []
        with tempfile.TemporaryDirectory() as temp_dir:
            app, snapshot = self.make_app(temp_dir, lambda _handoff: called.append(True) or valid_overseer_response())
            try:
                app.lifecycle.activate(snapshot)
                app.task_state = wrapper.TASK_STATE_RUNNING
                self.assertIsNone(app.send_handoff_to_overseer())
                self.assertEqual(called, [])
                self.assertIsNone(app.overseer_run_id)
            finally:
                app.destroy()

    def test_cross_run_verification_evidence_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app, snapshot = self.make_app(temp_dir, lambda _handoff: valid_overseer_response())
            try:
                app._capture_handoff_event("other-executor-run", 1, "verification_exit", "wrong run")
                app._capture_handoff_event(snapshot.run_id, 2, "verification_exit", "code 0")
                handoff = app._build_current_handoff()
                self.assertEqual(handoff.verification_statuses, ("code 0",))
            finally:
                app.destroy()

    def test_async_worker_is_metadata_only_and_events_are_run_scoped(self):
        calls = []
        worker_thread_ids = []

        def adapter(handoff):
            worker_thread_ids.append(threading.get_ident())
            calls.append(handoff.to_json())
            return valid_overseer_response()

        with tempfile.TemporaryDirectory() as temp_dir:
            app, _snapshot = self.make_app(temp_dir, adapter)
            try:
                handle = app.send_handoff_to_overseer()
                self.assertIsInstance(handle, wrapper.OverseerWorkerHandle)
                handle.worker.join(1.0)
                events = []
                while True:
                    try:
                        events.append(app.work_queue.get_nowait())
                    except queue.Empty:
                        break
                self.assertTrue(events)
                self.assertTrue(all(event.run_id == handle.run_id for event in events))
                self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))
                self.assertNotEqual(worker_thread_ids[0], threading.get_ident())
                self.assertNotIn("AGENTS.md", calls[0])
                self.assertNotIn("file contents", calls[0])
                self.assertNotIn("diff --git", calls[0])
                self.assertNotIn("stream text", calls[0])
                self.assertNotIn("api-key-secret-123456", calls[0])
                for event in events:
                    app.work_queue.put(event)
                self.assertEqual(handle.wait(1.0).status, "approved")
            finally:
                app.destroy()

    def test_cancelled_worker_has_no_final_review_and_cleans_owner(self):
        started = threading.Event()
        release = threading.Event()

        def adapter(_handoff):
            started.set()
            release.wait(1.0)
            return valid_overseer_response()

        with tempfile.TemporaryDirectory() as temp_dir:
            app, _snapshot = self.make_app(temp_dir, adapter)
            try:
                handle = app.send_handoff_to_overseer()
                self.assertTrue(started.wait(1.0))
                run_id = handle.run_id
                self.assertTrue(app.cancel_overseer())
                release.set()
                handle.worker.join(1.0)
                self.assertIsNone(app.overseer_review)
                self.assertIsNone(app.overseer_run_id)
                self.assertIsNone(app.run_resources.get(run_id))
            finally:
                release.set()
                app.destroy()

    def test_close_cancels_overseer_without_waiting_indefinitely(self):
        started = threading.Event()
        release = threading.Event()

        def adapter(_handoff):
            started.set()
            release.wait(2.0)
            return valid_overseer_response()

        with tempfile.TemporaryDirectory() as temp_dir:
            app, _snapshot = self.make_app(temp_dir, adapter)
            handle = app.send_handoff_to_overseer()
            self.assertTrue(started.wait(1.0))
            started_at = time.monotonic()
            app.on_close()
            self.assertLess(time.monotonic() - started_at, 1.0)
            release.set()
            handle.worker.join(1.0)


class OverseerProviderTests(unittest.TestCase):
    def make_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = wrapper.create_run_snapshot(
                temp_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="provider-executor",
                request_text="metadata-only request",
            )
            return wrapper.build_evidence_handoff(
                snapshot,
                task_state=wrapper.TASK_STATE_REVIEW,
                changed_paths=[{"path": "src/app.py", "additions": 2, "deletions": 1}],
                verification_statuses=["verification output observed (redacted)"],
            )

    def test_provider_request_is_metadata_only_and_response_is_closed(self):
        handoff = self.make_handoff()
        raw_response = sse_response(json.dumps(valid_overseer_response(), separators=(",", ":")))
        events = queue.Queue()
        owner = wrapper.RunResourceOwner("overseer-provider")
        raw_key = "provider-secret-api-key-123456"
        with mock.patch.object(wrapper, "urlopen", return_value=raw_response) as opener:
            response_text = wrapper.call_openrouter_overseer(
                raw_key,
                "free/provider",
                handoff,
                log_queue=events,
                run_id="overseer-provider",
                event_is_current=lambda: True,
                resource_owner=owner,
            )
        request_body = json.loads(opener.call_args.args[0].data)
        body_text = json.dumps(request_body)
        self.assertTrue(request_body["stream"])
        self.assertIn("EXECUTOR EVIDENCE", request_body["messages"][1]["content"])
        self.assertNotIn(raw_key, body_text)
        evidence_text = request_body["messages"][1]["content"]
        self.assertNotIn("file contents", evidence_text)
        self.assertNotIn("raw provider output", evidence_text)
        self.assertNotIn("diff --git", body_text)
        self.assertEqual(wrapper.parse_overseer_response(response_text).status, "approved")
        self.assertTrue(raw_response.closed)
        self.assertEqual(owner.response_handles, ())
        queued = []
        while not events.empty():
            queued.append(events.get_nowait())
        self.assertTrue(all(event.run_id == "overseer-provider" for event in queued))
        self.assertTrue(any(event.kind == "overseer_stream" for event in queued))

    def test_free_fallback_then_success_and_cancellation_before_second(self):
        records = [
            {"id": "a/free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "b/free", "pricing": {"prompt": "0", "completion": "0"}},
        ]
        model_queue = wrapper.order_free_model_queue(records, static_models=())
        handoff = self.make_handoff()
        events = queue.Queue()
        calls = []

        def provider(*args, **kwargs):
            calls.append(args[1])
            if len(calls) == 1:
                raise RuntimeError("temporary provider failure")
            return json.dumps(valid_overseer_response())

        with mock.patch.object(wrapper, "call_openrouter_overseer", side_effect=provider):
            review = wrapper.call_openrouter_overseer_with_fallback(
                "key-123456789",
                handoff,
                events,
                "overseer-fallback",
                event_is_current=lambda: True,
                model_queue=model_queue,
            )
        self.assertEqual(review.status, "approved")
        self.assertEqual(calls, ["a/free", "b/free"])

        active = {"value": True}
        calls.clear()

        def cancelling_provider(*args, **kwargs):
            calls.append(args[1])
            active["value"] = False
            raise RuntimeError("first failure")

        with mock.patch.object(wrapper, "call_openrouter_overseer", side_effect=cancelling_provider):
            with self.assertRaises(wrapper.RunCancelledError):
                wrapper.call_openrouter_overseer_with_fallback(
                    "key-123456789",
                    handoff,
                    queue.Queue(),
                    "overseer-cancel",
                    event_is_current=lambda: active["value"],
                    model_queue=model_queue,
                )
        self.assertEqual(calls, ["a/free"])


if __name__ == "__main__":
    unittest.main()
