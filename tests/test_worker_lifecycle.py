import json
import queue
import tempfile
import threading
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class ClosableResponse:
    def __init__(self, chunks=None, on_read=None):
        self.chunks = iter(chunks or [])
        self.on_read = on_read
        self.closed = False

    def read(self, _size=-1):
        if self.on_read is not None:
            self.on_read(self)
        if self.closed:
            raise OSError("response closed")
        return next(self.chunks, b"")

    def close(self):
        self.closed = True


class ResourceWorkerHost:
    def __init__(self):
        self.api_key = "worker-lifecycle-key-123456"
        self.work_queue = queue.Queue()
        self.lifecycle = wrapper.RunLifecycle()
        self.run_resources = wrapper.RunResourceRegistry()

    def _run_is_current(self, run_id):
        return self.lifecycle.accepts(run_id) and self.run_resources.is_current(run_id)

    def _finish_run_worker(self, run_id):
        self.run_resources.unregister_worker(run_id, threading.current_thread())


def make_snapshot(root, run_id="lifecycle-run"):
    return wrapper.create_run_snapshot(
        project_root=root,
        extra_context_paths=(),
        session_messages=(),
        apply_mode=wrapper.APPLY_MODE_REVIEW,
        run_id=run_id,
        request_text="Make a bounded lifecycle-safe change.",
    )


def sse_text(text):
    payload = {"choices": [{"delta": {"content": text}}]}
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8") + b"data: [DONE]\n\n"


class ResourceRegistryTests(unittest.TestCase):
    def test_active_response_is_closed_and_handles_are_released(self):
        registry = wrapper.RunResourceRegistry()
        owner = registry.create("response-run")
        response = ClosableResponse()
        self.assertTrue(registry.register_response("response-run", response))
        self.assertIn(response, owner.response_handles)

        self.assertTrue(registry.cancel("response-run"))
        self.assertTrue(response.closed)
        registry.unregister_response("response-run", response)
        self.assertEqual(registry.provider_response_handles, {})

    def test_provider_response_is_closed_on_success_and_cancel(self):
        registry = wrapper.RunResourceRegistry()
        owner = registry.create("provider-run")
        events = queue.Queue()
        response = ClosableResponse([sse_text('{"summary":"ok","files":[]}')])

        with mock.patch.object(wrapper, "urlopen", return_value=response):
            assembled = wrapper.call_openrouter(
                "safe-key-123456",
                "coding:free",
                "safe request",
                [],
                [],
                log_queue=events,
                run_id="provider-run",
                event_is_current=owner.is_current,
                resource_owner=owner,
            )
        self.assertEqual(assembled, '{"summary":"ok","files":[]}')
        self.assertTrue(response.closed)
        self.assertEqual(owner.response_handles, ())

        plan_owner = registry.create("plan-provider-run")
        plan_response = ClosableResponse(
            [sse_text('{"summary":"plan","steps":[{"id":"1","title":"Inspect","detail":"Check"}]}')]
        )
        with mock.patch.object(wrapper, "urlopen", return_value=plan_response):
            plan_text = wrapper.call_openrouter_plan(
                "safe-key-123456",
                "planning:free",
                "make a plan",
                [],
                [],
                log_queue=queue.Queue(),
                run_id="plan-provider-run",
                event_is_current=plan_owner.is_current,
                resource_owner=plan_owner,
            )
        self.assertIn('"steps"', plan_text)
        self.assertTrue(plan_response.closed)
        self.assertEqual(plan_owner.response_handles, ())

        cancel_owner = registry.create("cancel-provider-run")
        cancel_response = ClosableResponse(
            [sse_text('{"summary":"late","files":[]}')],
            on_read=lambda _response: cancel_owner.cancel(),
        )
        with mock.patch.object(wrapper, "urlopen", return_value=cancel_response):
            with self.assertRaises(wrapper.RunCancelledError):
                wrapper.call_openrouter(
                    "safe-key-123456",
                    "coding:free",
                    "safe request",
                    [],
                    [],
                    log_queue=queue.Queue(),
                    run_id="cancel-provider-run",
                    event_is_current=cancel_owner.is_current,
                    resource_owner=cancel_owner,
                )
        self.assertTrue(cancel_response.closed)


