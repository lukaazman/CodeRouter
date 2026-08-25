import os
import queue
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class InspectRoundWorkerTests(unittest.TestCase):
    class Host:
        def __init__(self, root, run_id, inspect_round):
            self.api_key = "worker-key-123456"
            self.work_queue = queue.Queue()
            self.lifecycle = wrapper.RunLifecycle()
            self.snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id=run_id,
                task_id="inspect-task",
                session_id="inspect-session",
                request_text="two-round inspect",
                inspect_round=inspect_round,
            )
            self.lifecycle.activate(self.snapshot)

        def _run_is_current(self, run_id):
            return self.lifecycle.accepts(run_id)

    @staticmethod
    def drain(host):
        events = []
        while not host.work_queue.empty():
            events.append(host.work_queue.get_nowait())
        return events

    def test_round_two_isolated_worker_and_third_response_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("bounded inspect content", encoding="utf-8")
            round_one = self.Host(root, "inspect-run-1", 1)
            request_one = wrapper.InspectRequest(
                "Read the selected file.",
                ("notes.txt",),
                round_one.snapshot.run_id,
                round=0,
            )
            request_two = wrapper.InspectRequest(
                "Read the selected file again.",
                ("notes.txt",),
            )
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(
                    wrapper,
                    "collect_inspect_files",
                    return_value=((), "Inspect context loaded: 0 file(s), 0 bytes."),
                ),
                mock.patch.object(
                    wrapper,
                    "call_openrouter_with_fallback",
                    return_value=(request_two, "safe:free"),
                ),
            ):
                wrapper.CodeAgentApp._run_agent_worker(
                    round_one,
                    round_one.snapshot,
                    "inspect round one",
                    request_one,
                    True,
                )
            first_events = self.drain(round_one)
            first_request_event = next(
                event for event in first_events if event.kind == "inspect_request"
            )
            self.assertEqual(first_request_event.payload.round, 1)
            self.assertEqual(first_request_event.run_id, round_one.snapshot.run_id)
            self.assertNotIn("proposal", [event.kind for event in first_events])

            round_two = self.Host(root, "inspect-run-2", 2)
            request_for_round_two = wrapper.InspectRequest(
                "Read the selected file again.",
                ("notes.txt",),
                round_two.snapshot.run_id,
                round=1,
            )
            third_request = wrapper.InspectRequest(
                "A third read must be rejected.",
                ("notes.txt",),
                round_two.snapshot.run_id,
            )
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(
                    wrapper,
                    "collect_inspect_files",
                    return_value=((), "Inspect context loaded: 0 file(s), 0 bytes."),
                ),
                mock.patch.object(
                    wrapper,
                    "call_openrouter_with_fallback",
                    return_value=(third_request, "safe:free"),
                ),
            ):
                wrapper.CodeAgentApp._run_agent_worker(
                    round_two,
                    round_two.snapshot,
                    "inspect round two",
                    request_for_round_two,
                    True,
                )
            second_events = self.drain(round_two)
            self.assertNotIn("inspect_request", [event.kind for event in second_events])
            self.assertNotIn("proposal", [event.kind for event in second_events])
            self.assertNotIn("diffs", [event.kind for event in second_events])
            self.assertTrue(
                any(
                    event.kind == "task_state"
                    and event.payload[0] == wrapper.TASK_STATE_ERROR
                    for event in second_events
                )
            )
            self.assertNotEqual(round_one.snapshot.run_id, round_two.snapshot.run_id)
            self.assertEqual(round_two.snapshot.inspect_parent_run_id, "")
            self.assertEqual(round_two.snapshot.inspect_round, 2)

    def test_inspect_request_round_and_collector_guards_are_bounded_redacted(self):
        with self.assertRaises(ValueError):
            wrapper.InspectRequest("read", ("notes.txt",), round=3)
        with self.assertRaises(ValueError):
            wrapper.InspectRequest("Authorization: Bearer raw-secret", ("notes.txt",), round=1)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.txt").write_text("token=raw-token-value", encoding="utf-8")
            (root / "b.txt").write_text("second file", encoding="utf-8")
            with self.assertRaises(ValueError):
                wrapper.resolve_inspect_target(root, "../outside.txt")
            files, status = wrapper.collect_inspect_files(
                root,
                ("a.txt", "b.txt"),
                max_files=1,
                max_file_bytes=64,
                max_total_bytes=64,
                secrets=("worker-key-123456",),
            )
            self.assertLessEqual(len(files), 1)
            self.assertLessEqual(
                sum(len(item.content.encode("utf-8")) for item in files),
                64,
            )
            content = "\n".join(item.content for item in files)
            self.assertNotIn("raw-token-value", content)
            self.assertNotIn("../outside.txt", status)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class InspectRoundUiTests(unittest.TestCase):
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
        self.app = wrapper.CodeAgentApp(
            history_path=Path(self.temp_dir.name) / "history.json"
        )
        self.app.withdraw()
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def activate(self, run_id, inspect_round=0):
        snapshot = wrapper.create_run_snapshot(
            self.root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            task_id="ui-inspect-task",
            session_id="ui-inspect-session",
            request_text="two-round inspect UI task",
            inspect_round=inspect_round,
        )
        self.app.selected_folder.set(str(self.root))
        self.app._activate_run(snapshot)
        self.app.run_snapshot = snapshot
        self.app._handoff_snapshot = snapshot
        self.app._handoff_stale = False
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "Inspect permission required")
        return snapshot

    def pending(self, snapshot, round_number):
        request = wrapper.InspectRequest(
            f"Read round {round_number + 1} safely.",
            ("notes.txt",),
            snapshot.run_id,
            round=round_number,
        )
        self.app.inspect_request = request
        self.app._write_inspect_preview(request)
        self.app._update_lifecycle_controls()
        return request

    def test_two_allows_create_fresh_runs_and_preserve_session_ledger(self):
        first = self.activate("ui-inspect-1", inspect_round=0)
        self.pending(first, 0)
        started = []

        def fake_start(snapshot, target, args):
            started.append((snapshot, args[2]))
            return object()

        with mock.patch.object(self.app, "_start_run_worker", side_effect=fake_start):
            self.assertTrue(self.app.allow_inspect())
            second = self.app.lifecycle.active_snapshot
            self.assertNotEqual(first.run_id, second.run_id)
            self.assertEqual(second.inspect_round, 1)
            self.assertEqual(second.inspect_parent_run_id, first.run_id)
            self.assertEqual(second.task_id, first.task_id)
            self.assertEqual(second.session_id, first.session_id)
            self.assertEqual(started[0][1].run_id, second.run_id)
            self.assertEqual(started[0][1].round, 0)

            self.pending(second, 1)
            self.assertTrue(self.app.allow_inspect())
            third = self.app.lifecycle.active_snapshot
            self.assertNotEqual(second.run_id, third.run_id)
            self.assertEqual(third.inspect_round, 2)
            self.assertEqual(third.inspect_parent_run_id, second.run_id)
            self.assertEqual(started[1][1].run_id, third.run_id)
            self.assertEqual(started[1][1].round, 1)

        self.assertEqual(len(started), 2)
        self.assertEqual(
            [record.category for record in self.app.permission_ledger.records],
            ["inspect", "inspect"],
        )
        self.assertEqual(
            [record.decision for record in self.app.permission_ledger.records],
            ["allow", "allow"],
        )
        self.assertIsNone(self.app.pending_proposal)
        self.assertEqual(self.app.pending_edits, [])

    def test_stale_and_third_queue_events_are_ignored_without_next_worker(self):
        current = self.activate("ui-inspect-current", inspect_round=2)
        old = wrapper.create_run_snapshot(
            self.root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id="ui-inspect-old",
            task_id=current.task_id,
            session_id=current.session_id,
            request_text="stale inspect",
            inspect_round=1,
        )
        with (
            mock.patch.object(self.app, "_start_run_worker") as starter,
            mock.patch.object(wrapper, "collect_inspect_files") as collector,
            mock.patch.object(wrapper, "call_openrouter_with_fallback") as provider,
        ):
            wrapper.queue_run_event(
                self.app.work_queue,
                old.run_id,
                "inspect_request",
                wrapper.InspectRequest("stale", ("notes.txt",), old.run_id, round=1),
            )
            self.app._poll_queue()
            self.assertIsNone(self.app.inspect_request)

            wrapper.queue_run_event(
                self.app.work_queue,
                current.run_id,
                "inspect_request",
                wrapper.InspectRequest("third", ("notes.txt",), current.run_id, round=2),
            )
            self.app._poll_queue()
            self.assertIsNone(self.app.inspect_request)
            starter.assert_not_called()
            collector.assert_not_called()
            provider.assert_not_called()
        self.assertIsNone(self.app.pending_proposal)
        self.assertEqual(self.app.pending_edits, [])

    def test_cancel_reset_folder_and_close_clear_round_two_without_write(self):
        first = self.activate("ui-inspect-cancel", inspect_round=1)
        self.pending(first, 1)
        with mock.patch.object(self.app, "_start_run_worker") as starter:
            self.assertTrue(self.app.cancel_inspect())
            starter.assert_not_called()
        self.assertIsNone(self.app.inspect_request)
        self.assertIsNone(self.app.pending_proposal)

        reset_snapshot = self.activate("ui-inspect-reset", inspect_round=1)
        self.pending(reset_snapshot, 1)
        self.app.reset_session()
        self.assertIsNone(self.app.inspect_request)
        self.assertFalse(self.app.allow_inspect())

        folder_snapshot = self.activate("ui-inspect-folder", inspect_round=1)
        self.pending(folder_snapshot, 1)
        other_root = Path(self.temp_dir.name) / "other"
        other_root.mkdir()
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Inspect permission required")
        with mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(other_root)):
            self.app.choose_folder()
        self.assertIsNone(self.app.inspect_request)
        self.assertFalse(self.app.allow_inspect())

        close_snapshot = self.activate("ui-inspect-close", inspect_round=1)
        self.pending(close_snapshot, 1)
        self.app.on_close()
        self.assertIsNone(self.app.inspect_request)
        self.assertFalse(self.app.allow_inspect())
        self.assertIsNone(self.app.pending_proposal)


if __name__ == "__main__":
    unittest.main()
