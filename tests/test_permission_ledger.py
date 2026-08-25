import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class PermissionLedgerTests(unittest.TestCase):
    def make_snapshot(self, root, run_id="ledger-run"):
        return wrapper.create_run_snapshot(
            project_root=root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            task_id=f"task-{run_id}",
            session_id=f"session-{run_id}",
            request_text="safe request; raw file content must never be recorded",
        )

    def make_record(self, run_id="ledger-run", sequence=1, category="inspect", decision="allow"):
        return wrapper.PermissionDecision(
            category=category,
            decision=decision,
            run_id=run_id,
            task_id=f"task-{run_id}",
            session_id=f"session-{run_id}",
            timestamp="2026-08-25T12:00:00Z",
            sequence=sequence,
            policy_outcome="preset" if category == "verify_policy" else "not_applicable",
        )

    def test_immutable_redacted_round_trip_has_only_safe_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = wrapper.PermissionDecisionLedger()
            ledger.bind_snapshot(self.make_snapshot(Path(temp_dir)))
            record = self.make_record()
            self.assertIs(ledger.append(record), record)
            encoded = ledger.to_json().decode("utf-8")
            parsed = json.loads(encoded)
            self.assertEqual(
                set(parsed[0]),
                {
                    "category",
                    "decision",
                    "run_id",
                    "task_id",
                    "session_id",
                    "timestamp",
                    "sequence",
                    "policy_outcome",
                },
            )
            self.assertNotIn("command", encoded)
            self.assertNotIn("path", encoded)
            self.assertNotIn("PRIVATE_FILE_CONTENT", encoded)
            self.assertNotIn("Bearer raw-token", encoded)
            with self.assertRaises((AttributeError, TypeError)):
                record.decision = "deny"

    def test_categories_and_decisions_are_bounded_and_policy_is_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = wrapper.PermissionDecisionLedger(max_records=4, max_bytes=600)
            ledger.bind_snapshot(self.make_snapshot(Path(temp_dir)))
            for index, (category, decision) in enumerate(
                (
                    ("inspect", "allow"),
                    ("verify", "deny"),
                    ("verify_policy", "allow"),
                    ("apply", "deny"),
                    ("undo", "cancel"),
                    ("inspect", "allow"),
                ),
                start=1,
            ):
                self.assertIsNotNone(
                    ledger.append(
                        self.make_record(
                            sequence=index,
                            category=category,
                            decision=decision,
                        )
                    )
                )
            self.assertLessEqual(len(ledger.records), 4)
            self.assertLessEqual(len(ledger.to_json()), 600)
            self.assertIn("undo:cancel", ledger.summary_text())
            self.assertLessEqual(len(ledger.summary_text()), wrapper.LOCAL_COMMAND_MAX_RESULT_CHARS)
            with self.assertRaises(ValueError):
                wrapper.PermissionDecision("inspect", "allow", "Authorization: Bearer secret")
            with self.assertRaises(ValueError):
                wrapper.PermissionDecision("inspect", "allow", "ledger-run", policy_outcome="command")

    def test_stale_cross_run_detach_and_close_do_not_append(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            ledger = wrapper.PermissionDecisionLedger()
            ledger.bind_snapshot(self.make_snapshot(root, "run-a"))
            self.assertIsNone(ledger.append(self.make_record("run-b")))
            self.assertIsNone(ledger.append(self.make_record(), is_current=lambda: False))
            self.assertEqual(ledger.records, ())
            ledger.bind_snapshot(self.make_snapshot(root, "run-a"))
            self.assertIsNotNone(ledger.append(self.make_record("run-a")))
            ledger.detach()
            self.assertIsNone(ledger.append(self.make_record()))
            ledger.bind_snapshot(self.make_snapshot(root, "run-a"))
            ledger.close()
            self.assertIsNone(ledger.append(self.make_record("run-a")))
            self.assertEqual(ledger.records, ())

    def test_report_includes_only_safe_permission_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            snapshot = self.make_snapshot(root)
            handoff = wrapper.build_evidence_handoff(
                snapshot,
                task_state=wrapper.TASK_STATE_REVIEW,
                outcome=wrapper.TASK_STATE_REVIEW,
            )
            records = (
                self.make_record(category="inspect"),
                self.make_record(category="verify", decision="cancel", sequence=2),
                self.make_record(category="verify_policy", sequence=3),
            )
            payload = wrapper.build_task_report_payload(
                snapshot=snapshot,
                handoff=handoff,
                permission_decisions=records,
            )
            self.assertIn("permissions", payload)
            self.assertEqual(payload["counts"]["permission_records"], 3)
            self.assertTrue(all(set(item) == set(records[0].to_dict()) for item in payload["permissions"]))
            serialized = wrapper.serialize_task_report(payload).decode("utf-8")
            for forbidden in ("content", "diff", "stream", "raw output", "original_bytes", "raw command"):
                self.assertNotIn(forbidden, serialized.casefold())


class PermissionLedgerUiTests(unittest.TestCase):
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
        self.app.selected_folder.set(str(self.root))
        self.snapshot = wrapper.create_run_snapshot(
            project_root=self.root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="ui-ledger-run",
            task_id="ui-ledger-task",
            session_id="ui-ledger-session",
            request_text="safe UI ledger task",
        )
        self.app._activate_run(self.snapshot)

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def test_permissions_summary_is_bounded_read_only(self):
        self.app._record_permission_decision("inspect", "allow")
        self.app._record_permission_decision("verify", "cancel")
        self.app._record_permission_decision("apply", "deny")
        before = len(self.app.permission_ledger.records)
        result = self.app._local_command_permissions()
        self.assertIn("inspect:allow", result)
        self.assertIn("verify:cancel", result)
        self.assertIn("apply:deny", result)
        self.assertLessEqual(len(result), wrapper.LOCAL_COMMAND_MAX_RESULT_CHARS)
        self.assertEqual(len(self.app.permission_ledger.records), before)
        self.assertIsNone(self.app.pending_proposal)

    def test_explicit_inspect_and_verification_denials_reach_timeline_only(self):
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "awaiting permission")
        self.app.inspect_request = wrapper.InspectRequest(
            "Read one safe file",
            ("README.md",),
            run_id=self.snapshot.run_id,
        )
        self.assertTrue(self.app.deny_inspect())
        self.assertTrue(
            any(
                entry["kind"] == "permission_decision"
                and "category=inspect; decision=deny" in entry["text"]
                for entry in self.app.run_timeline
            )
        )

        next_snapshot = wrapper.create_run_snapshot(
            project_root=self.root,
            extra_context_paths=(),
            session_messages=(),
            apply_mode=wrapper.APPLY_MODE_REVIEW,
            run_id="ui-ledger-run-2",
            task_id="ui-ledger-task-2",
            session_id="ui-ledger-session-2",
            request_text="safe verification task",
        )
        self.app._activate_run(next_snapshot)
        self.app.set_task_state(wrapper.TASK_STATE_RUNNING, "awaiting permission")
        self.app.verification_request = wrapper.VerificationRequest(
            "python --version",
            run_id=next_snapshot.run_id,
        )
        self.assertTrue(self.app.deny_verification())
        self.assertTrue(
            any(
                entry["kind"] == "permission_decision"
                and "category=verify; decision=deny" in entry["text"]
                for entry in self.app.run_timeline
            )
        )
        self.assertIsNone(self.app.pending_proposal)

    def test_apply_and_undo_explicit_decisions_have_no_model_or_process_side_effect(self):
        proposal = wrapper.create_pending_proposal(
            self.snapshot,
            ({"path": "safe.txt", "content": "new"},),
        )
        self.app.pending_proposal = proposal
        self.app.set_task_state(wrapper.TASK_STATE_REVIEW, "review")
        with (
            mock.patch.object(wrapper, "apply_proposal_transactionally", return_value=0),
            mock.patch.object(self.app, "scan_folder"),
        ):
            self.app.apply_pending()
        self.assertTrue(
            any(
                entry["kind"] == "permission_decision"
                and "category=apply; decision=allow" in entry["text"]
                for entry in self.app.run_timeline
            )
        )

        undo = wrapper.UndoTransaction(
            transaction_id="undo-1",
            project_root=self.root,
            source_run_id=self.snapshot.run_id,
            files=(),
            created_at="2026-08-25T12:00:00Z",
        )
        self.app._last_apply_undo = undo
        with (
            mock.patch.object(wrapper.messagebox, "askyesno", return_value=False),
            mock.patch.object(wrapper, "restore_undo_transactionally") as restore,
        ):
            self.assertFalse(self.app.undo_last_apply())
        restore.assert_not_called()
        self.assertTrue(
            any(
                entry["kind"] == "permission_decision"
                and "category=undo; decision=deny" in entry["text"]
                for entry in self.app.run_timeline
            )
        )
        self.assertIsNone(self.app.pending_proposal)


if __name__ == "__main__":
    unittest.main()
