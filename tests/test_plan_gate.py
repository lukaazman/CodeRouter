import json
import os
import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class ChunkedResponse:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return next(self.chunks, b"")


def sse_event(content):
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def streamed_response(content_parts):
    body = b"".join(sse_event(part) for part in content_parts) + b"data: [DONE]\n\n"
    return ChunkedResponse([body])


def valid_plan_text():
    return json.dumps(
        {
            "summary": "Implement the bounded change safely.",
            "steps": [
                {
                    "id": "1",
                    "title": "Inspect the current boundary",
                    "detail": "Confirm the existing guard and preserve unrelated behavior.",
                },
                {
                    "id": "2",
                    "title": "Apply the smallest implementation",
                    "detail": "Change only the requested files and keep review before writes.",
                },
            ],
        }
    )


class WorkerHost:
    def __init__(self, api_key="plan-api-key-123456"):
        self.api_key = api_key
        self.work_queue = queue.Queue()
        self.lifecycle = wrapper.RunLifecycle()

    def _run_is_current(self, run_id):
        return self.lifecycle.accepts(run_id)


class PlanParserTests(unittest.TestCase):
    def test_valid_plan_parsing_and_strict_shape(self):
        plan = wrapper.parse_plan_response(valid_plan_text())
        self.assertIsInstance(plan, wrapper.ExecutionPlan)
        self.assertEqual(plan.summary, "Implement the bounded change safely.")
        self.assertEqual([step.id for step in plan.steps], ["1", "2"])

        with self.assertRaisesRegex(ValueError, "only summary and steps"):
            wrapper.parse_plan_response(
                json.dumps({"summary": "bad", "steps": [], "files": []})
            )

    def test_malformed_empty_and_secret_bearing_plans_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            wrapper.parse_plan_response("")
        with self.assertRaisesRegex(ValueError, "Malformed"):
            wrapper.parse_plan_response("{not-json}")

        raw_key = "raw-plan-api-key-123456"
        secret_output = json.dumps(
            {
                "summary": f"api_key={raw_key}",
                "steps": [
                    {"id": "1", "title": "No write", "detail": "Do not write files."}
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "credential-shaped") as raised:
            wrapper.parse_plan_response(secret_output, secrets=[raw_key])
        self.assertNotIn(raw_key, str(raised.exception))


class PlanWorkerTests(unittest.TestCase):
    def drain(self, work_queue):
        events = []
        while not work_queue.empty():
            events.append(work_queue.get_nowait())
        return events

    def test_plan_streams_without_proposal_diff_auto_apply_or_writes(self):
        host = WorkerHost()
        response_text = valid_plan_text()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_AUTO,
                run_id="plan-worker-run",
                request_text="Make a bounded change.",
            )
            host.lifecycle.activate(snapshot)
            response = streamed_response(
                [response_text[:20], response_text[20:57], response_text[57:]]
            )
            with (
                mock.patch.object(wrapper, "choose_context_limits", return_value=(1, 1)),
                mock.patch.object(wrapper, "collect_files", return_value=[]),
                mock.patch.object(wrapper, "collect_extra_context_files", return_value=[]),
                mock.patch.object(
                    wrapper,
                    "build_free_model_queue",
                    return_value=(["coding:free"], None),
                ),
                mock.patch.object(wrapper, "urlopen", return_value=response),
            ):
                wrapper.CodeAgentApp._run_plan_worker(host, snapshot, snapshot.request_text)

            events = self.drain(host.work_queue)

        kinds = [event.kind for event in events]
        self.assertIn("stream_delta", kinds)
        self.assertIn("plan", kinds)
        self.assertIn(wrapper.TASK_STATE_PLAN, [event.payload[0] for event in events if event.kind == "task_state"])
        self.assertNotIn("proposal", kinds)
        self.assertNotIn("diffs", kinds)
        self.assertNotIn("files", kinds)
        self.assertNotIn("auto_apply", kinds)
        self.assertFalse((root / "note.txt").exists())
        plan_event = next(event for event in events if event.kind == "plan")
        self.assertIsInstance(plan_event.payload, wrapper.ExecutionPlan)
        self.assertEqual(
            "".join(event.payload for event in events if event.kind == "stream_delta"),
            response_text,
        )

    def test_cancellation_after_plan_provider_return_emits_no_plan(self):
        host = WorkerHost()
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = wrapper.create_run_snapshot(
                temp_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="cancel-plan-run",
            )
            host.lifecycle.activate(snapshot)
            active = {"value": True}

            def provider(*_args, **_kwargs):
                active["value"] = False
                return valid_plan_text()

            with mock.patch.object(wrapper, "call_openrouter_plan", side_effect=provider) as mocked:
                with self.assertRaises(wrapper.RunCancelledError):
                    wrapper.call_openrouter_plan_with_fallback(
                        "safe-key-123456",
                        "request",
                        [],
                        [],
                        host.work_queue,
                        snapshot.run_id,
                        event_is_current=lambda: active["value"] and host._run_is_current(snapshot.run_id),
                        model_queue=["coding:free", "second:free"],
                    )

        mocked.assert_called_once()
        events = self.drain(host.work_queue)
        self.assertFalse(any(event.kind == "plan" for event in events))
        self.assertFalse(any(event.kind == "fallback" for event in events))

    def test_plan_queue_payload_redacts_credential_shaped_text(self):
        raw_key = "raw-plan-queue-key-123456"
        plan = wrapper.ExecutionPlan(
            summary=f"api_key={raw_key}",
            steps=(
                wrapper.PlanStep("1", "Bearer raw-plan-bearer-123456", "safe detail"),
            ),
        )
        events = queue.Queue()
        wrapper.queue_run_event(
            events,
            "redact-plan-run",
            "plan",
            plan,
            secrets=[raw_key],
        )
        payload = events.get_nowait().payload
        self.assertNotIn(raw_key, payload.summary)
        self.assertNotIn("raw-plan-bearer-123456", payload.steps[0].title)
        self.assertIn("[redacted]", payload.summary)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class PlanUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_path = wrapper.CONFIG_PATH
        wrapper.CONFIG_PATH = Path(self.temp_dir.name) / "local_config.json"
        self.app = wrapper.CodeAgentApp()
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def snapshot(self, root, run_id="plan-ui-run"):
        return wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="Make the requested change.",
            project_instructions="Keep the change local.",
        )

    def activate_plan(self, root, run_id="plan-ui-run"):
        snapshot = self.snapshot(root, run_id)
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app.set_task_state(wrapper.TASK_STATE_PLAN, "Approve plan")
        plan = wrapper.parse_plan_response(valid_plan_text())
        self.app._set_pending_plan(plan, snapshot.run_id)
        return snapshot, plan

    def test_plan_is_displayed_and_approval_actions_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _snapshot, plan = self.activate_plan(Path(temp_dir))
            self.app._poll_queue()
            displayed = self.app.plan_preview.get("1.0", tk.END)
            self.assertIn(plan.steps[0].title, displayed)
            self.assertEqual(str(self.app.approve_plan_button.cget("state")), tk.NORMAL)
            self.assertEqual(str(self.app.revise_plan_button.cget("state")), tk.NORMAL)
            self.assertEqual(str(self.app.cancel_plan_button.cget("state")), tk.NORMAL)
            self.assertIsNone(self.app.pending_proposal)
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_PLAN)

    def test_approved_plan_creates_next_snapshot_and_is_in_edit_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot, plan = self.activate_plan(root, run_id="approval-source-run")
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.app.approve_plan()

            next_snapshot = self.app.run_snapshot
            self.assertNotEqual(next_snapshot.run_id, snapshot.run_id)
            self.assertEqual(next_snapshot.approved_plan, plan)
            self.assertEqual(next_snapshot.request_text, snapshot.request_text)
            self.assertTrue(self.app.lifecycle.accepts(next_snapshot.run_id))
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_COLLECTING)
            thread_class.assert_called_once()

            response = streamed_response(['{"summary":"ok","files":[]}'])
            with mock.patch.object(wrapper, "urlopen", return_value=response) as opener:
                wrapper.call_openrouter(
                    "safe-api-key-123456",
                    "coding:free",
                    next_snapshot.request_text,
                    [],
                    [],
                    project_instructions=next_snapshot.project_instructions,
                    approved_plan=next_snapshot.approved_plan,
                )
            payload = json.loads(opener.call_args.args[0].data)
            prompt = payload["messages"][1]["content"]
            self.assertIn("APPROVED PLAN (READ-ONLY EXECUTION CONTEXT)", prompt)
            self.assertIn(plan.steps[0].title, prompt)

    def test_reset_folder_and_close_invalidate_pending_plan_events(self):
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_root = Path(first_dir)
            second_root = Path(second_dir)

            reset_snapshot, _plan = self.activate_plan(first_root, "reset-plan-run")
            wrapper.queue_run_event(self.app.work_queue, reset_snapshot.run_id, "plan", "late plan")
            self.app.reset_session()
            self.app._poll_queue()
            self.assertIsNone(self.app.pending_plan)
            self.assertFalse(self.app.lifecycle.accepts(reset_snapshot.run_id))

            folder_snapshot, _plan = self.activate_plan(first_root, "folder-plan-run")
            with mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(second_root)):
                self.app.choose_folder()
            self.assertIsNone(self.app.pending_plan)
            self.assertFalse(self.app.lifecycle.accepts(folder_snapshot.run_id))
            self.assertEqual(Path(self.app.selected_folder.get()).resolve(), second_root.resolve())

            close_snapshot, _plan = self.activate_plan(second_root, "close-plan-run")
            wrapper.queue_run_event(self.app.work_queue, close_snapshot.run_id, "plan", "late close plan")
            self.app.on_close()
            self.assertTrue(self.app.lifecycle.closed)
            self.assertIsNone(self.app.pending_plan)

    def test_revise_and_cancel_never_start_edit_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _snapshot, _plan = self.activate_plan(root, "revise-plan-run")
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.app.revise_plan()
            thread_class.assert_not_called()
            self.assertIsNone(self.app.pending_plan)
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_IDLE)

            _snapshot, _plan = self.activate_plan(root, "cancel-plan-run")
            with mock.patch.object(wrapper.threading, "Thread") as thread_class:
                self.app.cancel_plan()
            thread_class.assert_not_called()
            self.assertIsNone(self.app.pending_plan)
            self.assertEqual(self.app.task_state, wrapper.TASK_STATE_IDLE)


if __name__ == "__main__":
    unittest.main()
