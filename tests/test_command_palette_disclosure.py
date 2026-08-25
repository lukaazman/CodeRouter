import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class CommandPaletteDisclosureUiTests(unittest.TestCase):
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
        snapshot = wrapper.create_run_snapshot(
            project_root=self.root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="command-disclosure-run",
            task_id="command-disclosure-task",
            request_text="command disclosure test",
        )
        self.app.selected_folder.set(str(self.root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app._handoff_snapshot = snapshot
        self.app._handoff_stale = False
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review ready")

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def test_collapsed_by_default_and_existing_widgets_are_preserved(self):
        self.assertFalse(self.app._local_command_expanded)
        self.assertEqual(self.app.local_command_detail.grid_info(), {})
        self.assertNotEqual(self.app.local_command_disclosure_button.grid_info(), {})
        for widget in (
            self.app.local_command_entry,
            self.app.local_command_submit_button,
            self.app.local_command_result_label,
        ):
            self.assertTrue(widget.winfo_exists())

    def test_click_and_keyboard_round_trip_preserves_detail_identity(self):
        detail = self.app.local_command_detail
        button = self.app.local_command_disclosure_button
        button.invoke()
        self.assertTrue(self.app._local_command_expanded)
        self.assertNotEqual(detail.grid_info(), {})
        button.invoke()
        self.assertFalse(self.app._local_command_expanded)
        self.assertEqual(detail.grid_info(), {})

        self.app.deiconify()
        try:
            self.app.update()
            self.app.focus_force()
            button.focus_set()
            self.app.update_idletasks()
            self.app.update()
            if self.app.focus_get() is not button:
                button.focus_force()
                self.app.update_idletasks()
                self.app.update()
            self.assertIs(self.app.focus_get(), button)
            button.event_generate("<Return>")
            self.app.update()
            self.assertTrue(self.app._local_command_expanded)
            button.event_generate("<space>")
            self.app.update()
            self.assertFalse(self.app._local_command_expanded)
        finally:
            self.app.withdraw()
        self.assertIs(detail, self.app.local_command_detail)

    def test_ctrl_k_expands_and_selects_without_submitting(self):
        self.app.local_command.set("/status")
        before_result = self.app.local_command_result.get()
        self.app.deiconify()
        try:
            self.app.update()
            self.app.focus_force()
            self.app.local_command_entry.focus_force()
            self.app.update_idletasks()
            self.app.update()
            with (
                mock.patch.object(self.app, "submit_local_command") as submit,
                mock.patch.object(
                    self.app.local_command_entry,
                    "selection_range",
                    wraps=self.app.local_command_entry.selection_range,
                ) as selection,
            ):
                self.assertEqual(self.app._on_local_command_shortcut(), "break")
                submit.assert_not_called()
            selection.assert_called_once_with(0, tk.END)
            self.app.update_idletasks()
            self.app.update()
            self.assertTrue(self.app._local_command_expanded)
            self.assertIs(self.app.focus_get(), self.app.local_command_entry)
            self.assertEqual(self.app.local_command_result.get(), before_result)
        finally:
            self.app.withdraw()

    def test_submissions_keep_detail_open_and_remain_bounded_redacted_read_only(self):
        secret = "sk-or-v1-command-disclosure-secret-123456"
        self.app.model_status.set(f"Authorization: Bearer {secret}")
        self.app.local_command.set("/status")
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
                self.assertTrue(self.app._local_command_expanded)
                result = self.app.local_command_result.get()
                self.assertLessEqual(len(result), wrapper.LOCAL_COMMAND_MAX_RESULT_CHARS)
                self.assertNotIn(secret, result)
        self.assertEqual(self.app.task_state, before_state)
        self.assertEqual(self.app.session_messages, before_messages)
        thread.assert_not_called()
        popen.assert_not_called()
        apply.assert_not_called()
        upsert.assert_not_called()

    def test_stale_and_closed_submissions_remain_fail_closed_without_execution(self):
        self.app._set_local_command_disclosure(False)
        self.app._handoff_stale = True
        with (
            mock.patch.object(wrapper.threading, "Thread") as thread,
            mock.patch.object(wrapper.subprocess, "Popen") as popen,
        ):
            self.assertFalse(self.app.submit_local_command("/status"))
            self.assertIn("stale", self.app.local_command_result.get())
            self.assertTrue(self.app._local_command_expanded)
            thread.assert_not_called()
            popen.assert_not_called()

        self.app._handoff_stale = False
        self.app.on_close()
        self.assertFalse(self.app.submit_local_command("/review"))


if __name__ == "__main__":
    unittest.main()
