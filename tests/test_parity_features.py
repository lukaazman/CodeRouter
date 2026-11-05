import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import approval
import cli
import edit_ops
import git_tools
import hooks
import memory_files
import mentions
import sessions
import slash_commands
import theme
import ui_kit
import usage


class ChunkedResponse:
    def __init__(self, body):
        self.chunks = iter([body])

    def read(self, _size=-1):
        return next(self.chunks, b"")

    def close(self):
        pass


def streamed(text):
    payload = {"choices": [{"delta": {"content": text}}]}
    return ChunkedResponse(f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n".encode("utf-8"))


class SlashCommandTests(unittest.TestCase):
    def test_split_and_builtin_aliases(self):
        self.assertEqual(slash_commands.split_command("/model auto"), ("model", "auto"))
        self.assertIsNone(slash_commands.split_command("fix the bug"))
        self.assertIsNone(slash_commands.split_command("/"))
        registry = slash_commands.CommandRegistry(home=tempfile.mkdtemp())
        self.assertEqual(registry.resolve("new").name, "clear")
        self.assertEqual(registry.resolve("quit").name, "exit")
        self.assertIn("/compact", registry.help_text())

    def test_custom_commands_load_namespace_and_expand(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root:
            project = Path(root) / ".claude" / "commands" / "frontend"
            project.mkdir(parents=True)
            (project / "review.md").write_text(
                "---\ndescription: Review a component\nargument-hint: <file>\n---\nReview $1 carefully. Notes: $ARGUMENTS\n",
                encoding="utf-8",
            )
            codex = Path(home) / ".codex" / "prompts"
            codex.mkdir(parents=True)
            (codex / "tidy.md").write_text("Tidy imports.", encoding="utf-8")
            (codex / "help.md").write_text("Shadow builtin", encoding="utf-8")
            registry = slash_commands.CommandRegistry(root, home=home)
            command = registry.resolve("frontend:review")
            self.assertEqual(command.kind, "custom")
            self.assertIn("Review a component", command.description)
            self.assertEqual(
                slash_commands.expand_custom_command(command, "app.tsx now"),
                "Review app.tsx carefully. Notes: app.tsx now",
            )
            tidy = registry.resolve("tidy")
            self.assertEqual(slash_commands.expand_custom_command(tidy, "src"), "Tidy imports.\n\nsrc")
            self.assertEqual(registry.resolve("help").kind, "builtin")
            self.assertEqual([c.label for c in registry.complete("/front")], ["/frontend:review"])


class IgnoreRuleTests(unittest.TestCase):
    def test_gitignore_semantics(self):
        import ignore_rules

        rules = ignore_rules.IgnoreRules(["# c", "*.log", "build/", "/dist", "!keep.log", "docs/**/*.tmp", "a?c.txt"])
        self.assertTrue(rules.ignored("x/y.log"))
        self.assertFalse(rules.ignored("keep.log"))
        self.assertTrue(rules.ignored("build/out.js"))
        self.assertTrue(rules.ignored("sub/build/out.js"))
        self.assertFalse(rules.ignored("build.py"))
        self.assertTrue(rules.ignored("dist/a.js"))
        self.assertFalse(rules.ignored("sub/dist/a.js"))
        self.assertTrue(rules.ignored("docs/a/b/c.tmp"))
        self.assertTrue(rules.ignored("abc.txt"))
        self.assertFalse(rules.ignored("src/app.py"))

    def test_collect_files_respects_ignore_files(self):
        import CodeRouter as core

        with tempfile.TemporaryDirectory() as root:
            Path(root, ".gitignore").write_text("generated/\n", encoding="utf-8")
            Path(root, ".coderouterignore").write_text("big.txt\n", encoding="utf-8")
            Path(root, "generated").mkdir()
            Path(root, "generated", "x.py").write_text("x", encoding="utf-8")
            Path(root, "big.txt").write_text("b", encoding="utf-8")
            Path(root, "main.py").write_text("m", encoding="utf-8")
            names = [f.relative_path for f in core.collect_files(root, 50, 64)]
            self.assertIn("main.py", names)
            self.assertNotIn("generated/x.py", names)
            self.assertNotIn("big.txt", names)


class ExtensionTests(unittest.TestCase):
    def test_skills_agents_styles(self):
        import extensions

        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root:
            skill = Path(root, ".claude", "skills", "pdf-forms")
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: pdf-forms\ndescription: Fill PDF forms and extract fields\n---\nUse pypdf.", encoding="utf-8")
            user_skill = Path(home, ".claude", "skills", "tkinter-motion")
            user_skill.mkdir(parents=True)
            (user_skill / "SKILL.md").write_text("---\ndescription: Animate tkinter widgets smoothly\n---\nUse after().", encoding="utf-8")
            agents = Path(root, ".coderouter", "agents")
            agents.mkdir(parents=True)
            (agents / "reviewer.md").write_text("---\ndescription: Strict reviewer\n---\nBe strict.", encoding="utf-8")
            skills = extensions.load_extensions("skill", root, home)
            self.assertEqual(set(skills), {"pdf-forms", "tkinter-motion"})
            matched = extensions.match_skills(skills, "please extract the fields from this PDF form")
            self.assertEqual([item.name for item in matched], ["pdf-forms"])
            self.assertEqual(extensions.match_skills(skills, "rename a variable"), [])
            forced = extensions.match_skills(skills, "rename", forced=["tkinter-motion"])
            self.assertEqual([item.name for item in forced], ["tkinter-motion"])
            self.assertIn("Use pypdf.", extensions.skills_context(matched))
            agent = extensions.load_extensions("agent", root, home)["reviewer"]
            self.assertIn("Be strict.", extensions.agent_context(agent))


class WebFetchTests(unittest.TestCase):
    def test_html_to_text_and_validation(self):
        import web_fetch

        title, text = web_fetch.html_to_text("<html><head><title>Docs</title><style>x{}</style></head><body><h1>API</h1><p>Use <b>get()</b> &amp; set().</p><script>bad()</script><ul><li>one</li></ul></body></html>")
        self.assertEqual(title, "Docs")
        self.assertIn("# API", text)
        self.assertIn("Use get() & set().", text)
        self.assertNotIn("bad()", text)
        self.assertIn("- one", text)
        with self.assertRaises(ValueError):
            web_fetch.validate_url("file:///etc/passwd")

    def test_fetch_with_fake_opener(self):
        import web_fetch

        class Response:
            headers = {"Content-Type": "text/html; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def read(self, _n):
                return b"<title>T</title><p>hello</p>"

        title, text = web_fetch.fetch_text("https://example.com/x", opener=lambda *_a, **_k: Response())
        self.assertEqual((title, text), ("T", "hello"))
        with tempfile.TemporaryDirectory() as directory:
            path = web_fetch.save_fetched(directory, "https://example.com/x", title, text)
            self.assertEqual(path.name, "example-com-x.md")


class FuzzyPaletteTests(unittest.TestCase):
    def test_fuzzy_ranking(self):
        self.assertIsNone(slash_commands.fuzzy_score("zzq", "compact"))
        self.assertGreater(slash_commands.fuzzy_score("com", "commit"), slash_commands.fuzzy_score("cmt", "commit"))
        names = [c.name for c in slash_commands.palette_matches("cmp", slash_commands.BUILTIN_COMMANDS)]
        self.assertEqual(names[0], "compact")


class MemoryAndMentionTests(unittest.TestCase):
    def test_memory_files_and_notes(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root:
            (Path(root) / "CLAUDE.md").write_text("Use tabs.", encoding="utf-8")
            (Path(home) / ".claude").mkdir()
            (Path(home) / ".claude" / "CLAUDE.md").write_text("Be brief.", encoding="utf-8")
            text, labels = memory_files.load_memory_files(root, home=home)
            self.assertIn("Use tabs.", text)
            self.assertIn("Be brief.", text)
            self.assertEqual(labels, ["~/.claude/CLAUDE.md", "CLAUDE.md"])
            self.assertEqual(memory_files.parse_memory_note("# prefer pytest"), "prefer pytest")
            self.assertIsNone(memory_files.parse_memory_note("## heading"))
            path = memory_files.append_memory_note(root, "prefer pytest")
            memory_files.append_memory_note(root, "no mocks")
            self.assertEqual(path.read_text(encoding="utf-8"), "## Notes\n- prefer pytest\n- no mocks\n")

    def test_mentions(self):
        found = mentions.extract_mentions("Fix @src/app.py and @README.md, not email a@b.com")
        self.assertEqual(found, ["src/app.py", "README.md"])
        resolved, missing = mentions.resolve_mentions(["app.py", "docs", "nope.py"], ["src/app.py", "docs/a.md", "docs/b.md"])
        self.assertEqual(resolved, ["src/app.py", "docs/a.md", "docs/b.md"])
        self.assertEqual(missing, ["nope.py"])
        self.assertEqual(mentions.current_mention_prefix("look at @src/a"), "src/a")
        self.assertIsNone(mentions.current_mention_prefix("mail a@b"))


class ApprovalTests(unittest.TestCase):
    def test_rules_and_modes(self):
        rules = approval.RuleSet(allow=["Bash(pytest*)", "Read(src/**)", "bogus"], deny=["Read(src/secret/**)"])
        self.assertEqual(rules.allow, ["Bash(pytest*)", "Read(src/**)"])
        self.assertEqual(rules.decide("Bash", "pytest -q"), "allow")
        self.assertIsNone(rules.decide("Bash", "rm -rf /"))
        self.assertEqual(rules.decide_paths("Read", ["src/a.py", "src/secret/k.py"]), "deny")
        self.assertEqual(approval.auto_decision("suggest", "inspect", rules, ["src/a.py"]), "allow")
        self.assertIsNone(approval.auto_decision("suggest", "inspect", rules, ["lib/a.py"]))
        self.assertEqual(approval.auto_decision("full-auto", "inspect", rules, ["lib/a.py"]), "allow")
        self.assertIsNone(approval.auto_decision("full-auto", "verify", None, "make", command_policy_allowed=False))
        self.assertEqual(approval.auto_decision("full-auto", "verify", None, "pytest", command_policy_allowed=True), "allow")
        self.assertEqual(approval.normalize_approval_mode("yolo"), "full-auto")
        self.assertEqual(approval.normalize_approval_mode(None, "auto"), "auto-edit")
        self.assertEqual(approval.command_rule_for("npm run test"), "Bash(npm run*)")
        self.assertEqual(approval.edits_blocked(approval.RuleSet(deny=["Edit(docs/**)"]), ["docs/x.md", "a.py"]), ["docs/x.md"])
        with self.assertRaises(ValueError):
            approval.parse_rule("Write(x)")


class EditOpsTests(unittest.TestCase):
    def test_hunks(self):
        original = "a = 1\nb = 2\nc = 3\n"
        self.assertEqual(edit_ops.apply_hunks(original, [{"old": "b = 2", "new": "b = 20"}]), "a = 1\nb = 20\nc = 3\n")
        self.assertEqual(edit_ops.apply_hunks("", [{"old": "", "new": "new\n"}]), "new\n")
        self.assertEqual(edit_ops.apply_hunks("x x", [{"old": "x", "new": "y", "all": True}]), "y y")
        self.assertEqual(edit_ops.apply_hunks("def f():   \n    pass\n", [{"old": "def f():\n    pass", "new": "def g():\n    pass"}]),
                         "def g():\n    pass\n")
        with self.assertRaises(edit_ops.EditApplyError):
            edit_ops.apply_hunks("x x", [{"old": "x", "new": "y"}])
        with self.assertRaises(edit_ops.EditApplyError):
            edit_ops.apply_hunks("abc", [{"old": "zzz", "new": "y"}])


class GitToolsTests(unittest.TestCase):
    @unittest.skipUnless(git_tools.git_available(), "git missing")
    def test_status_diff_commit(self):
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
            subprocess.run(["git", "init", "-q", "-b", "main", root], check=True, env=env)
            Path(root, "a.txt").write_text("one\n", encoding="utf-8")
            status = git_tools.git_status(root)
            self.assertTrue(status.is_repo)
            self.assertEqual(status.branch, "main")
            self.assertEqual(status.changed, (("??", "a.txt"),))
            with mock.patch.dict(os.environ, env):
                ok, text = git_tools.git_commit(root, "Add a")
            self.assertTrue(ok, text)
            Path(root, "a.txt").write_text("two\n", encoding="utf-8")
            self.assertIn("+two", git_tools.git_diff(root))
            self.assertIn("main ±1", git_tools.git_status(root).label())
            self.assertFalse(git_tools.is_git_repo(tempfile.gettempdir() + "/definitely-missing"))
        self.assertEqual(git_tools.suggest_commit_message(["a.py"], ""), "Update a.py")
        self.assertEqual(git_tools.suggest_commit_message([], "Fix parser. Also tests."), "Fix parser")


class SessionTests(unittest.TestCase):
    def test_store_roundtrip_and_compaction_split(self):
        with tempfile.TemporaryDirectory() as directory:
            store = sessions.SessionStore(directory)
            conversation = sessions.Conversation("s-abc", "/p")
            self.assertIsNone(store.save(conversation))
            conversation.add("user", "Add tests")
            conversation.add("assistant", "Added 2 tests")
            store.save(conversation)
            loaded = store.load("s-abc")
            self.assertEqual(loaded.title, "Add tests")
            self.assertEqual(loaded.messages, [("user", "Add tests"), ("assistant", "Added 2 tests")])
            self.assertEqual(store.latest("/p").session_id, "s-abc")
            self.assertEqual(store.list("/other"), [])
            with self.assertRaises(ValueError):
                store.load("../escape")
        older, recent = sessions.split_for_compaction([("u", str(i)) for i in range(6)], keep=4)
        self.assertEqual(len(older), 2)
        self.assertEqual(len(recent), 4)


class HooksUsageThemeMotionTests(unittest.TestCase):
    def test_hooks(self):
        config = hooks.normalize_hooks({"PreApply": [["python", "-c", "import sys; sys.exit(1)"]], "Stop": "echo done", "Bad": [["x"]]})
        self.assertEqual(set(config), {"PreApply", "Stop"})
        with tempfile.TemporaryDirectory() as root:
            results = hooks.run_hooks({"PreApply": [[sys.executable, "-c", "import sys; sys.exit(1)"]]}, "PreApply", root)
            self.assertTrue(hooks.blocked("PreApply", results))
            shell = hooks.run_hooks({"Stop": [["bash", "-c", "true"]]}, "Stop", root)
            self.assertEqual(shell[0][1], 126)

    def test_usage(self):
        meter = usage.UsageMeter()
        meter.record("m:free", 1000, 200, context_window=4000)
        self.assertEqual(meter.total_tokens, 1200)
        self.assertEqual(meter.short_label(), "1.2k tokens · 25% ctx · $0")
        self.assertIn("cost $0.00", meter.report())

    def test_theme_contrast(self):
        for palette in theme.PALETTES.values():
            self.assertGreaterEqual(theme.contrast(palette["text"], palette["canvas"]), 7)
            self.assertGreaterEqual(theme.contrast(palette["text_muted"], palette["canvas"]), 4.5)
            self.assertGreaterEqual(theme.contrast(palette["accent_ink"], palette["accent"]), 4.5)
        self.assertEqual(theme.normalize_theme("neon"), "dark")

    def test_easing_and_stagger(self):
        ease = ui_kit.cubic_bezier(0.2, 0.8, 0.2, 1.0)
        self.assertEqual(ease(0), 0.0)
        self.assertEqual(ease(1), 1.0)
        self.assertGreater(ease(0.5), 0.8)
        self.assertAlmostEqual(ui_kit.cubic_bezier(0, 0, 1, 1)(0.3), 0.3, places=4)
        self.assertAlmostEqual(ui_kit.power_out(2)(0.5), 0.875)
        self.assertEqual(ui_kit.stagger_delays(3, 0.1), [0.0, 0.1, 0.2])
        self.assertEqual(ui_kit.stagger_delays(3, amount=0.4, origin="end"), [0.4, 0.2, 0.0])

    def test_timeline_positions(self):
        line = ui_kit.Timeline(mock.Mock())
        noop = lambda _t: None
        line.to("a", 0.2, noop).to("b", 0.1, noop, position="<").to("c", 0.1, noop, position="+=0.05")
        starts = {key: start for key, start, *_rest in line.steps}
        self.assertEqual(starts, {"a": 0.0, "b": 0.0, "c": 0.25})
        self.assertAlmostEqual(line.duration, 0.35)


class ExecutorExtensionTests(unittest.TestCase):
    def setUp(self):
        import CodeRouter as core

        self.core = core

    def test_parser_accepts_hunks_and_delete(self):
        text = json.dumps({"action": "final", "summary": "s", "files": [
            {"path": "a.py", "edits": [{"old": "1", "new": "2"}]},
            {"path": "b.py", "delete": True},
        ]})
        parsed = self.core.parse_executor_response(text)
        self.assertEqual(parsed["files"], [{"path": "a.py", "edits": [{"old": "1", "new": "2"}]}, {"path": "b.py", "content": None}])
        with self.assertRaises(ValueError):
            self.core.parse_executor_response(json.dumps({"action": "final", "summary": "s", "files": [{"path": "b.py", "delete": False}]}))

    def test_hunks_delete_apply_and_undo(self):
        core = self.core
        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.py").write_text("x = 1\n", encoding="utf-8")
            Path(root, "old.py").write_text("gone\n", encoding="utf-8")
            edits = core.resolve_edit_hunks(root, [
                {"path": "a.py", "edits": [{"old": "x = 1", "new": "x = 2"}]},
                {"path": "old.py", "content": None},
            ])
            diffs = core.render_diff_by_path(root, edits)
            self.assertIn("(deleted)", diffs["old.py"])
            snapshot = core.create_run_snapshot(root, (), (), core.APPLY_MODE_REVIEW, run_id="r1")
            proposal = core.create_pending_proposal(snapshot, edits)
            undo = core.build_undo_transaction(proposal)
            self.assertEqual(core.apply_proposal_transactionally(proposal, root, core.TASK_STATE_REVIEW, "r1"), 2)
            self.assertEqual(Path(root, "a.py").read_text(encoding="utf-8"), "x = 2\n")
            self.assertFalse(Path(root, "old.py").exists())
            core.restore_undo_transactionally(undo, root)
            self.assertEqual(Path(root, "old.py").read_text(encoding="utf-8"), "gone\n")
            self.assertEqual(Path(root, "a.py").read_text(encoding="utf-8"), "x = 1\n")
            with self.assertRaises(ValueError):
                core.create_pending_proposal(snapshot, [{"path": "missing.py", "content": None}])

    def test_generation_settings_payload(self):
        core = self.core
        saved = dict(core.GENERATION_SETTINGS)
        try:
            core.configure_generation(temperature=0.7, style="concise", reasoning_effort="high")
            core.GENERATION_SETTINGS["images"] = ("data:image/png;base64,AA==",)
            payload = core.apply_generation_settings({"temperature": 0.1, "messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(payload["temperature"], 0.7)
            self.assertEqual(payload["reasoning"], {"effort": "high"})
            self.assertEqual(payload["messages"][0]["content"][1]["type"], "image_url")
            self.assertIn("terse", core.generation_style_suffix())
        finally:
            core.GENERATION_SETTINGS.clear()
            core.GENERATION_SETTINGS.update(saved)


class ToolQueryTests(unittest.TestCase):
    def setUp(self):
        import CodeRouter as core

        self.core = core

    def test_parse_and_run_search_and_list(self):
        core = self.core
        query = core.parse_executor_response(json.dumps({"action": "search", "pattern": "def (\\w+)", "glob": "*.py"}))
        self.assertEqual(query, core.ToolQuery("search", pattern="def (\\w+)", glob="*.py"))
        with self.assertRaises(ValueError):
            core.parse_executor_response(json.dumps({"action": "list", "path": "../up"}))
        with tempfile.TemporaryDirectory() as root:
            Path(root, "src").mkdir()
            Path(root, "src", "a.py").write_text("def alpha():\n    pass\n", encoding="utf-8")
            Path(root, "secrets.txt").write_text("def hidden():", encoding="utf-8")
            Path(root, "node_modules").mkdir()
            Path(root, "node_modules", "b.py").write_text("def beta():", encoding="utf-8")
            found = core.run_tool_query(root, query)
            self.assertEqual(found.content, "src/a.py:1: def alpha():")
            listing = core.run_tool_query(root, core.parse_executor_response(json.dumps({"action": "list", "path": ""})))
            self.assertEqual(listing.content.splitlines(), ["src/"])
            literal = core.run_tool_query(root, core.ToolQuery("search", pattern="alpha(("))
            self.assertIn("(no matches)", literal.content)


class ExecCliTests(unittest.TestCase):
    def setUp(self):
        import CodeRouter as core

        self.core = core

    def run_cli(self, argv, responses, env_key="sk-or-test"):
        out, err = io.StringIO(), io.StringIO()
        replies = iter(responses)
        with (
            mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": env_key}),
            mock.patch.object(self.core, "load_local_config", return_value={}),
            mock.patch.object(self.core, "build_free_model_queue", return_value=(["test/model:free"], "")),
            mock.patch.object(self.core, "urlopen", side_effect=lambda *_a, **_k: streamed(next(replies))),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli.main(argv, self.core)
        return code, out.getvalue(), err.getvalue()

    def test_exec_suggest_then_apply(self):
        final = json.dumps({"action": "final", "summary": "Rename var", "files": [{"path": "a.py", "edits": [{"old": "x", "new": "y"}]}]})
        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.py").write_text("x = 1\n", encoding="utf-8")
            code, out, _err = self.run_cli(["exec", "-C", root, "--no-plan", "-q", "rename x"], [final])
            self.assertEqual(code, 3)
            self.assertIn("+y = 1", out)
            self.assertEqual(Path(root, "a.py").read_text(encoding="utf-8"), "x = 1\n")
            code, out, _err = self.run_cli(["exec", "-C", root, "--no-plan", "--json", "--yes", "rename x"], [final])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["applied"], 1)
            self.assertEqual(Path(root, "a.py").read_text(encoding="utf-8"), "y = 1\n")

    def test_exec_full_auto_inspect_round(self):
        inspect = json.dumps({"action": "inspect", "summary": "need file", "paths": ["a.py"]})
        final = json.dumps({"action": "final", "summary": "Done", "files": []})
        plan = json.dumps({"summary": "p", "steps": [{"id": "1", "title": "t", "detail": "d"}]})
        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.py").write_text("x = 1\n", encoding="utf-8")
            code, out, _err = self.run_cli(["exec", "-C", root, "-a", "full-auto", "--json", "go"], [plan, inspect, final])
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["plan"]["summary"], "p")

    def test_exec_tool_query_then_final(self):
        search = json.dumps({"action": "search", "pattern": "x ="})
        final = json.dumps({"action": "final", "summary": "Found it", "files": []})
        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.py").write_text("x = 1\n", encoding="utf-8")
            code, out, _err = self.run_cli(["exec", "-C", root, "--no-plan", "--json", "find x"], [search, final])
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["summary"], "Found it")

    def test_exec_requires_key_and_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            code, _out, err = self.run_cli(["exec", "-C", root], [], env_key="")
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()


class WorkerToolLoopTests(unittest.TestCase):
    def test_worker_runs_tool_queries_then_proposes(self):
        import queue as queue_module
        import CodeRouter as core

        with tempfile.TemporaryDirectory() as root:
            Path(root, "a.py").write_text("x = 1\n", encoding="utf-8")

            class Host:
                api_key = "worker-key-123456"
                work_queue = queue_module.Queue()
                lifecycle = core.RunLifecycle()

                def _run_is_current(self, run_id):
                    return self.lifecycle.accepts(run_id)

            host = Host()
            snapshot = core.create_run_snapshot(root, (), (), core.APPLY_MODE_REVIEW, run_id="tool-run", request_text="t")
            host.lifecycle.activate(snapshot)
            final = {"action": "final", "summary": "Bump", "files": [{"path": "a.py", "content": "x = 2\n"}]}
            calls = []

            def fake_call(**kwargs):
                calls.append(kwargs["inspect_context"])
                return (core.ToolQuery("search", pattern="x"), "m:free") if len(calls) == 1 else (final, "m:free")

            with (
                mock.patch.object(core, "build_free_model_queue", return_value=([], None)),
                mock.patch.object(core, "call_openrouter_with_fallback", side_effect=fake_call),
            ):
                core.CodeAgentApp._run_agent_worker(host, snapshot, "t", None, True)
            kinds = []
            while not host.work_queue.empty():
                kinds.append(host.work_queue.get_nowait().kind)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1][0].content, "a.py:1: x = 1")
            self.assertIn("proposal", kinds)
