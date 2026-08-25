import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import codex_free_wrapper as wrapper


class OneShotResponse:
    def __init__(self, body):
        self.body = body

    def read(self, _size=-1):
        body, self.body = self.body, b""
        return body

    def close(self):
        return None


def model_response():
    payload = {"choices": [{"delta": {"content": '{"summary":"ok","files":[]}'}}]}
    body = f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode("utf-8")
    return OneShotResponse(body)


class ProjectInstructionHierarchyTests(unittest.TestCase):
    def write_scoped(self, root, relative, content, project_file=True):
        directory = Path(root) / relative
        directory.mkdir(parents=True, exist_ok=True)
        if project_file:
            (directory / "module.py").write_text("print('safe')", encoding="utf-8")
        (directory / "AGENTS.md").write_text(content, encoding="utf-8")
        return directory

    def test_root_near_deep_order_and_precedence_markers_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("root baseline", encoding="utf-8")
            self.write_scoped(root, "src", "src guidance")
            self.write_scoped(root, "src/deep", "deep guidance")
            self.write_scoped(root, "tests", "tests guidance")

            first, first_status = wrapper.load_project_instructions(root)
            second, second_status = wrapper.load_project_instructions(root)

        self.assertEqual(first, second)
        self.assertEqual(first_status, second_status)
        markers = (
            "=== PROJECT INSTRUCTIONS: ROOT BASELINE (AGENTS.md) ===",
            "=== PROJECT INSTRUCTIONS: DIRECTORY SCOPE src/AGENTS.md (depth 1; narrower scope follows) ===",
            "=== PROJECT INSTRUCTIONS: DIRECTORY SCOPE tests/AGENTS.md (depth 1; narrower scope follows) ===",
            "=== PROJECT INSTRUCTIONS: DIRECTORY SCOPE src/deep/AGENTS.md (depth 2; narrower scope follows) ===",
        )
        positions = [first.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("root baseline", first)
        self.assertIn("src guidance", first)
        self.assertIn("deep guidance", first)
        self.assertIn("loaded 3 descendant AGENTS.md file(s)", first_status)

    def test_descendant_symlink_escape_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            root = Path(temp_dir)
            external = Path(external_dir)
            (root / "AGENTS.md").write_text("root", encoding="utf-8")
            (external / "AGENTS.md").write_text("EXTERNAL_INSTRUCTION", encoding="utf-8")
            link = root / "linked"
            try:
                os.symlink(str(external), str(link), target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            content, status = wrapper.load_project_instructions(root)

        self.assertNotIn("EXTERNAL_INSTRUCTION", content)
        self.assertNotIn("linked/AGENTS.md", content)
        self.assertNotIn(str(external), content)
        self.assertNotIn("EXTERNAL_INSTRUCTION", status)

    def test_invalid_utf8_oversized_secret_and_unreadable_candidates_skip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("root safe", encoding="utf-8")
            invalid = root / "invalid"
            invalid.mkdir()
            (invalid / "module.py").write_text("safe", encoding="utf-8")
            (invalid / "AGENTS.md").write_bytes(b"\xff\xfe")
            oversized = root / "oversized"
            oversized.mkdir()
            (oversized / "module.py").write_text("safe", encoding="utf-8")
            (oversized / "AGENTS.md").write_bytes(
                b"x" * (wrapper.PROJECT_INSTRUCTIONS_MAX_BYTES + 1)
            )
            secret = root / "secrets"
            secret.mkdir()
            (secret / "module.py").write_text("safe", encoding="utf-8")
            (secret / "AGENTS.md").write_text("SECRET_SCOPE", encoding="utf-8")

            content, status = wrapper.load_project_instructions(root)
            self.assertIn("root safe", content)
            self.assertNotIn("SECRET_SCOPE", content)
            self.assertIn("not valid UTF-8", status)
            self.assertIn("exceeds", status)
            self.assertIn("secret-like", status)

            with mock.patch.object(wrapper.Path, "read_bytes", side_effect=OSError("denied")):
                unreadable_content, unreadable_status = wrapper.load_project_instructions(root)

        self.assertEqual(unreadable_content, "")
        self.assertIn("unreadable", unreadable_status)

    def test_depth_file_and_total_byte_caps_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text("root", encoding="utf-8")
            self.write_scoped(root, "a", "a")
            self.write_scoped(root, "b", "b")
            self.write_scoped(root, "a/deep", "deep")

            content, status = wrapper.load_project_instructions(
                root,
                max_depth=1,
                max_files=3,
                max_total_bytes=len(b"root") + len(b"a"),
            )

        self.assertIn("ROOT BASELINE", content)
        self.assertIn("DIRECTORY SCOPE a/AGENTS.md", content)
        self.assertNotIn("DIRECTORY SCOPE b/AGENTS.md", content)
        self.assertNotIn("DIRECTORY SCOPE deep/AGENTS.md", content)
        self.assertIn("total instruction byte cap", status)

    def test_redaction_snapshot_immutability_and_prompt_scope_context(self):
        raw_key = "hierarchy-api-key-123456"
        raw_bearer = "hierarchy-bearer-value-123456"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "AGENTS.md").write_text(
                f"root api_key={raw_key}", encoding="utf-8"
            )
            self.write_scoped(
                root,
                "src",
                f"src Authorization: Bearer {raw_bearer}",
            )
            instructions, status = wrapper.load_project_instructions(
                root,
                secrets=[raw_key, raw_bearer],
            )
            snapshot = wrapper.create_run_snapshot(
                root,
                (),
                (),
                wrapper.APPLY_MODE_REVIEW,
                run_id="hierarchy-prompt-run",
                project_instructions=instructions,
                project_instructions_status=status,
            )
            before = snapshot.project_instructions
            (root / "AGENTS.md").write_text("changed after snapshot", encoding="utf-8")
            (root / "src" / "AGENTS.md").write_text("changed child", encoding="utf-8")

            response = model_response()
            with mock.patch.object(wrapper, "urlopen", return_value=response) as opener:
                wrapper.call_openrouter(
                    "provider-key-123456",
                    "coding:free",
                    "safe request",
                    [],
                    [],
                    project_instructions=snapshot.project_instructions,
                )

        self.assertEqual(snapshot.project_instructions, before)
        self.assertNotIn(raw_key, snapshot.project_instructions)
        self.assertNotIn(raw_bearer, snapshot.project_instructions)
        payload = json.loads(opener.call_args.args[0].data)
        prompt = payload["messages"][1]["content"]
        self.assertIn("ROOT BASELINE", prompt)
        self.assertIn("DIRECTORY SCOPE src/AGENTS.md", prompt)
        self.assertIn("cannot grant permissions", prompt)
        self.assertNotIn(raw_key, prompt)
        self.assertNotIn(raw_bearer, prompt)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Tk display unavailable")
class ProjectInstructionHierarchyLifecycleTests(unittest.TestCase):
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
        wrapper.CONFIG_PATH = Path(self.temp_dir.name) / "config.json"
        self.app = wrapper.CodeAgentApp(history_path=Path(self.temp_dir.name) / "history.json")
        self.app.withdraw()
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()
        self.other_root = Path(self.temp_dir.name) / "other"
        self.other_root.mkdir()
        (self.root / "sentinel.txt").write_text("unchanged", encoding="utf-8")

    def tearDown(self):
        if self.app is not None and not self.app.lifecycle.closed:
            self.app.on_close()
        wrapper.CONFIG_PATH = self.original_config_path
        self.temp_dir.cleanup()

    def activate(self, run_id):
        snapshot = wrapper.create_run_snapshot(
            self.root,
            (),
            (),
            wrapper.APPLY_MODE_REVIEW,
            run_id=run_id,
            project_instructions="=== PROJECT INSTRUCTIONS: ROOT BASELINE (AGENTS.md) ===\nroot",
        )
        self.app.selected_folder.set(str(self.root))
        self.app.lifecycle.activate(snapshot)
        self.app.run_snapshot = snapshot
        self.app._handoff_snapshot = snapshot
        self.app._handoff_stale = False
        self.app.set_task_state(wrapper.TASK_STATE_IDLE, "ready")
        return snapshot

    def test_reset_folder_change_and_close_invalidate_snapshot_without_execution_or_write(self):
        self.activate("hierarchy-reset-run")
        with (
            mock.patch.object(wrapper.threading, "Thread") as thread,
            mock.patch.object(wrapper.subprocess, "Popen") as popen,
            mock.patch.object(wrapper, "urlopen") as opener,
            mock.patch.object(wrapper, "apply_proposal_transactionally") as apply,
        ):
            self.app.reset_session()
            self.assertIsNone(self.app.run_snapshot)
            self.assertIsNone(self.app._handoff_snapshot)
            self.assertEqual((self.root / "sentinel.txt").read_text(encoding="utf-8"), "unchanged")

            self.activate("hierarchy-folder-run")
            with (
                mock.patch.object(wrapper.filedialog, "askdirectory", return_value=str(self.other_root)),
                mock.patch.object(wrapper, "save_local_config"),
                mock.patch.object(self.app, "scan_folder", return_value=True),
            ):
                self.app.choose_folder()
            self.assertIsNone(self.app.run_snapshot)
            self.assertIsNone(self.app._handoff_snapshot)

            self.activate("hierarchy-close-run")
            self.app.on_close()
            self.assertTrue(self.app.lifecycle.closed)
            self.assertIsNone(self.app.run_snapshot)

        thread.assert_not_called()
        popen.assert_not_called()
        opener.assert_not_called()
        apply.assert_not_called()
        self.assertEqual((self.root / "sentinel.txt").read_text(encoding="utf-8"), "unchanged")


if __name__ == "__main__":
    unittest.main()