class WorkerCancellationTests(unittest.TestCase):
    def activate_host(self, host, root, run_id):
        snapshot = make_snapshot(root, run_id=run_id)
        host.lifecycle.activate(snapshot)
        owner = host.run_resources.create(run_id)
        host.run_resources.register_worker(run_id, threading.current_thread())
        return snapshot, owner

    def drain(self, work_queue):
        events = []
        while not work_queue.empty():
            events.append(work_queue.get_nowait())
        return events

    def worker_context(self, provider_result=None, build_error=None):
        build_patch = (
            mock.patch.object(wrapper, "build_free_model_queue", side_effect=build_error)
            if build_error is not None
            else mock.patch.object(wrapper, "build_free_model_queue", return_value=(['coding:free'], None))
        )
        patches = [
            mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
            mock.patch.object(wrapper, "collect_files", return_value=[]),
            mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
            build_patch,
            mock.patch.object(wrapper, "call_openrouter_with_fallback", return_value=provider_result or ({"summary": "none", "files": []}, "coding:free")),
        ]
        return patches

    def test_worker_success_failure_and_cancel_release_worker_handles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for mode in ("success", "failure", "cancel"):
                host = ResourceWorkerHost()
                snapshot, owner = self.activate_host(host, root, f"worker-{mode}")
                if mode == "cancel":
                    owner.cancel()
                    host.lifecycle.invalidate()
                    wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe request")
                else:
                    patches = self.worker_context(
                        build_error=RuntimeError("provider failed") if mode == "failure" else None,
                    )
                    with patches[0], patches[1], patches[2], patches[3], patches[4]:
                        wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe request")
                self.assertEqual(owner.worker_handles, ())

    def test_cancellation_after_provider_return_cannot_create_proposal_or_diff(self):
        host = ResourceWorkerHost()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot, owner = self.activate_host(host, root, "cancel-after-provider")

            def cancel_then_return(**_kwargs):
                owner.cancel()
                host.lifecycle.invalidate()
                return (
                    {"summary": "late", "files": [{"path": "note.txt", "content": "after"}]},
                    "coding:free",
                )

            with (
                mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
                mock.patch.object(wrapper, "collect_files", return_value=[]),
                mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
                mock.patch.object(wrapper, "build_free_model_queue", return_value=(["coding:free"], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", side_effect=cancel_then_return),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe request")

            events = self.drain(host.work_queue)
            self.assertFalse(any(event.kind in {"proposal", "diffs", "files", "auto_apply"} for event in events))
            self.assertFalse((root / "note.txt").exists())
            self.assertEqual(owner.worker_handles, ())

    def test_cancelled_run_events_are_rejected_after_invalidation(self):
        lifecycle = wrapper.RunLifecycle()
        registry = wrapper.RunResourceRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = make_snapshot(Path(temp_dir), "stale-resource-run")
            lifecycle.activate(snapshot)
            registry.create(snapshot.run_id)
            is_current = lambda: lifecycle.accepts(snapshot.run_id) and registry.is_current(snapshot.run_id)
            events = queue.Queue()
            self.assertTrue(wrapper.queue_run_event(events, snapshot.run_id, "log", "before", is_current=is_current))
            registry.cancel(snapshot.run_id)
            lifecycle.invalidate()
            self.assertFalse(wrapper.queue_run_event(events, snapshot.run_id, "proposal", "after", is_current=is_current))
            event = events.get_nowait()
            self.assertFalse(wrapper.event_matches_run(event, lifecycle.active_run_id, lifecycle.closed))
            self.assertTrue(events.empty())


class AppCancellationTests(unittest.TestCase):
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

    def activate_with_response(self, run_id, state=wrapper.TASK_STATE_PLANNING):
        root = Path(self.temp_dir.name)
        snapshot = make_snapshot(root, run_id)
        self.app._activate_run(snapshot)
        self.app.run_snapshot = snapshot
        self.app.set_task_state(state, "active")
        response = ClosableResponse()
        self.assertTrue(self.app.run_resources.register_response(run_id, response))
        return snapshot, response

    def test_reset_folder_and_plan_cancel_request_response_close(self):
        _snapshot, response = self.activate_with_response("reset-run")
        self.app.reset_session()
        self.assertTrue(response.closed)
        self.assertIsNone(self.app.lifecycle.active_run_id)

        _snapshot, response = self.activate_with_response("folder-run")
        new_root = Path(self.temp_dir.name) / "new-root"
        new_root.mkdir()
        with mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(new_root)):
            self.app.choose_folder()
        self.assertTrue(response.closed)
        self.assertIsNone(self.app.lifecycle.active_run_id)

        snapshot, response = self.activate_with_response("plan-cancel-run", wrapper.TASK_STATE_PLAN)
        plan = wrapper.ExecutionPlan("Inspect", (wrapper.PlanStep("1", "Inspect", "Check"),))
        self.app._set_pending_plan(plan, snapshot.run_id)
        self.app.cancel_plan()
        self.assertTrue(response.closed)
        self.assertIsNone(self.app.lifecycle.active_run_id)

    def test_close_is_bounded_and_cancels_without_join(self):
        _snapshot, response = self.activate_with_response("close-run")
        with mock.patch.object(wrapper.threading.Thread, "join", side_effect=AssertionError("unbounded join")):
            self.app.on_close()
        self.assertTrue(response.closed)
        self.assertTrue(self.app.lifecycle.closed)

    def test_init_update_destroy_smoke_is_bounded(self):
        self.app.update()
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_IDLE)
        self.app.on_close()
        self.assertTrue(self.app.lifecycle.closed)


if __name__ == "__main__":
    unittest.main()
