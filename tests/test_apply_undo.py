import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class ApplyUndoTransactionTests(unittest.TestCase):
    def proposal(self, root, edits, run_id="undo-run"):
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="bounded apply",
        )
        return wrapper.create_pending_proposal(snapshot, edits)

    def test_existing_content_and_created_file_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / "existing.txt"
            existing.write_text("before", encoding="utf-8")
            proposal = self.proposal(
                root,
                [
                    {"path": "existing.txt", "content": "after"},
                    {"path": "created.txt", "content": "created"},
                ],
            )
            transaction = wrapper.build_undo_transaction(proposal)
            self.assertEqual(
                wrapper.apply_proposal_transactionally(
                    proposal,
                    root,
                    wrapper.TASK_STATE_REVIEW,
                    proposal.run_id,
                ),
                2,
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "after")
            self.assertTrue((root / "created.txt").exists())
            self.assertEqual(wrapper.restore_undo_transactionally(transaction, root), 2)
            self.assertEqual(existing.read_text(encoding="utf-8"), "before")
            self.assertFalse((root / "created.txt").exists())
            metadata = json.dumps(transaction.metadata())
            self.assertNotIn("before", metadata)
            self.assertNotIn("after", metadata)

    def test_undo_restore_failure_rolls_back_the_undo_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first-before", encoding="utf-8")
            second.write_text("second-before", encoding="utf-8")
            proposal = self.proposal(
                root,
                [
                    {"path": "first.txt", "content": "first-after"},
                    {"path": "second.txt", "content": "second-after"},
                ],
            )
            transaction = wrapper.build_undo_transaction(proposal)
            wrapper.apply_proposal_transactionally(
                proposal,
                root,
                wrapper.TASK_STATE_REVIEW,
                proposal.run_id,
            )
            real_atomic = wrapper._atomic_replace_bytes

            def fail_second(target, content):
                if Path(target).name == "second.txt" and content == b"second-before":
                    raise OSError("simulated undo failure")
                return real_atomic(target, content)

            with mock.patch.object(wrapper, "_atomic_replace_bytes", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "simulated undo"):
                    wrapper.restore_undo_transactionally(transaction, root)
            self.assertEqual(first.read_text(encoding="utf-8"), "first-after")
            self.assertEqual(second.read_text(encoding="utf-8"), "second-after")

    def test_protected_path_cannot_be_captured_for_undo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="protected-undo",
            )
            with self.assertRaises(ValueError):
                wrapper.create_pending_proposal(
                    snapshot,
                    [{"path": ".env", "content": "must not write"}],
                )


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ApplyUndoUiTests(unittest.TestCase):
    def make_app(self, root):
        return wrapper.CodeAgentApp(history_path=Path(root) / "history.json")

    def prepare_applied_app(self, root, edits=None, run_id="ui-undo"):
        root = Path(root)
        target = root / "note.txt"
        target.write_text("before", encoding="utf-8")
        snapshot = wrapper.create_run_snapshot(
            root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            request_text="apply",
        )
        app = self.make_app(root)
        app.selected_folder.set(str(root))
        app.lifecycle.activate(snapshot)
        app.run_snapshot = snapshot
        proposal = wrapper.create_pending_proposal(
            snapshot,
            edits or [{"path": "note.txt", "content": "after"}],
        )
        app._set_pending_proposal(proposal)
        app.set_task_state(wrapper.TASK_STATE_REVIEW, "Review pending")
        app.apply_pending()
        return app, target, proposal

    def test_successful_apply_exposes_one_explicit_undo_and_restores(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app, target, proposal = self.prepare_applied_app(
                temp_dir,
                [
                    {"path": "note.txt", "content": "after"},
                    {"path": "new.txt", "content": "new content"},
                ],
            )
            try:
                self.assertEqual(app.task_state, wrapper.TASK_STATE_APPLIED)
                self.assertIsNotNone(app._last_apply_undo)
                self.assertEqual(
                    str(app.undo_last_apply_button.cget("state")),
                    wrapper.tk.NORMAL,
                )
                with mock.patch.object(wrapper.messagebox, "askyesno", return_value=True):
                    self.assertTrue(app.undo_last_apply())
                self.assertEqual(target.read_text(encoding="utf-8"), "before")
                self.assertFalse((Path(temp_dir) / "new.txt").exists())
                self.assertIsNone(app._last_apply_undo)
                self.assertEqual(app.task_state, wrapper.TASK_STATE_IDLE)
                self.assertIsNone(app.pending_proposal)
            finally:
                app.destroy()

    def test_confirmation_rejection_and_active_worker_do_not_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app, target, _proposal = self.prepare_applied_app(temp_dir)
            try:
                with mock.patch.object(wrapper.messagebox, "askyesno", return_value=False):
                    self.assertFalse(app.undo_last_apply())
                self.assertEqual(target.read_text(encoding="utf-8"), "after")
                self.assertIsNotNone(app._last_apply_undo)

                owner = app.run_resources.create(app._last_apply_undo.source_run_id)
                worker = object()
                self.assertTrue(owner.register_worker(worker))
                with mock.patch.object(wrapper.messagebox, "askyesno") as confirm:
                    self.assertFalse(app.undo_last_apply())
                confirm.assert_not_called()
                self.assertEqual(target.read_text(encoding="utf-8"), "after")
                self.assertIsNotNone(app._last_apply_undo)
            finally:
                app.destroy()

    def test_external_hash_or_root_change_invalidates_without_write(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as other_dir:
            app, target, _proposal = self.prepare_applied_app(temp_dir)
            try:
                target.write_text("changed externally", encoding="utf-8")
                with mock.patch.object(wrapper.messagebox, "askyesno") as confirm:
                    self.assertFalse(app.undo_last_apply())
                confirm.assert_not_called()
                self.assertEqual(target.read_text(encoding="utf-8"), "changed externally")
                self.assertIsNone(app._last_apply_undo)

                app, target, _proposal = self.prepare_applied_app(other_dir, run_id="root-undo")
                app.selected_folder.set(str(temp_dir))
                self.assertFalse(app.undo_last_apply())
                self.assertEqual(target.read_text(encoding="utf-8"), "after")
                self.assertIsNone(app._last_apply_undo)
            finally:
                if not app.lifecycle.closed:
                    app.on_close()

    def test_reset_folder_close_and_history_do_not_retain_undo_content(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as other_dir:
            app, target, _proposal = self.prepare_applied_app(temp_dir, run_id="cleanup-undo")
            history_path = Path(temp_dir) / "history.json"
            try:
                app.reset_session()
                self.assertIsNone(app._last_apply_undo)
                app, target, _proposal = self.prepare_applied_app(other_dir, run_id="folder-undo")
                with (
                    mock.patch.object(wrapper.filedialog, "askdirectory", return_value=temp_dir),
                    mock.patch.object(wrapper, "save_local_config"),
                    mock.patch.object(app, "scan_folder", return_value=True),
                ):
                    app.choose_folder()
                self.assertIsNone(app._last_apply_undo)
                self.assertNotIn("before", history_path.read_text(encoding="utf-8") if history_path.exists() else "")
                self.assertNotIn("after", history_path.read_text(encoding="utf-8") if history_path.exists() else "")
            finally:
                if not app.lifecycle.closed:
                    app.on_close()
            self.assertIsNone(app._last_apply_undo)


if __name__ == "__main__":
    unittest.main()
