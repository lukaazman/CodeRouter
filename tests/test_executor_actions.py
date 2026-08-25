import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


def final_response(path="notes.txt", content="final content"):
    return {
        "action": "final",
        "summary": "A bounded final response.",
        "files": [{"path": path, "content": content}],
    }


class ExecutorActionParserTests(unittest.TestCase):
    def test_final_and_inspect_are_strictly_separate(self):
        final = wrapper.parse_executor_response(json.dumps(final_response()))
        self.assertEqual(final["action"], "final")
        self.assertEqual(final["files"][0]["path"], "notes.txt")
        inspect = wrapper.parse_executor_response(
            json.dumps({"action": "inspect", "summary": "Read one source file.", "paths": ["src/app.py"]})
        )
        self.assertIsInstance(inspect, wrapper.InspectRequest)
        self.assertEqual(inspect.paths, ("src/app.py",))

    def test_malformed_unknown_and_extra_fields_fail_closed(self):
        invalid = [
            "",
            "not json",
            {"action": "unknown", "summary": "x", "files": []},
            {**final_response(), "extra": True},
            {"action": "inspect", "summary": "x", "paths": ["a.py"], "files": []},
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    wrapper.parse_executor_response(value if isinstance(value, str) else json.dumps(value))

    def test_inspect_paths_reject_external_traversal_protected_and_secret_like(self):
        bad_paths = [
            "C:/outside.py",
            "../outside.py",
            "__external_context__/context.txt",
            ".git/config",
            ".env",
            "local_config.json",
            "AGENTS.md",
            "credentials.txt",
            "private.pem",
        ]
        for path in bad_paths:
            with self.subTest(path=path):
                response = {"action": "inspect", "summary": "read", "paths": [path]}
                with self.assertRaises(ValueError):
                    wrapper.parse_executor_response(json.dumps(response))

    def test_final_paths_use_the_same_write_guards_and_secrets_are_rejected(self):
        for path in ("../x.py", ".env", "__external_context__/x.py", "secret.txt"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    wrapper.parse_executor_response(json.dumps(final_response(path=path)))
        with self.assertRaises(ValueError):
            wrapper.parse_executor_response(json.dumps(final_response(content="Authorization: Bearer raw-secret")))

    def test_inspect_summaries_and_collected_content_fail_closed_for_credentials(self):
        for summary in (
            "token=raw-token-value",
            "Authorization: Bearer raw-bearer-value",
            "-----BEGIN PRIVATE KEY-----\nraw\n-----END PRIVATE KEY-----",
        ):
            with self.subTest(summary=summary):
                with self.assertRaises(ValueError):
                    wrapper.parse_executor_response(
                        json.dumps({"action": "inspect", "summary": summary, "paths": ["notes.txt"]})
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "notes.txt"
            target.write_text(
                "token=raw-token-value\n"
                "Authorization: Bearer raw-bearer-value\n"
                "-----BEGIN PRIVATE KEY-----\nraw\n-----END PRIVATE KEY-----",
                encoding="utf-8",
            )
            files, _status = wrapper.collect_inspect_files(
                temp_dir,
                ("notes.txt",),
                secrets=("worker-key-123456",),
            )
            content = "\n".join(item.content for item in files)
            self.assertNotIn("raw-token-value", content)
            self.assertNotIn("raw-bearer-value", content)
            self.assertNotIn("BEGIN PRIVATE KEY", content)
            self.assertIn("[redacted]", content)


class ExecutorInspectWorkerTests(unittest.TestCase):
    class Host:
        def __init__(self, root, run_id="inspect-run"):
            self.api_key = "worker-key-123456"
            self.work_queue = __import__("queue").Queue()
            self.lifecycle = wrapper.RunLifecycle()
            self.snapshot = wrapper.create_run_snapshot(
                root, (), (), wrapper.APPLY_MODE_REVIEW, run_id=run_id, request_text="inspect request"
            )
            self.lifecycle.activate(self.snapshot)

        def _run_is_current(self, run_id):
            return self.lifecycle.accepts(run_id)

    @staticmethod
    def drain(host):
        events = []
        while not host.work_queue.empty():
            events.append(host.work_queue.get_nowait())
        return events

    def test_one_round_inspect_has_no_proposal_diff_apply_or_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = (root / "notes.txt").write_text("original", encoding="utf-8")
            host = self.Host(root)
            request = wrapper.InspectRequest("Read the selected file.", ("notes.txt",), host.snapshot.run_id)
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", return_value=(request, "safe:free")),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, host.snapshot, "inspect request", None, True)
            events = self.drain(host)
            kinds = [event.kind for event in events]
            self.assertIn("inspect_request", kinds)
            self.assertNotIn("proposal", kinds)
            self.assertNotIn("diffs", kinds)
            self.assertNotIn("auto_apply", kinds)
            self.assertEqual((root / "notes.txt").read_text(encoding="utf-8"), "original")
            self.assertEqual(original, len("original"))

    def test_allow_continuation_can_create_final_proposal_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "notes.txt"
            target.write_text("original", encoding="utf-8")
            host = self.Host(root)
            next_snapshot = wrapper.create_run_snapshot(
                root, (), (), wrapper.APPLY_MODE_REVIEW, run_id=host.snapshot.run_id,
                request_text="inspect request", inspect_round=1,
            )
            request = wrapper.InspectRequest("Read the selected file.", ("notes.txt",), host.snapshot.run_id)
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(
                    wrapper,
                    "collect_inspect_files",
                    return_value=(
                        (wrapper.SourceFile(target, "notes.txt", "original"),),
                        "Inspect context loaded: 1 file(s), 8 bytes.",
                    ),
                ),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", return_value=(final_response("notes.txt", "changed"), "safe:free")) as provider,
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, next_snapshot, "inspect request", request, True)
            events = self.drain(host)
            self.assertTrue(any(event.kind == "proposal" for event in events))
            self.assertNotIn("auto_apply", [event.kind for event in events])
            provider.assert_called_once()
            self.assertTrue(provider.call_args.kwargs["strict_actions"])
            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_allow_continuation_failure_rolls_back_without_proposal_or_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            host = self.Host(Path(temp_dir))
            snapshot = wrapper.create_run_snapshot(
                temp_dir, (), (), wrapper.APPLY_MODE_REVIEW, run_id=host.snapshot.run_id,
                request_text="inspect request", inspect_round=1,
            )
            request = wrapper.InspectRequest("Read the selected file.", ("notes.txt",), snapshot.run_id)
            with mock.patch.object(
                wrapper,
                "collect_inspect_files",
                side_effect=RuntimeError("Authorization: Bearer raw-bearer-value"),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "inspect request", request, True)
            events = self.drain(host)
            kinds = [event.kind for event in events]
            self.assertIn("inspect_rollback", kinds)
            self.assertNotIn("proposal", kinds)
            self.assertNotIn("diffs", kinds)
            self.assertNotIn("auto_apply", kinds)
            rollback = next(event.payload for event in events if event.kind == "inspect_rollback")
            self.assertNotIn("raw-bearer-value", rollback)
            self.assertNotIn("Authorization: Bearer raw-bearer-value", rollback)

    def test_cancel_after_inspect_collection_prevents_provider_and_side_effects(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            host = self.Host(Path(temp_dir))
            snapshot = wrapper.create_run_snapshot(
                temp_dir, (), (), wrapper.APPLY_MODE_REVIEW, run_id=host.snapshot.run_id,
                request_text="inspect request", inspect_round=1,
            )
            request = wrapper.InspectRequest("Read the selected file.", ("notes.txt",), snapshot.run_id)

            def cancel_after_collection(*_args, **_kwargs):
                host.lifecycle.invalidate()
                return (), "Inspect context loaded: 0 file(s), 0 bytes."

            provider = mock.Mock(return_value=(final_response(), "safe:free"))
            with (
                mock.patch.object(wrapper, "collect_inspect_files", side_effect=cancel_after_collection),
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", provider),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "inspect request", request, True)
            events = self.drain(host)
            self.assertFalse(provider.called)
            self.assertNotIn("proposal", [event.kind for event in events])
            self.assertNotIn("diffs", [event.kind for event in events])
            self.assertNotIn("auto_apply", [event.kind for event in events])

    def test_cancel_after_provider_return_prevents_proposal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            host = self.Host(Path(temp_dir))
            snapshot = wrapper.create_run_snapshot(
                temp_dir, (), (), wrapper.APPLY_MODE_REVIEW, run_id=host.snapshot.run_id,
                request_text="inspect request", inspect_round=1,
            )
            request = wrapper.InspectRequest("Read the selected file.", ("notes.txt",), snapshot.run_id)

            def cancel_after_provider(*_args, **_kwargs):
                host.lifecycle.invalidate()
                return final_response(), "safe:free"

            provider = mock.Mock(side_effect=cancel_after_provider)
            with (
                mock.patch.object(
                    wrapper,
                    "collect_inspect_files",
                    return_value=((), "Inspect context loaded: 0 file(s), 0 bytes."),
                ),
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", provider),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "inspect request", request, True)
            events = self.drain(host)
            self.assertTrue(provider.called)
            self.assertNotIn("proposal", [event.kind for event in events])
            self.assertNotIn("diffs", [event.kind for event in events])
            self.assertNotIn("auto_apply", [event.kind for event in events])

    def test_cancel_during_proposal_or_diff_construction_has_no_usable_side_effect(self):
        for phase in ("proposal", "diff"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp_dir:
                target = Path(temp_dir) / "notes.txt"
                target.write_text("original", encoding="utf-8")
                host = self.Host(Path(temp_dir))
                snapshot = wrapper.create_run_snapshot(
                    temp_dir, (), (), wrapper.APPLY_MODE_REVIEW, run_id=host.snapshot.run_id,
                    request_text="inspect request", inspect_round=1,
                )
                request = wrapper.InspectRequest("Read the selected file.", ("notes.txt",), snapshot.run_id)
                real_create = wrapper.create_pending_proposal
                real_render = wrapper.render_diff_by_path

                def cancel_create(*args, **kwargs):
                    proposal = real_create(*args, **kwargs)
                    host.lifecycle.invalidate()
                    return proposal

                def cancel_render(*args, **kwargs):
                    diff = real_render(*args, **kwargs)
                    host.lifecycle.invalidate()
                    return diff

                patcher = (
                    mock.patch.object(wrapper, "create_pending_proposal", side_effect=cancel_create)
                    if phase == "proposal"
                    else mock.patch.object(wrapper, "render_diff_by_path", side_effect=cancel_render)
                )
                with (
                    mock.patch.object(
                        wrapper,
                        "collect_inspect_files",
                        return_value=((), "Inspect context loaded: 0 file(s), 0 bytes."),
                    ),
                    mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                    mock.patch.object(wrapper, "call_openrouter_with_fallback", return_value=(final_response(), "safe:free")),
                    patcher,
                ):
                    wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "inspect request", request, True)
                events = self.drain(host)
                self.assertNotIn("proposal", [event.kind for event in events])
                self.assertNotIn("diffs", [event.kind for event in events])
                self.assertNotIn("auto_apply", [event.kind for event in events])
                self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_second_inspect_response_is_blocked_after_round_one(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            host = self.Host(Path(temp_dir))
            snapshot = wrapper.create_run_snapshot(
                temp_dir, (), (), wrapper.APPLY_MODE_REVIEW, run_id=host.snapshot.run_id,
                request_text="inspect request", inspect_round=1,
            )
            request = wrapper.InspectRequest("again", ("notes.txt",), snapshot.run_id)
            with (
                mock.patch.object(wrapper, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(wrapper, "collect_inspect_files", return_value=((), "Inspect context loaded: 0 file(s), 0 bytes.")),
                mock.patch.object(wrapper, "call_openrouter_with_fallback", return_value=(request, "safe:free")),
            ):
                wrapper.CodeAgentApp._run_agent_worker(host, snapshot, "inspect request", request, True)
            events = self.drain(host)
            self.assertNotIn("inspect_request", [event.kind for event in events])
            self.assertNotIn("proposal", [event.kind for event in events])
            self.assertTrue(any(event.kind == "task_state" and event.payload[0] == wrapper.TASK_STATE_ERROR for event in events))


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ExecutorInspectUiTests(unittest.TestCase):
    def make_app(self, root):
        return wrapper.CodeAgentApp(history_path=root / "history.json")

    def prepare_request(self, app, root, run_id="ui-inspect"):
        snapshot = wrapper.create_run_snapshot(
            root, (), (), wrapper.APPLY_MODE_REVIEW, run_id=run_id, request_text="inspect"
        )
        app.lifecycle.activate(snapshot)
        app.run_resources.create(snapshot.run_id)
        app.run_snapshot = snapshot
        app.task_state = wrapper.TASK_STATE_RUNNING
        request = wrapper.InspectRequest("Read one file.", ("notes.txt",), snapshot.run_id)
        app.inspect_request = request
        app._write_inspect_preview(request)
        return snapshot, request

    def test_allow_deny_and_reset_clear_pending_request_without_starting_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot = wrapper.create_run_snapshot(root, (), (), wrapper.APPLY_MODE_REVIEW, run_id="ui-inspect", request_text="inspect")
                app.lifecycle.activate(snapshot)
                app.run_resources.create(snapshot.run_id)
                app.run_snapshot = snapshot
                app.task_state = wrapper.TASK_STATE_RUNNING
                app.inspect_request = wrapper.InspectRequest("Read one file.", ("notes.txt",), snapshot.run_id)
                app._write_inspect_preview(app.inspect_request)
                with mock.patch.object(app, "_start_run_worker", return_value=object()) as starter:
                    self.assertTrue(app.allow_inspect())
                    starter.assert_called_once()
                self.assertIsNone(app.inspect_request)
                self.assertEqual(app.lifecycle.active_snapshot.inspect_round, 1)
                app.inspect_request = wrapper.InspectRequest("stale", ("notes.txt",), snapshot.run_id)
                app.reset_session()
                self.assertIsNone(app.inspect_request)
                self.assertFalse(app.allow_inspect())
            finally:
                app.destroy()

    def test_allow_start_failure_rolls_back_continuation_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                self.prepare_request(app, root, run_id="allow-failure")
                with mock.patch.object(app, "_start_run_worker", return_value=None):
                    self.assertFalse(app.allow_inspect())
                self.assertIsNone(app.inspect_request)
                self.assertIsNone(app.run_snapshot)
                self.assertIsNone(app.lifecycle.active_snapshot)
                self.assertIsNone(app.pending_proposal)
                self.assertEqual(app.task_state, wrapper.TASK_STATE_ERROR)
            finally:
                app.destroy()

    def test_reset_filters_stale_inspect_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            try:
                snapshot, request = self.prepare_request(app, root, run_id="reset-stale")
                app.reset_session()
                app.work_queue.put(wrapper.RunEvent(snapshot.run_id, "inspect_request", request, 1))
                app._poll_queue()
                self.assertIsNone(app.inspect_request)
                self.assertIsNone(app.lifecycle.active_snapshot)
            finally:
                app.destroy()

    def test_folder_change_clears_inspect_continuation(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as next_dir:
            root = Path(temp_dir)
            next_root = Path(next_dir)
            app = self.make_app(root)
            try:
                self.prepare_request(app, root, run_id="folder-change")
                app.task_state = wrapper.TASK_STATE_REVIEW
                with (
                    mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(next_root)),
                    mock.patch.object(wrapper, "save_local_config"),
                    mock.patch.object(app, "scan_folder", return_value=True),
                ):
                    app.choose_folder()
                self.assertIsNone(app.inspect_request)
                self.assertIsNone(app.run_snapshot)
                self.assertIsNone(app.lifecycle.active_snapshot)
                self.assertEqual(Path(app.selected_folder.get()).resolve(), next_root.resolve())
            finally:
                app.destroy()

    def test_close_clears_inspect_continuation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_app(root)
            self.prepare_request(app, root, run_id="close-inspect")
            app.on_close()
            self.assertTrue(app.lifecycle.closed)
            self.assertIsNone(app.inspect_request)


if __name__ == "__main__":
    unittest.main()
