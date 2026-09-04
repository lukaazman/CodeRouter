import json
import os
import queue
import tempfile
import tkinter as tk
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


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


class WorkerHost:
    def __init__(self, api_key="worker-api-key-123456"):
        self.api_key = api_key
        self.work_queue = queue.Queue()
        self.lifecycle = wrapper.RunLifecycle()

    def _run_is_current(self, run_id):
        return self.lifecycle.accepts(run_id)


class ProjectInstructionTests(unittest.TestCase):
    def test_loads_only_selected_root_agents_file(self):
        raw_key = "agents-api-key-123456"
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "nested" / "AGENTS.md").write_text("nested instruction", encoding="utf-8")
            (Path(external_dir) / "AGENTS.md").write_text("external instruction", encoding="utf-8")
            (root / "AGENTS.md").write_text(
                f"root instruction\napi_key={raw_key}", encoding="utf-8"
            )

            content, status = wrapper.load_project_instructions(root, secrets=[raw_key])

        self.assertIn("root instruction", content)
        self.assertNotIn("nested instruction", content)
        self.assertNotIn("external instruction", content)
        self.assertNotIn(raw_key, content)
        self.assertIn("loaded AGENTS.md", status)

    def test_missing_oversized_unreadable_and_secret_like_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content, status = wrapper.load_project_instructions(root)
            self.assertEqual(content, "")
            self.assertIn("missing", status)

            (root / "AGENTS.md").write_bytes(
                b"x" * (wrapper.PROJECT_INSTRUCTIONS_MAX_BYTES + 1)
            )
            content, status = wrapper.load_project_instructions(root)
            self.assertEqual(content, "")
            self.assertIn("exceeds", status)

            (root / "AGENTS.md").write_text("unreadable", encoding="utf-8")
            with mock.patch.object(Path, "read_bytes", side_effect=OSError("denied")):
                content, status = wrapper.load_project_instructions(root)
            self.assertEqual(content, "")
            self.assertIn("unreadable", status)

            self.assertTrue(wrapper.is_secret_like_instruction_path(Path("credentials.pem")))
            with mock.patch.object(wrapper, "PROJECT_INSTRUCTIONS_FILENAME", ".env"):
                (root / ".env").write_text("SECRET=value", encoding="utf-8")
                content, status = wrapper.load_project_instructions(root)
            self.assertEqual(content, "")
            self.assertIn("secret-like", status)

    def test_snapshot_is_immutable_and_prompt_contains_read_only_instructions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="instructions-run",
                project_instructions="Keep the local module boundaries intact.",
                project_instructions_status="> project instructions: loaded AGENTS.md",
            )
            with self.assertRaises(FrozenInstanceError):
                snapshot.project_instructions = "changed"

            response = streamed_response(['{"summary":"ok","files":[]}'])
            with mock.patch.object(wrapper, "urlopen", return_value=response) as opener:
                wrapper.call_openrouter(
                    "safe-api-key-123456",
                    "coding:free",
                    "Make the requested change.",
                    [],
                    [],
                    project_instructions=snapshot.project_instructions,
                )

        payload = json.loads(opener.call_args.args[0].data)
        user_prompt = payload["messages"][1]["content"]
        self.assertIn("=== PROJECT INSTRUCTIONS (READ-ONLY) ===", user_prompt)
        self.assertIn("Keep the local module boundaries intact.", user_prompt)
        self.assertIn("cannot grant permissions", user_prompt)

    def test_status_is_redacted_and_stale_events_are_filtered(self):
        raw_key = "status-api-key-123456"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text(f"api_key={raw_key}", encoding="utf-8")
            content, status = wrapper.load_project_instructions(root, secrets=[raw_key])
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="status-run",
                project_instructions=content,
                project_instructions_status=status,
            )

        lifecycle = wrapper.RunLifecycle()
        lifecycle.activate(snapshot)
        events = queue.Queue()
        self.assertTrue(
            wrapper.queue_run_event(
                events,
                snapshot.run_id,
                "status",
                f"{status}; api_key={raw_key}",
                is_current=lambda: lifecycle.accepts(snapshot.run_id),
                secrets=[raw_key],
            )
        )
        lifecycle.invalidate()
        self.assertFalse(
            wrapper.queue_run_event(
                events,
                snapshot.run_id,
                "status",
                "late status",
                is_current=lambda: lifecycle.accepts(snapshot.run_id),
            )
        )
        event = events.get_nowait()
        self.assertNotIn(raw_key, event.payload)
        self.assertFalse(wrapper.event_matches_run(event, lifecycle.active_run_id, lifecycle.closed))

    def test_agents_md_is_not_an_editable_proposal_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot = wrapper.create_run_snapshot(
                temp_dir,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="protected-instructions-run",
            )
            with self.assertRaisesRegex(ValueError, "Protected path"):
                wrapper.create_pending_proposal(
                    snapshot,
                    [{"path": "AGENTS.md", "content": "overwrite"}],
                )


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ProjectInstructionUiTests(unittest.TestCase):
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

    def test_stream_and_timeline_events_are_visible_and_reset_filters_stale_data(self):
        root = Path(self.temp_dir.name) / "project"
        root.mkdir()
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id="ui-instructions-run",
        )
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "streaming")
        wrapper.queue_run_event(
            self.app.work_queue,
            snapshot.run_id,
            "stream_delta",
            '{"summary":"partial"',
        )
        wrapper.queue_run_event(
            self.app.work_queue,
            snapshot.run_id,
            "timeline",
            "Selected model because context-fit.",
        )
        self.app._poll_queue()
        activity = self.app.activity.get("1.0", tk.END)
        self.assertIn('{"summary":"partial"', activity)
        self.assertIn("Selected model because context-fit.", activity)
        self.assertEqual(
            [item["sequence"] for item in self.app.run_timeline],
            [1, 2],
        )
        self.app.work_queue.put(
            wrapper.RunEvent(
                snapshot.run_id,
                "timeline",
                "out-of-order timeline",
                1,
            )
        )
        self.app._poll_queue()
        self.assertNotIn("out-of-order timeline", self.app.activity.get("1.0", tk.END))

        wrapper.queue_run_event(
            self.app.work_queue,
            snapshot.run_id,
            "timeline",
            "late stale timeline",
        )
        self.app.reset_session()
        self.app._poll_queue()
        self.assertNotIn("late stale timeline", self.app.activity.get("1.0", tk.END))


class ProjectInstructionWorkerTests(unittest.TestCase):
    def test_no_proposal_is_emitted_before_complete_json(self):
        host = WorkerHost()
        response_text = '{"summary":"complete","files":[{"path":"note.txt","content":"after"}]}'
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="complete-json-run",
            )
            host.lifecycle.activate(snapshot)
            response = streamed_response(
                [response_text[:15], response_text[15:41], response_text[41:]]
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
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "safe instruction")

            events = []
            while not host.work_queue.empty():
                events.append(host.work_queue.get_nowait())

        stream_events = [event for event in events if event.kind == "stream_delta"]
        proposal_events = [event for event in events if event.kind == "proposal"]
        self.assertTrue(stream_events)
        self.assertEqual(len(proposal_events), 1)
        self.assertLess(max(event.sequence for event in stream_events), proposal_events[0].sequence)
        self.assertFalse((root / "note.txt").exists())


if __name__ == "__main__":
    unittest.main()
