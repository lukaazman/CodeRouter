import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class TaskReportPayloadTests(unittest.TestCase):
    def make_snapshot(self, root):
        return wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="export-run",
            task_id="export-task",
            request_text="Summarize the bounded task. STREAM_RESPONSE_SECRET",
        )

    def make_handoff(self, snapshot):
        return wrapper.build_evidence_handoff(
            snapshot,
            plan=wrapper.ExecutionPlan(
                "Bounded report plan",
                (wrapper.PlanStep("1", "Inspect metadata", "Review safe task state only"),),
            ),
            changed_paths=[wrapper.make_handoff_path_metadata("src/app.py", 4, 2)],
            task_state=wrapper.TASK_STATE_APPLIED,
            outcome=wrapper.TASK_STATE_APPLIED,
            model_statuses=["selected: qwen/qwen3-coder:free"],
            model_health_statuses=["latency 12ms · success"],
            fallback_statuses=["static fallback retained"],
            blockers=["Bearer sk-or-v1-123456789"],
            acceptance_evidence=["diff --git PRIVATE_FILE_CONTENT"],
            run_sequence=19,
        )

    def test_allowlist_redaction_and_no_raw_material(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = self.make_snapshot(root)
            handoff = self.make_handoff(snapshot)
            payload = wrapper.build_task_report_payload(
                snapshot=snapshot,
                handoff=handoff,
                transitions=[
                    ("review", "raw output PRIVATE_FILE_CONTENT", "2026-08-25T00:00:00Z"),
                    ("applied", "done", "2026-08-25T00:01:00Z"),
                ],
                verification_metadata={
                    "status": "timeout",
                    "command_identity": "python · 1 args",
                    "error": "Authorization: Bearer raw-token-value",
                    "result_output_present": True,
                    "result_output_bytes": 999999,
                },
                undo_file_count=2,
            )
            encoded = wrapper.serialize_task_report(payload).decode("utf-8")
            self.assertEqual(
                set(payload),
                {
                    "schema",
                    "exported_at",
                    "task",
                    "changes",
                    "model",
                    "verification",
                    "overseer",
                    "evidence",
                    "undo",
                    "counts",
                },
            )
            self.assertIn("src/app.py", encoded)
            self.assertNotIn("PRIVATE_FILE_CONTENT", encoded)
            self.assertNotIn("diff --git", encoded)
            self.assertNotIn("STREAM_RESPONSE_SECRET", encoded)
            self.assertNotIn("raw-token-value", encoded)
            self.assertNotIn("original_bytes", encoded)
            self.assertNotIn("before", encoded)
            self.assertLessEqual(len(encoded.encode("utf-8")), wrapper.REPORT_MAX_BYTES)
            self.assertLessEqual(len(encoded.splitlines()), wrapper.REPORT_MAX_LINES)
            self.assertEqual(payload["verification"]["output_bytes"], wrapper.VERIFICATION_RESULT_MAX_OUTPUT_BYTES)

    def test_caps_are_applied_before_serialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = self.make_snapshot(root)
            handoff = self.make_handoff(snapshot)
            payload = wrapper.build_task_report_payload(
                snapshot=snapshot,
                handoff=handoff,
                transitions=[
                    (f"state-{index}", f"detail-{index}", f"timestamp-{index}")
                    for index in range(wrapper.REPORT_MAX_RECORDS * 3)
                ],
            )
            self.assertLessEqual(len(payload["task"]["transitions"]), wrapper.REPORT_MAX_RECORDS)
            self.assertLessEqual(len(payload["model"]["selection"]), wrapper.REPORT_MAX_RECORDS)
            self.assertLessEqual(len(wrapper.serialize_task_report(payload)), wrapper.REPORT_MAX_BYTES + 1)

    def test_destination_is_outside_project_root_and_parent_must_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(ValueError):
                wrapper.validate_task_report_destination(root / "report.json", project_root=root)
            with self.assertRaises(ValueError):
                wrapper.validate_task_report_destination(
                    root.parent / "missing-parent" / "report.json",
                    project_root=root,
                )

    def test_atomic_failure_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            target = directory / "report.json"
            target.write_text("old report", encoding="utf-8")
            payload = {"schema": "coderouter.task_report.v1", "task": {"state": "review"}}
            with mock.patch.object(wrapper.os, "replace", side_effect=OSError("replace denied")):
                self.assertFalse(wrapper.write_task_report_atomic(payload, target))
            self.assertEqual(target.read_text(encoding="utf-8"), "old report")
            self.assertEqual(list(directory.glob(".report.json.*.tmp")), [])


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class TaskReportUiTests(unittest.TestCase):
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
        self.app = wrapper.CodeAgentApp(history_path=Path(self.temp_dir.name) / "history.json")
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def activate_terminal(self, root, state=wrapper.TASK_STATE_REVIEW):
        root = Path(root)
        snapshot = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="ui-export-run",
            task_id="ui-export-task",
            request_text="Export metadata only.",
        )
        self.app.selected_folder.set(str(root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app._handoff_snapshot = snapshot
        self.app._handoff_created_at = wrapper._history_timestamp()
        self.app._handoff_stale = False
        self.app._handoff_evidence_events = []
        self.app.set_task_state(state, "terminal test state")
        self.app._update_lifecycle_controls()
        return snapshot

    def test_visible_export_is_explicit_and_has_no_execution_side_effects(self):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(project_dir)
            output = Path(output_dir) / "task-report.json"
            self.activate_terminal(root)
            self.assertEqual(str(self.app.export_report_button.cget("state")), tk.NORMAL)
            with (
                mock.patch.object(wrapper.filedialog, "asksaveasfilename", return_value=str(output)),
                mock.patch.object(wrapper.messagebox, "askyesno", return_value=True),
                mock.patch.object(wrapper.threading, "Thread") as thread,
                mock.patch.object(self.app, "apply_pending") as apply,
                mock.patch.object(self.app, "run_verification") as verify,
            ):
                self.assertTrue(self.app.export_report())
            thread.assert_not_called()
            apply.assert_not_called()
            verify.assert_not_called()
            self.assertTrue(output.is_file())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "coderouter.task_report.v1")
            self.assertIsNone(self.app.pending_proposal)

    def test_stale_closed_and_project_root_guards_refuse_without_dialog_or_write(self):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(project_dir)
            output = Path(output_dir) / "task-report.json"
            self.activate_terminal(root)
            self.app._invalidate_handoff("stale test")
            with mock.patch.object(wrapper.filedialog, "asksaveasfilename") as dialog:
                self.assertFalse(self.app.export_report())
            dialog.assert_not_called()
            self.activate_terminal(root, state=wrapper.TASK_STATE_APPLIED)
            inside = root / "report.json"
            with (
                mock.patch.object(wrapper.filedialog, "asksaveasfilename", return_value=str(inside)),
                mock.patch.object(wrapper.messagebox, "askyesno") as confirm,
            ):
                self.assertFalse(self.app.export_report())
            confirm.assert_not_called()
            self.assertFalse(inside.exists())
            self.app.on_close()
            with mock.patch.object(wrapper.filedialog, "asksaveasfilename") as dialog:
                self.assertFalse(self.app.export_report())
            dialog.assert_not_called()
            self.assertFalse(output.exists())

    def test_declined_confirmation_does_not_write_or_change_task_state(self):
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as output_dir:
            root = Path(project_dir)
            output = Path(output_dir) / "task-report.json"
            self.activate_terminal(root)
            state_before = self.app.task_state
            with (
                mock.patch.object(wrapper.filedialog, "asksaveasfilename", return_value=str(output)),
                mock.patch.object(wrapper.messagebox, "askyesno", return_value=False),
            ):
                self.assertFalse(self.app.export_report())
            self.assertEqual(self.app.task_state, state_before)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
