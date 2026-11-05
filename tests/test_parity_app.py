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

    def test_skills_and_agents_join_run_context(self):
        skill = Path(self.project.name, ".claude", "skills", "sql-migrations")
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\ndescription: Write safe SQL migrations with rollback\n---\nAlways add a down migration.", encoding="utf-8")
        agents = Path(self.project.name, ".claude", "agents")
        agents.mkdir(parents=True)
        (agents / "tester.md").write_text("Write tests first.", encoding="utf-8")
        self.app._on_project_changed(self.project.name)
        self.assertTrue(self.app.run_slash_command("/agent tester")[1])
        self.app.api_key = "sk-or-test"
        self.app._set_prompt_text("add a SQL migration with rollback for users")
        with mock.patch.object(self.app, "_start_run_worker") as start:
            self.app.run_agent()
        context = start.call_args[0][0].project_instructions
        self.assertIn("Always add a down migration.", context)
        self.assertIn("Write tests first.", context)
        self.assertFalse(self.app.run_slash_command("/skill nope")[1])
        self.app.run_slash_command("/agent off")

    def test_rewind_restores_multiple_applies(self):
        root = Path(self.project.name)
        target = root / "a.txt"
        target.write_text("v1", encoding="utf-8")
        for index, content in enumerate(("v2", "v3")):
            snapshot = wrapper.create_run_snapshot(root, (), (), wrapper.APPLY_MODE_REVIEW, run_id=f"r{index}")
            proposal = wrapper.create_pending_proposal(snapshot, [{"path": "a.txt", "content": content}])
            undo = wrapper.build_undo_transaction(proposal)
            wrapper.apply_proposal_transactionally(proposal, root, wrapper.TASK_STATE_REVIEW, f"r{index}")
            self.app._push_apply_undo(undo)
        self.assertEqual(len(self.app.apply_undo_stack), 1)
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            handled, ok, message = self.app.run_slash_command("/rewind 2")
        self.assertTrue(ok, message)
        self.assertEqual(target.read_text(encoding="utf-8"), "v1")
        self.assertIsNone(self.app._last_apply_undo)

    def test_prompt_history_recall(self):
        self.app._remember_prompt("first")
        self.app._remember_prompt("second")
        self.app._set_prompt_text("draft")
        self.app.instructions.mark_set(tk.INSERT, "1.0")
        self.assertEqual(self.app._on_history_up(), "break")
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "second")
        self.app._on_history_up()
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "first")
        self.app.instructions.mark_set(tk.INSERT, tk.END)
        self.app._on_history_down()
        self.app._on_history_down()
        self.assertEqual(self.app.instructions.get("1.0", "end-1c"), "draft")

    def _pump(self, condition, seconds=8.0):
        import time as _time

        deadline = _time.monotonic() + seconds
        while _time.monotonic() < deadline:
            self.app.update()
            if condition():
                return True
            _time.sleep(0.02)
        return False

    def test_full_auto_end_to_end(self):
        import json as _json

        root = Path(self.project.name)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        plan = _json.dumps({"summary": "Bump x", "steps": [{"id": "1", "title": "Edit", "detail": "set x to 2"}]})
        inspect = _json.dumps({"action": "inspect", "summary": "read a", "paths": ["a.py"]})
        final = _json.dumps({"action": "final", "summary": "Set x to 2", "files": [{"path": "a.py", "edits": [{"old": "x = 1", "new": "x = 2"}]}]})
        replies = iter([plan, inspect, final])

        class Response:
            def __init__(self, text):
                payload = {"choices": [{"delta": {"content": text}}]}
                self.chunks = iter([f"data: {_json.dumps(payload)}\n\ndata: [DONE]\n\n".encode("utf-8")])

            def read(self, _size=-1):
                return next(self.chunks, b"")

            def close(self):
                pass

        self.app.api_key = "sk-or-test"
        self.app.set_approval_mode("full-auto", announce=False)
        self.app.scan_folder(silent=True)
        self.app._set_prompt_text("set x to 2")
        with (
            mock.patch.object(wrapper, "build_free_model_queue", return_value=(["t/model:free"], "")),
            mock.patch.object(wrapper, "urlopen", side_effect=lambda *_a, **_k: Response(next(replies))),
            mock.patch.object(wrapper.messagebox, "askyesno", return_value=True),
            mock.patch.object(wrapper.messagebox, "showerror"),
        ):
            self.app.set_plan_gate(False)
            self.app.run_agent()
            done = self._pump(lambda: (root / "a.py").read_text(encoding="utf-8") == "x = 2\n")
        self.assertTrue(done, f"state={self.app.task_state} summary={self.app.summary.get('1.0', tk.END)[-300:]}")
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_APPLIED)
        self.assertIn("Set x to 2", self.app.summary.get("1.0", tk.END))
        self.app.set_plan_gate(True)
        self.app.set_approval_mode("suggest", announce=False)

    def test_starters_follow_project_state(self):
        self.app.selected_folder.set("")
        self.app.api_key = ""
        self.assertEqual([item[1] for item in self.app._starter_set()[:2]], ["Connect OpenRouter", "Open a project"])
        self.app.api_key = "sk-or-test"
        self.assertEqual(self.app._starter_set()[0][1], "Open a project")
        self.app.selected_folder.set(self.project.name)
        self.assertEqual(self.app._starter_set()[0][2], "/init")
        Path(self.project.name, "AGENTS.md").write_text("x", encoding="utf-8")
        self.app.git_state = wrapper._git.GitStatus(True, "main", 0, 0, ((" M", "a.py"),))
        labels = [item[1] for item in self.app._starter_set()]
        self.assertEqual(labels[:2], ["Review my changes", "Commit changes"])
        self.app._starters_checked_at = 0.0
        self.app._refresh_starters()
        self.assertEqual(self.app._empty_tile_parts[0][1].cget("text"), "Review my changes")
        self.app._record_conversation_turn("old", "chat")
        self.app.conversation = wrapper._sessions.Conversation("s-new", self.project.name)
        self.assertEqual(self.app._starter_set()[0][1], "Resume last chat")

    def test_always_allow_saves_rules(self):
        self.app.inspect_request = wrapper.InspectRequest("read", ("src/a.py", "README.md"), "r1")
        self.app.verification_request = wrapper.VerificationRequest(command="python -m pytest -q")
        with (
            mock.patch.object(self.app, "allow_inspect", return_value=True) as allow_inspect,
            mock.patch.object(self.app, "allow_verification", return_value=True) as allow_verify,
        ):
            self.assertTrue(self.app.always_allow_inspect())
            self.assertTrue(self.app.always_allow_verification())
        allow_inspect.assert_called_once()
        allow_verify.assert_called_once()
        self.assertEqual(self.app.approval_rules.allow, ["Read(src/**)", "Read(README.md)", "Bash(python -m pytest*)"])
        self.app.inspect_request = None
        self.app.verification_request = None

    def test_worker_mcp_call_respects_policy(self):
        import sys as _sys

        server_script = str(Path(__file__).resolve().parent / "fake_mcp_server.py")
        self.app.mcp_manager = wrapper._mcp.McpManager(wrapper._mcp.load_server_specs(
            {"mcp_servers": {"fake": {"command": [_sys.executable, server_script]}}}))
        try:
            self.app.mcp_manager.start_all()
            call = wrapper.McpCall("fake.echo", ('{"text": "yo"}',))
            self.assertIn("Refused", self.app._run_mcp_call(call).content)
            self.app.run_slash_command("/allow Mcp(fake.*)")
            self.assertEqual(self.app._run_mcp_call(call).content, "echo: yo")
            self.app.run_slash_command("/mcp")
            self.assertIn("fake (user): connected", self.app.summary.get("1.0", tk.END))
        finally:
            self.app.mcp_manager.stop_all()

    def test_stream_log_inline_and_palette_sessions(self):
        self.app._log_stream('{"action":')
        self.app._log_stream('"final"}')
        self.app.log("! failed")
        text = self.app.activity.get("1.0", tk.END)
        self.assertIn('[model] {"action":"final"}\n', text)
        self.assertIn("log_error", self.app.activity.tag_names("end-3c"))
        self.app._record_conversation_turn("Parser rewrite", "Done")
        self.app.open_command_palette()
        self.app.palette_entry.insert(0, "parser")
        self.app._palette_filter()
        sessions = [item for item in self.app._palette_items if item.kind == "session"]
        self.assertEqual(len(sessions), 1)
        self.app.close_command_palette()

    def test_reject_some_files_keeps_the_rest(self):
        root = Path(self.project.name)
        snapshot = wrapper.create_run_snapshot(root, (), (), wrapper.APPLY_MODE_REVIEW, run_id="rj")
        self.app.lifecycle.activate(snapshot)
        edits = [{"path": "a.py", "content": "a"}, {"path": "b.py", "content": "b"}]
        proposal = wrapper.create_pending_proposal(snapshot, edits)
        self.app._set_pending_proposal(proposal)
        self.app.diff_by_path = wrapper.render_diff_by_path(root, edits)
        self.app.populate_changed_files(wrapper.build_file_rows(self.app.diff_by_path))
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review 2")
        handled, ok, message = self.app.run_slash_command("/reject b.py")
        self.assertTrue(ok, message)
        self.assertEqual([edit.relative_path for edit in self.app.pending_proposal.edits], ["a.py"])
        self.assertEqual(list(self.app.diff_by_path), ["a.py"])
        self.assertFalse(self.app.run_slash_command("/reject zzz.py")[1])

    def test_ask_mode_answers_without_a_run(self):
        Path(self.project.name, "app.py").write_text("def main(): pass\n", encoding="utf-8")
        self.app.api_key = "sk-or-test"
        self.app._set_prompt_text("? where is main defined")
        with (
            mock.patch.object(wrapper, "complete_text", return_value=("In app.py.", "m:free")) as complete,
            mock.patch.object(self.app, "_start_run_worker") as start,
        ):
            self.app.run_agent()
            self.assertTrue(self._pump(lambda: "In app.py." in self.app.summary.get("1.0", tk.END)))
        start.assert_not_called()
        self.assertIn("def main()", complete.call_args[0][1])
        self.assertEqual(self.app.session_messages[-1]["content"], "In app.py.")

    def test_recent_folders_and_title(self):
        other = tempfile.TemporaryDirectory()
        try:
            with mock.patch.object(self.app, "scan_folder"):
                self.app.open_folder(other.name)
            self.assertEqual(self.app.selected_folder.get(), other.name)
            self.assertEqual(self.app.config_data["recent_folders"][0], other.name)
            self.assertTrue(self.app.title().startswith(Path(other.name).name))
            self.assertIs(wrapper.filedialog.askdirectory.__name__ != "<lambda>", True)
        finally:
            other.cleanup()

    def test_profiles_apply_settings(self):
        self.app.config_data["profiles"] = {"yolo": {"approval_mode": "full-auto", "plan_gate": False, "style": "concise", "bogus": 1}}
        handled, ok, message = self.app.run_slash_command("/profile yolo")
        self.assertTrue(ok, message)
        self.assertEqual(self.app.approval_mode_value, "full-auto")
        self.assertFalse(self.app.plan_gate_enabled)
        self.assertEqual(wrapper.GENERATION_SETTINGS["style"], "concise")
        self.assertIn("*yolo", self.app.run_slash_command("/profile")[2])
        self.assertFalse(self.app.run_slash_command("/profile nope")[1])
        self.app.set_approval_mode("suggest", announce=False)
        self.app.set_plan_gate(True)
        self.app.set_output_style("default")

    def test_stream_preview_extracts_summary(self):
        self.app._stream_buffer = '{"action":"final","summary":"Guard the loader agai'
        self.app._show_stream_preview()
        self.assertIn("Writing · Guard the loader agai", self.app.summary.get("1.0", tk.END))
        self.app._stream_buffer = '{"summary":"p","steps":[{"id":"1","title":"Read the \\"config\\" file'
        self.app._show_stream_preview()
        self.assertIn('Planning · Read the "config" file', self.app.summary.get("1.0", tk.END))

    def test_tests_run_after_apply_only_when_allowed(self):
        Path(self.project.name, "tests").mkdir()
        with mock.patch.object(self.app, "run_verification", return_value=True) as run:
            self.assertFalse(self.app._test_after_apply(self.project.name))
            run.assert_not_called()
            self.app.run_slash_command("/allow Bash(python -m unittest*)")
            self.assertTrue(self.app._test_after_apply(self.project.name))
            run.assert_called_once()
        self.assertEqual(self.app.verification_command.get(), "python -m unittest discover -s tests")
        self.assertTrue(self.app.run_slash_command("/test after-apply on")[1])
        self.assertTrue(self.app.config_data["test_after_apply"])

    def test_custom_statusline(self):
        import sys as _sys

        self.app.config_data["statusline_command"] = [_sys.executable, "-c", "import sys, json; print('proj:' + str(json.load(sys.stdin)['approval']))"]
        self.app._start_statusline()
        self.assertTrue(self._pump(lambda: self.app._statusline_label.cget("text") == "proj:suggest"))


if __name__ == "__main__":
    unittest.main()
