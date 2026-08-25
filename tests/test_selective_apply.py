import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class SelectiveApplyUnitTests(unittest.TestCase):
    def make_proposal(self, root, edits, run_id="selective-unit"):
        snapshot = wrapper.create_run_snapshot(
            Path(root),
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="selective apply test",
        )
        return wrapper.create_pending_proposal(snapshot, edits)

    def test_subset_preserves_original_order_and_preconditions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "one.txt").write_text("one-before", encoding="utf-8")
            (root / "two.txt").write_text("two-before", encoding="utf-8")
            proposal = self.make_proposal(
                root,
                [
                    {"path": "one.txt", "content": "one-after"},
                    {"path": "two.txt", "content": "two-after"},
                ],
            )
            subset = wrapper.select_pending_proposal(proposal, ("two.txt",))
            self.assertEqual([item.relative_path for item in subset.edits], ["two.txt"])
            self.assertIs(subset.preconditions[0], proposal.preconditions[1])
            self.assertEqual(subset.run_id, proposal.run_id)
            self.assertEqual(subset.project_root, proposal.project_root)

    def test_subset_rejects_unknown_or_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal = self.make_proposal(root, [{"path": "one.txt", "content": "after"}])
            for selected in (("missing.txt",), ("../outside.txt",), (".env",)):
                with self.subTest(selected=selected):
                    with self.assertRaises(ValueError):
                        wrapper.select_pending_proposal(proposal, selected)

    def test_subset_transaction_rolls_back_when_second_selected_write_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first-before", encoding="utf-8")
            second.write_text("second-before", encoding="utf-8")
            proposal = self.make_proposal(
                root,
                [
                    {"path": "first.txt", "content": "first-after"},
                    {"path": "second.txt", "content": "second-after"},
                ],
            )
            selected = wrapper.select_pending_proposal(proposal, ("first.txt", "second.txt"))
            real_replace = wrapper.os.replace
            calls = 0

            def fail_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated selected apply failure")
                return real_replace(source, target)

            with mock.patch.object(wrapper.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "simulated selected apply failure"):
                    wrapper.apply_proposal_transactionally(
                        selected,
                        root,
                        wrapper.TASK_STATE_REVIEW,
                        selected.run_id,
                    )
            self.assertEqual(first.read_text(encoding="utf-8"), "first-before")
            self.assertEqual(second.read_text(encoding="utf-8"), "second-before")


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class SelectiveApplyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            tk.Tcl()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tcl unavailable: {exc}")

    def setUp(self):
        self.project_dir = tempfile.TemporaryDirectory()
        self.history_dir = tempfile.TemporaryDirectory()
        self.config_path = tempfile.TemporaryDirectory()
        self.original_config_path = wrapper.CONFIG_PATH
        wrapper.CONFIG_PATH = Path(self.config_path.name) / "local_config.json"
        self.app = wrapper.CodeAgentApp(
            history_path=Path(self.history_dir.name) / "history.json"
        )
        self.app.withdraw()

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.project_dir.cleanup()
        self.history_dir.cleanup()
        self.config_path.cleanup()

    @property
    def root(self):
        return Path(self.project_dir.name)

    def prepare(self, names=("one.txt", "two.txt", "three.txt"), run_id="selective-ui"):
        edits = []
        for name in names:
            (self.root / name).write_text(f"{name}-before", encoding="utf-8")
            edits.append({"path": name, "content": f"{name}-after"})
        snapshot = wrapper.create_run_snapshot(
            self.root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="selective UI test",
        )
        self.app.selected_folder.set(str(self.root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
        proposal = wrapper.create_pending_proposal(snapshot, edits)
        self.app._set_pending_proposal(proposal)
        self.app.diff_by_path = wrapper.render_diff_by_path(self.root, edits)
        self.app.populate_changed_files(wrapper.build_file_rows(self.app.diff_by_path))
        self.app.update_idletasks()
        self.app._update_apply_controls()
        return snapshot, proposal

    def select(self, *paths):
        self.app.edited_files.selection_set(paths)
        self.app.update_idletasks()
        self.app._update_apply_controls()

    def test_visible_selected_button_requires_review_and_selection(self):
        self.prepare()
        self.assertEqual(str(self.app.apply_button.cget("state")), tk.NORMAL)
        self.assertEqual(str(self.app.apply_selected_button.cget("state")), tk.NORMAL)

        self.app.edited_files.selection_remove(*self.app.edited_files.selection())
        self.app._update_apply_controls()
        self.assertEqual(str(self.app.apply_selected_button.cget("state")), tk.DISABLED)

        self.app.edited_files.selection_set("one.txt")
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "worker active")
        self.assertEqual(str(self.app.apply_button.cget("state")), tk.DISABLED)
        self.assertEqual(str(self.app.apply_selected_button.cget("state")), tk.DISABLED)

    def test_partial_apply_keeps_unselected_pending_and_undoes_only_selected(self):
        _snapshot, proposal = self.prepare()
        self.select("one.txt")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.apply_selected())

        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-after")
        self.assertEqual((self.root / "two.txt").read_text(encoding="utf-8"), "two.txt-before")
        self.assertEqual((self.root / "three.txt").read_text(encoding="utf-8"), "three.txt-before")
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REVIEW)
        self.assertEqual(
            [edit.relative_path for edit in self.app.pending_proposal.edits],
            ["two.txt", "three.txt"],
        )
        self.assertIsNotNone(self.app._last_apply_undo)
        self.assertEqual([item.relative_path for item in self.app._last_apply_undo.files], ["one.txt"])
        self.assertIsNot(self.app.pending_proposal, proposal)

        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.undo_last_apply())
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-before")
        self.assertEqual((self.root / "two.txt").read_text(encoding="utf-8"), "two.txt-before")
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REVIEW)
        self.assertEqual(str(self.app.apply_button.cget("state")), tk.NORMAL)
        self.assertIsNotNone(self.app.pending_proposal)

        self.select("two.txt")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.apply_selected())
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REVIEW)
        self.assertEqual(
            [edit.relative_path for edit in self.app.pending_proposal.edits],
            ["three.txt"],
        )
        self.app.apply_pending()
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_APPLIED)
        self.assertIsNone(self.app.pending_proposal)
        self.assertEqual((self.root / "three.txt").read_text(encoding="utf-8"), "three.txt-after")

    def test_multi_select_applies_only_selected_files(self):
        self.prepare()
        self.select("one.txt", "three.txt")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.apply_selected())
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-after")
        self.assertEqual((self.root / "two.txt").read_text(encoding="utf-8"), "two.txt-before")
        self.assertEqual((self.root / "three.txt").read_text(encoding="utf-8"), "three.txt-after")
        self.assertEqual([edit.relative_path for edit in self.app.pending_proposal.edits], ["two.txt"])
        self.assertEqual(
            {item.relative_path for item in self.app._last_apply_undo.files},
            {"one.txt", "three.txt"},
        )

    def test_selected_confirmation_rejection_has_no_write_or_undo(self):
        self.prepare()
        self.select("one.txt")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=False) as confirm:
            self.assertFalse(self.app.apply_selected())
        confirm.assert_called_once()
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-before")
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REVIEW)
        self.assertIsNotNone(self.app.pending_proposal)
        self.assertIsNone(self.app._last_apply_undo)

    def test_root_hash_and_stale_guards_refuse_without_write(self):
        _snapshot, _proposal = self.prepare()
        self.select("one.txt")
        other_dir = tempfile.TemporaryDirectory()
        try:
            self.app.selected_folder.set(other_dir.name)
            with mock.patch.object(wrapper.messagebox, "askyesno") as confirm:
                self.assertFalse(self.app.apply_selected())
            confirm.assert_not_called()
            self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-before")

            self.app.selected_folder.set(str(self.root))
            (self.root / "one.txt").write_text("external-change", encoding="utf-8")
            with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
                self.assertFalse(self.app.apply_selected())
            self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "external-change")
            self.assertIsNotNone(self.app.pending_proposal)

            self.app.lifecycle.invalidate()
            self.app._update_apply_controls()
            with mock.patch.object(wrapper.messagebox, "askyesno") as confirm:
                self.assertFalse(self.app.apply_selected())
            confirm.assert_not_called()
        finally:
            other_dir.cleanup()

    def test_reset_and_close_clear_selection_proposal_and_undo(self):
        self.prepare()
        self.app._last_apply_undo = object()
        self.app.reset_session()
        self.assertIsNone(self.app.pending_proposal)
        self.assertIsNone(self.app._last_apply_undo)
        self.assertEqual(self.app.edited_files.selection(), ())

        self.prepare(run_id="close-selective")
        self.app._last_apply_undo = object()
        self.app.on_close()
        self.assertIsNone(self.app._last_apply_undo)
        self.assertTrue(self.app.lifecycle.closed)

    def test_selected_apply_has_no_worker_command_or_auto_apply_side_effect(self):
        self.prepare()
        self.select("one.txt")
        with (
            mock.patch.object(self.app, "_start_run_worker") as start_worker,
            mock.patch.object(self.app, "apply_pending") as apply_all,
            mock.patch.object(wrapper.messagebox, "askyesno", return_value=True),
        ):
            self.assertTrue(self.app.apply_selected())
        start_worker.assert_not_called()
        apply_all.assert_not_called()
        self.assertFalse(self.app.run_resources.worker_handles)
        self.assertFalse(self.app.run_resources.provider_response_handles)
        self.assertFalse(self.app.run_resources.process_handles)
        history_path = Path(self.history_dir.name) / "history.json"
        history_text = history_path.read_text(encoding="utf-8") if history_path.exists() else ""
        self.assertNotIn("one.txt-after", history_text)
        self.assertNotIn("two.txt-before", history_text)

    def test_unrelated_stale_handles_do_not_block_all_selected_or_undo(self):
        self.prepare(names=("one.txt", "two.txt"), run_id="scope-all")
        stale_owner = self.app.run_resources.create("stale-previous-run")
        stale_worker = object()
        self.assertTrue(stale_owner.register_worker(stale_worker))

        self.app.apply_pending()
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_APPLIED)
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-after")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.undo_last_apply())
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-before")

        self.prepare(names=("one.txt", "two.txt"), run_id="scope-selected")
        self.select("one.txt")
        with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.apply_selected())
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-after")
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_REVIEW)
        self.assertEqual([edit.relative_path for edit in self.app.pending_proposal.edits], ["two.txt"])

    def test_current_and_linked_resources_still_block_apply_selected_and_undo(self):
        snapshot, _proposal = self.prepare(names=("one.txt", "two.txt"), run_id="scope-current")
        current_owner = self.app.run_resources.create(snapshot.run_id)
        current_worker = object()
        self.assertTrue(current_owner.register_worker(current_worker))
        self.app._update_apply_controls()
        self.assertEqual(str(self.app.apply_button.cget("state")), tk.DISABLED)
        self.assertEqual(str(self.app.apply_selected_button.cget("state")), tk.DISABLED)
        self.select("one.txt")
        with mock.patch.object(wrapper.messagebox, "askyesno") as confirm:
            self.assertFalse(self.app.apply_selected())
        confirm.assert_not_called()
        self.assertEqual((self.root / "one.txt").read_text(encoding="utf-8"), "one.txt-before")
        current_owner.unregister_worker(current_worker)

        verification_id = "verification-linked-child"
        verification_owner = self.app.run_resources.create(verification_id)
        verification_worker = object()
        self.assertTrue(verification_owner.register_worker(verification_worker))
        self.app.verification_run_id = verification_id
        self.app._verification_executor_run_id = snapshot.run_id
        self.app._verification_lineage = wrapper.VerificationLineage(
            parent_executor_run_id=snapshot.run_id,
            child_verification_run_id=verification_id,
            command_identity="python",
        )
        self.app._update_apply_controls()
        self.assertEqual(str(self.app.apply_selected_button.cget("state")), tk.DISABLED)
        verification_owner.unregister_worker(verification_worker)
        self.app._stop_verification(keep_identity=False)

        self.app.apply_pending()
        self.assertEqual(self.app.task_state, wrapper.TASK_STATE_APPLIED)
        transaction = self.app._last_apply_undo
        self.assertIsNotNone(transaction)
        overseer_id = "overseer-linked-child"
        overseer_owner = self.app.run_resources.create(overseer_id)
        overseer_worker = object()
        self.assertTrue(overseer_owner.register_worker(overseer_worker))
        self.app._handoff_snapshot = snapshot
        self.app._handoff_stale = False
        self.app.overseer_run_id = overseer_id
        self.app._overseer_executor_run_id = snapshot.run_id
        self.app._update_lifecycle_controls()
        with mock.patch.object(wrapper.messagebox, "askyesno") as confirm:
            self.assertFalse(self.app.undo_last_apply())
        confirm.assert_not_called()
        self.assertIs(self.app._last_apply_undo, transaction)
        overseer_owner.unregister_worker(overseer_worker)


if __name__ == "__main__":
    unittest.main()
