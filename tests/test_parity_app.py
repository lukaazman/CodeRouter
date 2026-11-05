import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import CodeRouter as wrapper
from ui_test_helpers import build_hidden_app


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ParityAppTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.project = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CODEROUTER_DATA_DIR": self.data_dir.name})
        self.env.start()
        self.save = mock.patch.object(wrapper, "save_local_config")
        self.save.start()
        self.app = build_hidden_app(wrapper, history_path=Path(self.data_dir.name) / "history.json")
        self.app.selected_folder.set(self.project.name)

    def tearDown(self):
        try:
            self.app.on_close()
        except tk.TclError:
            pass
        self.save.stop()
        self.env.stop()
        self.project.cleanup()
        self.data_dir.cleanup()

    def test_help_and_unknown_commands(self):
        handled, ok, _message = self.app.run_slash_command("/help")
        self.assertTrue(handled and ok)
        self.assertIn("/compact", self.app.summary.get("1.0", tk.END))
        handled, ok, message = self.app.run_slash_command("/nope")
        self.assertTrue(handled)
        self.assertFalse(ok)
        self.assertIn("Unknown command", message)
        self.assertEqual(self.app.run_slash_command("plain text"), (False, False, ""))

    def test_command_field_routes_new_commands_but_keeps_legacy_strictness(self):
        self.assertTrue(self.app.submit_local_command("/approval full-auto"))
        self.assertEqual(self.app.approval_mode_value, "full-auto")
        self.assertEqual(self.app.apply_mode.get(), wrapper.APPLY_MODE_AUTO)
        self.assertFalse(self.app.submit_local_command("/status extra"))
        self.assertIn("Rejected", self.app.local_command_result.get())

    def test_approval_rules_and_settings_commands(self):
        self.assertTrue(self.app.run_slash_command("/allow Bash(pytest*)")[1])
        self.assertIn("Bash(pytest*)", self.app.approval_rules.allow)
        self.assertFalse(self.app.run_slash_command("/allow Write(x)")[1])
        self.assertTrue(self.app.run_slash_command("/style concise")[1])
        self.assertEqual(wrapper.GENERATION_SETTINGS["style"], "concise")
        self.assertFalse(self.app.run_slash_command("/temperature 3")[1])
        self.assertTrue(self.app.run_slash_command("/plan off")[1])
        self.assertFalse(self.app.plan_gate_enabled)
        self.app.run_slash_command("/style default")
        self.app.run_slash_command("/plan on")

    def test_composer_note_saves_memory_without_running(self):
        self.app._set_prompt_text("# always run pytest -q")
        with mock.patch.object(self.app, "_start_run_worker") as start:
            self.app.api_key = "sk-or-test"
            self.app.run_agent()
        start.assert_not_called()
        self.assertIn("- always run pytest -q", Path(self.project.name, "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "")

    def test_composer_slash_command_runs_locally(self):
        self.app.api_key = "sk-or-test"
        self.app._set_prompt_text("/cost")
        with mock.patch.object(self.app, "_start_run_worker") as start:
            self.app.run_agent()
        start.assert_not_called()
        self.assertIn("Session usage", self.app.summary.get("1.0", tk.END))

    def test_custom_command_expands_into_run(self):
        commands = Path(self.project.name, ".coderouter", "commands")
        commands.mkdir(parents=True)
        (commands / "fix.md").write_text("Fix the failing test in $ARGUMENTS", encoding="utf-8")
        self.app._on_project_changed(self.project.name)
        self.app.api_key = "sk-or-test"
        self.app._set_prompt_text("/fix tests/test_a.py")
        with mock.patch.object(self.app, "_start_run_worker") as start:
            self.app.run_agent()
        start.assert_called_once()
        snapshot = start.call_args[0][0]
        self.assertEqual(snapshot.request_text, "Fix the failing test in tests/test_a.py")

    def test_memory_files_join_project_instructions(self):
        Path(self.project.name, "CLAUDE.md").write_text("Prefer small diffs.", encoding="utf-8")
        self.app.api_key = "sk-or-test"
        self.app._set_prompt_text("Explain @README.md")
        with mock.patch.object(self.app, "_start_run_worker") as start:
            self.app.run_agent()
        snapshot = start.call_args[0][0]
        self.assertIn("Prefer small diffs.", snapshot.project_instructions)
        self.assertIn("README.md", start.call_args[0][2][1])

    def test_usage_status_strip_and_toast(self):
        self.app._record_usage({"model": "m:free", "prompt_tokens": 2000, "completion_tokens": 100, "context_window": 8000})
        self.assertEqual(self.app.status_usage_label.cget("text"), "2.1k tokens · 25% ctx · $0")
        self.app._toast("Saved", "success")
        self.assertTrue(self.app._toast_frame.winfo_manager())
        self.app._cycle_approval_mode()
        self.assertEqual(self.app.status_approval_label.cget("text"), "Auto-edit")
        self.app.set_approval_mode("suggest", announce=False)

    def test_composer_suggestions(self):
        self.app._set_prompt_text("/com")
        self.app.instructions.mark_set(tk.INSERT, tk.END)
        self.app._on_composer_key()
        labels = [label for label, _desc in self.app._suggest_items]
        self.assertIn("/compact", labels)
        self.app._accept_suggestion()
        self.assertTrue(self.app.instructions.get("1.0", "end-1c").startswith("/com"))
        self.app._scanned_context_paths = ("src/app.py", "README.md")
        self.app._set_prompt_text("look at @src")
        self.app.instructions.mark_set(tk.INSERT, tk.END)
        self.app._on_composer_key()
        self.assertEqual(self.app._suggest_items[0][0], "@src/app.py")
        self.app._accept_suggestion()
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "look at @src/app.py ")

    def test_resume_restores_conversation(self):
        self.app._record_conversation_turn("Add tests", "Added tests for parser")
        session_id = self.app.conversation.session_id
        self.app.reset_session()
        self.assertEqual(self.app.session_messages, [])
        handled, ok, message = self.app.run_slash_command(f"/resume {session_id}")
        self.assertTrue(ok, message)
        self.assertEqual(self.app.session_messages[0]["content"], "Add tests")

    def test_copy_save_rename_doctor_mention(self):
        self.app._transcript_add("user", "Add tests")
        self.app._transcript_add("agent", "Added tests")
        self.assertTrue(self.app.run_slash_command("/copy")[1])
        self.assertEqual(self.app.clipboard_get(), "Added tests")
        self.assertTrue(self.app.run_slash_command("/save chat.md")[1])
        self.assertIn("## CodeRouter", Path(self.project.name, "chat.md").read_text(encoding="utf-8"))
        self.assertTrue(self.app.run_slash_command("/rename Parser work")[1])
        self.assertEqual(self.app.conversation.title, "Parser work")
        self.app.run_slash_command("/doctor")
        self.assertIn("Doctor", self.app.summary.get("1.0", tk.END))
        self.app._set_prompt_text("")
        self.app.run_slash_command("/mention src/a.py")
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "@src/a.py ")

    def test_code_review_runs_in_background(self):
        import subprocess

        subprocess.run(["git", "init", "-q", self.project.name], check=True)
        Path(self.project.name, "a.py").write_text("x = 1\n", encoding="utf-8")
        self.app.api_key = "sk-or-test"
        with mock.patch.object(wrapper, "complete_text", return_value=("a.py:1 low: fine", "m:free")):
            handled, ok, message = self.app.run_slash_command("/code-review")
            self.assertTrue(ok, message)
            for _ in range(50):
                self.app._drain_parity_queue()
                if "a.py:1 low" in self.app.summary.get("1.0", tk.END):
                    break
                self.app.after(20)
                self.app.update()
        self.assertIn("a.py:1 low", self.app.summary.get("1.0", tk.END))

    def test_command_palette_filters_and_runs(self):
        self.app.open_command_palette()
        self.assertTrue(self.app.palette_frame.winfo_manager())
        self.app.palette_entry.insert(0, "doct")
        self.app._palette_filter()
        self.assertEqual(self.app._palette_items[0].name, "doctor")
        self.app._palette_run()
        self.assertFalse(self.app.palette_frame.winfo_manager())
        self.assertIn("Doctor", self.app.summary.get("1.0", tk.END))
        self.app.open_command_palette()
        self.app.palette_entry.insert(0, "allow")
        self.app._palette_filter()
        self.app._palette_run()
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "/allow ")

    def test_plan_checklist_and_queue(self):
        plan = wrapper.ExecutionPlan("Do it", (wrapper.PlanStep("1", "Read", "the code"),))
        self.app.pending_plan = plan
        self.app._transcript_add("agent", self.app._plan_checklist(plan, "pending"))
        self.app._refresh_plan_checklist("done")
        self.assertTrue(self.app.transcript[-1][1].splitlines()[1].startswith("✓ Read"))
        self.app.pending_plan = None
        self.app.task_state = wrapper.TASK_STATE_RUNNING
        self.app._set_prompt_text("next thing")
        with mock.patch.object(self.app, "_start_run_worker") as start:
            self.app.run_agent()
            start.assert_not_called()
            self.assertEqual(self.app.queued_prompts, ["next thing"])
            self.app.task_state = wrapper.TASK_STATE_IDLE
            self.app.api_key = "sk-or-test"
            self.app._run_queued_prompt()
            start.assert_called_once()
        self.assertEqual(self.app.queued_prompts, [])


if __name__ == "__main__":
    unittest.main()
