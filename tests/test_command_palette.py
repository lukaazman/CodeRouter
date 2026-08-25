import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class LocalCommandParserTests(unittest.TestCase):
    def test_exact_commands_trim_only_outer_whitespace(self):
        for command in wrapper.LOCAL_COMMANDS:
            with self.subTest(command=command):
                self.assertEqual(wrapper.parse_local_command(f"  \t{command}\n "), command)

    def test_unknown_arguments_and_malformed_values_fail_closed(self):
        for value in (None, "", "status", "/STATUS", "/status now", "/model --json", "/review\nextra"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    wrapper.parse_local_command(value)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class LocalCommandPaletteUiTests(unittest.TestCase):
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
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()
        snapshot = wrapper.create_run_snapshot(
            project_root=self.root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="palette-run",
            task_id="palette-task",
            request_text="local status request",
        )
        self.app.selected_folder.set(str(self.root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app._handoff_snapshot = snapshot
        self.app._handoff_stale = False
        self.app._reset_run_timeline(snapshot.run_id)
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review ready")
        self.app._record_timeline_event(
            snapshot.run_id,
            1,
            "task_state",
            (wrapper.TASK_STATE_COLLECTING, "bounded collection"),
        )
        self.app._record_timeline_event(
            snapshot.run_id,
            2,
            "task_state",
            (wrapper.TASK_STATE_REVIEW, "Review ready"),
        )

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def test_visible_input_is_explicit_and_ctrl_k_focuses_without_submit(self):
        self.assertEqual(self.app.local_command.get(), "")
        self.assertIn("/status", self.app.local_command_result.get())
        self.assertTrue(self.app.local_command_entry.winfo_exists())
        self.assertTrue(self.app.local_command_submit_button.winfo_exists())
        with mock.patch.object(self.app.local_command_entry, "focus_set") as focus:
            self.assertEqual(self.app._on_local_command_shortcut(), "break")
        focus.assert_called_once_with()
        self.assertIn("/status", self.app.local_command_result.get())

    def test_each_command_is_local_bounded_redacted_and_read_only(self):
        secret = "sk-or-v1-command-palette-secret-123456"
        self.app.model_status.set(f"Authorization: Bearer {secret}")
        self.app.model_health.record("qwen/qwen3-coder:free", 17, wrapper.MODEL_HEALTH_SUCCESS, "ok")
        self.app.pending_edits = [{"path": "src/app.py"}]
        self.app.run_timeline.append(
            {
                "run_id": self.app.lifecycle.active_run_id,
                "sequence": 3,
                "kind": "stream_delta",
                "text": "RAW_STREAM_COMMAND_CONTENT",
            }
        )
        before_state = self.app.task_state
        before_messages = list(self.app.session_messages)
        with (
            mock.patch.object(wrapper.threading, "Thread") as thread,
            mock.patch.object(wrapper.subprocess, "Popen") as popen,
            mock.patch.object(self.app, "apply_pending") as apply,
            mock.patch.object(wrapper.HistoryStore, "upsert") as upsert,
        ):
            for command in wrapper.LOCAL_COMMANDS:
                self.assertTrue(self.app.submit_local_command(command))
                result = self.app.local_command_result.get()
                self.assertLessEqual(len(result), wrapper.LOCAL_COMMAND_MAX_RESULT_CHARS)
                self.assertNotIn(secret, result)
                self.assertNotIn("RAW_STREAM_COMMAND_CONTENT", result)
        self.assertEqual(self.app.task_state, before_state)
        self.assertEqual(self.app.session_messages, before_messages)
        thread.assert_not_called()
        popen.assert_not_called()
        apply.assert_not_called()
        upsert.assert_not_called()

        self.app.submit_local_command("/status")
        status = self.app.local_command_result.get()
        self.assertIn("REVIEW", status)
        self.assertIn("palette-run", status)
        self.assertIn("bounded collection", status)

        self.app.submit_local_command("/permissions")
        permissions = self.app.local_command_result.get()
        self.assertIn("apply_mode=review", permissions)
        self.assertIn("auto_apply=false", permissions)
        self.assertIn("commands=user action only", permissions)

    def test_unknown_command_does_not_execute_or_mutate(self):
        before = (self.app.task_state, list(self.app.session_messages))
        with (
            mock.patch.object(wrapper.threading, "Thread") as thread,
            mock.patch.object(wrapper.subprocess, "Popen") as popen,
        ):
            self.assertFalse(self.app.submit_local_command("/status extra"))
        self.assertIn("Rejected", self.app.local_command_result.get())
        self.assertEqual((self.app.task_state, list(self.app.session_messages)), before)
        thread.assert_not_called()
        popen.assert_not_called()

    def test_stale_and_closed_palette_refuse_safely(self):
        self.app._handoff_stale = True
        self.assertFalse(self.app.submit_local_command("/status"))
        self.assertIn("stale", self.app.local_command_result.get())

        self.app._handoff_stale = False
        self.app.on_close()
        self.assertFalse(self.app.submit_local_command("/review"))


if __name__ == "__main__":
    unittest.main()
