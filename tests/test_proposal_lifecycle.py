import queue
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class ProposalLifecycleTests(unittest.TestCase):
    def make_snapshot(self, root, run_id="run-1", apply_mode=wrapper.APPLY_MODE_REVIEW):
        return wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=({"role": "user", "content": "keep this history"},),
            apply_mode=apply_mode,
            run_id=run_id,
        )

    def make_proposal(self, root, edits, run_id="run-1"):
        return wrapper.create_pending_proposal(self.make_snapshot(root, run_id=run_id), edits)

    def test_snapshot_and_queue_event_are_run_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = self.make_snapshot(root)
            self.assertEqual(snapshot.session_history, (("user", "keep this history"),))
            self.assertIsInstance(snapshot.extra_context_paths, tuple)

            events = queue.Queue()
            wrapper.queue_run_event(events, snapshot.run_id, "summary", "old")
            event = events.get_nowait()
            self.assertEqual(event[0], snapshot.run_id)
            self.assertTrue(wrapper.event_matches_run(event, snapshot.run_id))
            self.assertFalse(wrapper.event_matches_run(event, "new-run"))

    def test_reset_and_close_invalidate_worker_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lifecycle = wrapper.RunLifecycle()
            first = self.make_snapshot(Path(temp_dir), run_id="first")
            lifecycle.activate(first)
            self.assertTrue(lifecycle.accepts(first.run_id))
            self.assertEqual(lifecycle.invalidate(), first.run_id)
            self.assertFalse(lifecycle.accepts(first.run_id))

            second = self.make_snapshot(Path(temp_dir), run_id="second")
            lifecycle.activate(second)
            self.assertTrue(lifecycle.accepts(second.run_id))
            lifecycle.close()
            self.assertTrue(lifecycle.closed)
            self.assertFalse(lifecycle.accepts(second.run_id))
            self.assertFalse(wrapper.event_matches_run((second.run_id, "log", "late"), second.run_id, lifecycle.closed))

    def test_apply_requires_review_run_and_matching_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            other_root = root / "other"
            other_root.mkdir()
            target = root / "note.txt"
            target.write_text("before", encoding="utf-8")
            proposal = self.make_proposal(root, [{"path": "note.txt", "content": "after"}])

            with self.assertRaisesRegex(ValueError, "REVIEW"):
                wrapper.apply_proposal_transactionally(proposal, root, wrapper.TASK_STATE_IDLE, proposal.run_id)
            with self.assertRaisesRegex(ValueError, "stale"):
                wrapper.apply_proposal_transactionally(proposal, root, wrapper.TASK_STATE_REVIEW, "other-run")
            with self.assertRaisesRegex(ValueError, "root"):
                wrapper.apply_proposal_transactionally(proposal, other_root, wrapper.TASK_STATE_REVIEW, proposal.run_id)
            self.assertEqual(target.read_text(encoding="utf-8"), "before")

    def test_changed_file_precondition_blocks_apply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "note.txt"
            target.write_text("before", encoding="utf-8")
            proposal = self.make_proposal(root, [{"path": "note.txt", "content": "after"}])
            target.write_text("changed outside proposal", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "changed"):
                wrapper.apply_proposal_transactionally(
                    proposal,
                    root,
                    wrapper.TASK_STATE_REVIEW,
                    proposal.run_id,
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "changed outside proposal")

    def test_protected_and_external_paths_are_rejected(self):
        protected_paths = (
            ".git/config",
            ".env",
            "local_config.json",
            "credentials.key",
            "certificate.pem",
            f"{wrapper.EXTERNAL_CONTEXT_PREFIX}/readme.txt",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = self.make_snapshot(root)
            for path in protected_paths:
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        wrapper.create_pending_proposal(
                            snapshot,
                            [{"path": path, "content": "must not write"}],
                        )

    def test_partial_write_failure_rolls_back_every_file(self):
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
            real_replace = wrapper.os.replace

            def fail_for_second(source, destination):
                if Path(destination).name == "second.txt":
                    raise OSError("simulated second-file write failure")
                return real_replace(source, destination)

            with mock.patch.object(wrapper.os, "replace", side_effect=fail_for_second):
                with self.assertRaisesRegex(OSError, "simulated"):
                    wrapper.apply_proposal_transactionally(
                        proposal,
                        root,
                        wrapper.TASK_STATE_REVIEW,
                        proposal.run_id,
                    )

            self.assertEqual(first.read_text(encoding="utf-8"), "first-before")
            self.assertEqual(second.read_text(encoding="utf-8"), "second-before")
            self.assertEqual(list(root.glob(".*.coderouter-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
