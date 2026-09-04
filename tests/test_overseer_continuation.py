import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import CodeRouter as wrapper


def approved_review():
    return wrapper.OverseerReview(
        status="approved",
        summary="Bounded evidence is ready.",
        next_step=wrapper.OverseerNextStep(
            title="Review the bounded evidence",
            detail="Prepare a fresh implementation plan from the metadata only.",
            scope=("executor evidence",),
            requires_user_confirmation=True,
        ),
    )


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class OverseerContinuationUiTests(unittest.TestCase):
    def make_app(self, root):
        return wrapper.CodeAgentApp(history_path=Path(root) / "history.json")

    def prepare_app(self, app, root, run_id="parent-run"):
        snapshot = wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(Path(root) / "context.txt",),
            session_messages=(("user", "old task context"),),
            apply_mode=wrapper.APPLY_MODE_AUTO,
            run_id=run_id,
            task_id=f"{run_id}-task",
            request_text="old executor request",
            project_instructions="root instructions",
        )
        app.api_key = "continuation-api-key-123456"
        app.selected_folder.set(str(root))
        app.lifecycle.activate(snapshot)
        app.run_resources.create(snapshot.run_id)
        app.run_snapshot = snapshot
        app._handoff_snapshot = snapshot
        app._handoff_stale = False
        app._handoff_evidence_events = []
        app.overseer_review = approved_review()
        app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review complete")
        app._reset_run_timeline(snapshot.run_id)
        app._update_lifecycle_controls()
        return snapshot

    def prepare_next_step(self, app):
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(app.approve_overseer_next_step())
        self.assertIsNotNone(app._overseer_prepared_next_step)
        self.assertEqual(
            str(app.run_next_step_button.cget("state")),
            wrapper.tk.NORMAL,
        )

    def test_approve_only_prefills_and_run_creates_fresh_plan_snapshot_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "context.txt").write_text("context", encoding="utf-8")
            sentinel = root / "sentinel.txt"
            sentinel.write_text("original", encoding="utf-8")
            app = self.make_app(root)
            try:
                parent = self.prepare_app(app, root, "approved-parent")
                with mock.patch.object(app, "_start_run_worker") as starter:
                    self.prepare_next_step(app)
                    starter.assert_not_called()
                    self.assertIn("Review the bounded evidence", app.instructions.get("1.0", wrapper.tk.END))

                    starter.return_value = object()
                    self.assertTrue(app.run_next_step())
                    self.assertFalse(app.run_next_step())
                starter.assert_called_once()
                next_snapshot = starter.call_args.args[0]
                self.assertIs(
                    starter.call_args.args[1].__func__,
                    wrapper.CodeAgentApp._run_plan_worker,
                )
                self.assertIs(starter.call_args.args[2][0], next_snapshot)
                self.assertNotEqual(next_snapshot.run_id, parent.run_id)
                self.assertNotEqual(next_snapshot.task_id, parent.task_id)
                self.assertEqual(next_snapshot.project_root, parent.project_root)
                self.assertEqual(next_snapshot.extra_context_paths, parent.extra_context_paths)
                self.assertEqual(next_snapshot.session_history, ())
                self.assertEqual(next_snapshot.apply_mode, wrapper.APPLY_MODE_REVIEW)
                self.assertIsNone(next_snapshot.approved_plan)
                self.assertEqual(next_snapshot.inspect_round, 0)
                self.assertEqual(next_snapshot.verification_round, 0)
                self.assertIn("Review the bounded evidence", next_snapshot.request_text)
                self.assertEqual(app.task_state, wrapper.TASK_STATE_PLANNING)
                self.assertEqual(app._overseer_continuation_parent_run_id, parent.run_id)
                self.assertIsNone(app.pending_proposal)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")
            finally:
                app.destroy()

    def test_run_requires_approved_current_confirmation_and_preparation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                self.prepare_app(app, root, "gate-parent")
                with mock.patch.object(app, "_start_run_worker") as starter:
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()

                    app.overseer_review = wrapper.OverseerReview(
                        "needs_attention",
                        "More evidence is needed.",
                        approved_review().next_step,
                    )
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()

                    app.overseer_review = wrapper.OverseerReview(
                        "blocked",
                        "The evidence is blocked.",
                        approved_review().next_step,
                    )
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()

                    app.overseer_review = approved_review()
                    self.prepare_next_step(app)
                    app._handoff_stale = True
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()
            finally:
                app.destroy()

    def test_reset_folder_and_close_clear_prepared_next_step(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as next_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                self.prepare_app(app, root, "reset-parent")
                self.prepare_next_step(app)
                with mock.patch.object(app, "_start_run_worker") as starter:
                    app.reset_session()
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()
                self.assertIsNone(app._overseer_prepared_next_step)

                self.prepare_app(app, root, "folder-parent")
                self.prepare_next_step(app)
                with (
                    mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(next_dir)),
                    mock.patch.object(wrapper, "save_local_config"),
                    mock.patch.object(app, "scan_folder", return_value=True),
                    mock.patch.object(app, "_start_run_worker") as starter,
                ):
                    app.choose_folder()
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()
                self.assertIsNone(app._overseer_prepared_next_step)
            finally:
                app.destroy()

            app = self.make_app(root)
            self.prepare_app(app, root, "close-parent")
            self.prepare_next_step(app)
            with mock.patch.object(app, "_start_run_worker") as starter:
                app.on_close()
                starter.assert_not_called()
            self.assertTrue(app.lifecycle.closed)
            self.assertIsNone(app._overseer_prepared_next_step)

    def test_next_step_contract_rejects_secret_command_path_and_material(self):
        bad_steps = (
            wrapper.OverseerNextStep(
                "Review",
                "Authorization: Bearer raw-continuation-token",
                ("executor evidence",),
            ),
            wrapper.OverseerNextStep("Run command", "Prepare a plan", ("executor evidence",)),
            wrapper.OverseerNextStep("Review", "Prepare a plan", ("../outside",)),
            wrapper.OverseerNextStep("Review", "diff --git a/a b/a", ("executor evidence",)),
        )
        for step in bad_steps:
            with self.subTest(step=step):
                with self.assertRaises(ValueError):
                    wrapper.format_overseer_next_step_prompt(step)

    def test_two_terminal_handoffs_rearm_with_one_worker_per_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                with mock.patch.object(app, "_start_run_worker", return_value=object()) as starter:
                    first_parent = self.prepare_app(app, root, "cycle-one")
                    self.prepare_next_step(app)
                    self.assertTrue(app.run_next_step())

                    second_parent = self.prepare_app(app, root, "cycle-two")
                    self.prepare_next_step(app)
                    self.assertTrue(app.run_next_step())

                self.assertEqual(starter.call_count, 2)
                self.assertNotEqual(first_parent.run_id, second_parent.run_id)
                self.assertEqual(
                    [call.args[1].__func__ for call in starter.call_args_list],
                    [wrapper.CodeAgentApp._run_plan_worker] * 2,
                )
                self.assertTrue(all(call.args[2][0].approved_plan is None for call in starter.call_args_list))
            finally:
                app.destroy()

    def test_tk_buttons_rearm_for_new_terminal_handoff_and_after_prepare(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                with mock.patch.object(app, "_start_run_worker", return_value=object()):
                    first_parent = self.prepare_app(app, root, "button-cycle-one")
                    self.assertEqual(
                        str(app.approve_next_step_button.cget("state")),
                        wrapper.tk.NORMAL,
                    )
                    self.assertEqual(
                        str(app.run_next_step_button.cget("state")),
                        wrapper.tk.DISABLED,
                    )
                    self.prepare_next_step(app)
                    self.assertEqual(
                        str(app.approve_next_step_button.cget("state")),
                        wrapper.tk.DISABLED,
                    )
                    self.assertEqual(
                        str(app.run_next_step_button.cget("state")),
                        wrapper.tk.NORMAL,
                    )
                    self.assertTrue(app.run_next_step())

                    second_parent = self.prepare_app(app, root, "button-cycle-two")
                    self.assertNotEqual(first_parent.run_id, second_parent.run_id)
                    self.assertEqual(
                        str(app.approve_next_step_button.cget("state")),
                        wrapper.tk.NORMAL,
                    )
                    self.assertEqual(
                        str(app.run_next_step_button.cget("state")),
                        wrapper.tk.DISABLED,
                    )
                    self.prepare_next_step(app)
                    self.assertEqual(
                        str(app.run_next_step_button.cget("state")),
                        wrapper.tk.NORMAL,
                    )

                    app.overseer_review = wrapper.OverseerReview(
                        "needs_attention",
                        "More bounded evidence is needed.",
                        approved_review().next_step,
                    )
                    app._update_lifecycle_controls()
                    self.assertEqual(
                        str(app.approve_next_step_button.cget("state")),
                        wrapper.tk.DISABLED,
                    )
                    self.assertEqual(
                        str(app.run_next_step_button.cget("state")),
                        wrapper.tk.DISABLED,
                    )
            finally:
                app.destroy()

    def test_same_consumed_or_mismatched_handoff_cannot_unlock_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                parent = self.prepare_app(app, root, "stale-parent")
                self.prepare_next_step(app)
                app._overseer_consumed_handoff_run_id = parent.run_id
                app._overseer_next_step_run_started = True
                with mock.patch.object(app, "_start_run_worker") as starter:
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()

                other = wrapper.create_run_snapshot(
                    root,
                    (),
                    (),
                    wrapper.APPLY_MODE_REVIEW,
                    run_id="other-handoff",
                    task_id="other-task",
                    request_text="other",
                )
                app._handoff_snapshot = other
                app._handoff_stale = False
                app.overseer_review = approved_review()
                app._overseer_prepared_handoff_run_id = parent.run_id
                with mock.patch.object(app, "_start_run_worker") as starter:
                    self.assertFalse(app.run_next_step())
                    starter.assert_not_called()
            finally:
                app.destroy()

    def test_worker_start_failure_rolls_back_only_consumed_gate_without_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sentinel = root / "sentinel.txt"
            sentinel.write_text("original", encoding="utf-8")
            app = self.make_app(root)
            try:
                parent = self.prepare_app(app, root, "failure-parent")
                self.prepare_next_step(app)
                with mock.patch.object(
                    app,
                    "_start_run_worker",
                    side_effect=RuntimeError("worker unavailable"),
                ) as starter:
                    self.assertFalse(app.run_next_step())
                starter.assert_called_once()
                self.assertIsNone(app._overseer_consumed_handoff_run_id)
                self.assertFalse(app._overseer_next_step_run_started)
                self.assertIsNone(app.pending_proposal)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "original")
                self.assertNotEqual(app.lifecycle.active_run_id, parent.run_id)
            finally:
                app.destroy()


if __name__ == "__main__":
    unittest.main()
