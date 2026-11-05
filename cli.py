"""Headless mode: `python CodeRouter.py exec "prompt"`.

Runs the same plan -> execute -> review pipeline as the window, without a
display. By default changes are only shown (suggest); `--approval auto-edit`
or `--yes` writes them, `--approval full-auto` also lets the model read the
files it asks for. Exit codes: 0 ok, 1 error, 2 usage, 3 changes not applied.
"""

import argparse
import json
import os
import queue
import sys
import threading
import uuid
from pathlib import Path

import approval as _approval
import extensions as _ext
import mcp_client as _mcp
import memory_files as _memory
import mentions as _mentions
import slash_commands as _slash


def build_parser():
    parser = argparse.ArgumentParser(prog="CodeRouter", description="Free-model code agent.")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("exec", help="Run one task without the window")
    run.add_argument("prompt", nargs="*", help="Task text, a /custom-command, or '-' to read stdin")
    run.add_argument("-C", "--cwd", default=".", help="Project folder (default: current directory)")
    run.add_argument("-a", "--approval", choices=_approval.APPROVAL_MODES, default=None,
                     help="suggest (show only), auto-edit (write), full-auto (write + allow reads)")
    run.add_argument("-y", "--yes", action="store_true", help="Write changes (same as --approval auto-edit)")
    run.add_argument("--no-plan", action="store_true", help="Skip the planning call")
    run.add_argument("-m", "--model", default="", help="Free model id override (must end in :free)")
    run.add_argument("--style", choices=("concise", "default", "explanatory"), default=None)
    run.add_argument("--effort", choices=("low", "medium", "high"), default=None)
    run.add_argument("--temperature", type=float, default=None)
    run.add_argument("--max-rounds", type=int, default=2, help="Read-only inspect rounds (default 2)")
    run.add_argument("--agent", default="", help="Agent persona from .claude/agents or .coderouter/agents")
    run.add_argument("--json", action="store_true", help="Print a JSON result instead of text")
    run.add_argument("-q", "--quiet", action="store_true", help="Do not stream model output to stderr")
    sub.add_parser("commands", help="List slash commands, including custom ones").add_argument("-C", "--cwd", default=".")
    ask = sub.add_parser("ask", help="Answer a question about the project (no edits)")
    ask.add_argument("question", nargs="+")
    ask.add_argument("-C", "--cwd", default=".")
    gui = sub.add_parser("open", help="Open the window (optionally in a folder, resuming, or with a prompt)")
    gui.add_argument("prompt", nargs="*")
    gui.add_argument("-C", "--cwd", default="")
    gui.add_argument("--resume", action="store_true", help="Restore the latest conversation for the folder")
    return parser


def run_ask(args, core):
    root = Path(args.cwd).resolve()
    config = core.load_local_config()
    api_key = os.environ.get("OPENROUTER_API_KEY") or config.get("openrouter_api_key", "")
    if not api_key:
        print("Set OPENROUTER_API_KEY or sign in once from the window.", file=sys.stderr)
        return 2
    question = " ".join(args.question)
    instructions, _status = core.load_project_instructions(root, secrets=[api_key])
    max_files, max_file_kb = core.choose_context_limits(root)
    files = core.collect_files(root, max_files=max_files, max_file_kb=max_file_kb)
    parts, used = [], 0
    for source in files:
        block = f"--- FILE: {source.relative_path} ---\n{source.content}"
        if used + len(block) > 120_000:
            continue
        parts.append(block)
        used += len(block)
    prompt = core.redact_sensitive_text(
        (f"Project instructions:\n{instructions}\n\n" if instructions else "")
        + "Project files:\n" + "\n\n".join(parts) + "\n\nQuestion: " + question, [api_key])
    try:
        answer, _model = core.complete_text(api_key, prompt, system="You answer questions about a codebase. Be precise, cite file paths, keep it short.")
    except Exception as exc:
        print(core.short_error(exc), file=sys.stderr)
        return 1
    print(answer)
    return 0


def _read_prompt(parts):
    if parts == ["-"]:
        return sys.stdin.read().strip()
    return " ".join(parts).strip()


class _Printer(threading.Thread):
    def __init__(self, events, run_id, quiet):
        super().__init__(daemon=True)
        self.events, self.run_id, self.quiet = events, run_id, quiet
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set() or not self.events.empty():
            try:
                event = self.events.get(timeout=0.1)
            except queue.Empty:
                continue
            kind, payload = event[1], event[2]
            if self.quiet:
                continue
            if kind == "stream_delta":
                sys.stderr.write(str(payload))
            elif kind in {"log", "fallback", "model_status", "timeline"} and payload:
                sys.stderr.write(f"\n{payload}\n")
            sys.stderr.flush()


def run_exec(args, core):
    root = Path(args.cwd).resolve()
    if not root.is_dir():
        print(f"Not a folder: {root}", file=sys.stderr)
        return 2
    config = core.load_local_config()
    api_key = os.environ.get("OPENROUTER_API_KEY") or config.get("openrouter_api_key", "")
    if not api_key:
        print("Set OPENROUTER_API_KEY or sign in once from the window.", file=sys.stderr)
        return 2
    prompt = _read_prompt(args.prompt)
    registry = _slash.CommandRegistry(root)
    parsed = _slash.split_command(prompt)
    if parsed:
        command = registry.custom.get(parsed[0])
        if command is None:
            print(f"Only custom commands work in exec mode; /{parsed[0]} is not one.", file=sys.stderr)
            return 2
        prompt = _slash.expand_custom_command(command, parsed[1])
    if not prompt:
        print("Give a task, e.g. CodeRouter exec \"add tests for parser\"", file=sys.stderr)
        return 2

    mode = args.approval or ("auto-edit" if args.yes else _approval.normalize_approval_mode(config.get("approval_mode")))
    rules = _approval.RuleSet.from_config(config.get("permissions"))
    core.configure_generation(
        args.temperature if args.temperature is not None else config.get("temperature"),
        args.style or config.get("style", "default"),
        args.effort or config.get("reasoning_effort", ""),
    )
    secrets = [api_key]
    instructions_text, _status = core.load_project_instructions(root, secrets=secrets)
    memory_text, _labels = _memory.load_memory_files(root, secrets=secrets)
    project_instructions = _memory.combine_instructions(instructions_text, memory_text)
    skills = _ext.match_skills(_ext.load_extensions("skill", root), prompt)
    agent = _ext.load_extensions("agent", root).get(args.agent or config.get("agent", ""))
    extra = "\n\n".join(part for part in (_ext.skills_context(skills), _ext.agent_context(agent)) if part)
    project_instructions = _memory.combine_instructions(project_instructions, extra)
    mentions = _mentions.extract_mentions(prompt)
    if mentions:
        prompt += "\n\n(Files the user mentioned (prioritise them): " + ", ".join(mentions) + ")"
    prompt = core.redact_sensitive_text(prompt, secrets)
    model_mode, model_override = core.load_model_selection_settings(config)
    if args.model:
        model_mode, model_override = core.MODEL_SELECTION_OVERRIDE, core.normalize_model_override(args.model)

    mcp = _mcp.McpManager(_mcp.load_server_specs(config, root), config.get("mcp_enabled_project", ()))
    for error in mcp.start_all():
        print(f"mcp: {error}", file=sys.stderr)
    core.MCP_CATALOG["text"] = mcp.catalog_text()
    run_id = f"exec-{uuid.uuid4().hex[:10]}"
    events = queue.Queue()
    printer = _Printer(events, run_id, args.quiet or args.json)
    printer.start()
    result = {"ok": False, "approval": mode, "plan": None, "summary": "", "files": [], "applied": 0, "model": ""}
    try:
        max_files, max_file_kb = core.choose_context_limits(root)
        files = core.collect_files(root, max_files=max_files, max_file_kb=max_file_kb)
        files = _mentions.prioritise_files(files, _mentions.resolve_mentions(mentions, [f.relative_path for f in files])[0])
        category = core.classify_prompt_category(prompt)
        model_queue, _note = core.build_free_model_queue(api_key)
        tokens = core.estimate_task_context_tokens(prompt + "\n\n" + project_instructions, files, ())
        common = dict(
            api_key=api_key, instructions=prompt, files=files, session_messages=[], log_queue=events,
            run_id=run_id, model_queue=model_queue, task_context_tokens=tokens,
            project_instructions=project_instructions, task_category=category,
            model_selection_mode=model_mode, model_override=model_override,
        )
        plan = None
        if not args.no_plan:
            plan, model = core.call_openrouter_plan_with_fallback(**common)
            result["plan"] = {"summary": plan.summary, "steps": [[s.id, s.title, s.detail] for s in plan.steps]}
            if not args.json:
                print(f"\nPlan ({model}): {plan.summary}")
                for step in plan.steps:
                    print(f"  {step.id}. {step.title} — {step.detail}")
        inspect_context = ()
        tool_rounds = 0
        for round_number in range(max(0, args.max_rounds) + core.TOOL_QUERY_MAX_ROUNDS + 1):
            outcome, model = core.call_openrouter_with_fallback(
                **common, approved_plan=plan, inspect_context=inspect_context, strict_actions=True,
            )
            result["model"] = str(model)
            if isinstance(outcome, (core.ToolQuery, core.McpCall)):
                tool_rounds += 1
                if tool_rounds > core.TOOL_QUERY_MAX_ROUNDS:
                    result["summary"] = "The model kept searching without proposing changes."
                    break
                if isinstance(outcome, core.McpCall):
                    if _approval.auto_decision(mode, "mcp", rules, outcome.tool) == "allow":
                        try:
                            text = mcp.call(outcome.tool, outcome.argument_dict())
                        except (_mcp.McpError, ValueError) as exc:
                            text = f"MCP call failed: {exc}"
                    else:
                        text = f"Refused: {outcome.tool} needs Mcp({outcome.tool}) in permissions.allow or --approval full-auto."
                    item = core.SourceFile(path=root, relative_path=f"[{outcome.label()}]", content=core.redact_sensitive_text(text, secrets))
                else:
                    item = core.run_tool_query(root, outcome, secrets=secrets)
                inspect_context = tuple(inspect_context) + (item,)
                if not (args.quiet or args.json):
                    print(f"\n> {outcome.label()}", file=sys.stderr)
                continue
            if isinstance(outcome, core.InspectRequest):
                decision = _approval.auto_decision(mode, "inspect", rules, outcome.paths)
                if decision != "allow" or round_number - tool_rounds >= args.max_rounds:
                    result["summary"] = f"Model wants to read {', '.join(outcome.paths)}; rerun with --approval full-auto."
                    break
                inspect_context, _status = core.collect_inspect_files(root, outcome.paths, secrets=secrets)
                continue
            if isinstance(outcome, core.VerificationRequest):
                common["instructions"] = prompt + "\n\n(Verification commands are unavailable in exec mode; return a final action.)"
                continue
            edits = core.resolve_edit_hunks(root, outcome.get("files", []))
            result["summary"] = outcome.get("summary", "")
            diffs = core.render_diff_by_path(root, edits)
            result["files"] = [{"path": e["path"], "deleted": e.get("content") is None, "diff": diffs.get(e["path"], "")} for e in edits]
            blocked = _approval.edits_blocked(rules, [e["path"] for e in edits])
            if blocked:
                result["summary"] += f" (blocked by Edit deny rules: {', '.join(blocked)})"
            elif edits and mode != _approval.APPROVAL_SUGGEST:
                snapshot = core.create_run_snapshot(root, (), (), core.APPLY_MODE_AUTO, run_id=run_id)
                proposal = core.create_pending_proposal(snapshot, edits)
                result["applied"] = core.apply_proposal_transactionally(proposal, root, core.TASK_STATE_REVIEW, run_id)
            result["ok"] = True
            break
    except Exception as exc:  # report, never traceback at the user
        result["summary"] = core.short_error(core.redact_sensitive_text(str(exc), secrets))
    finally:
        printer.stop.set()
        printer.join(timeout=2)
        mcp.stop_all()
        core.MCP_CATALOG["text"] = ""
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{result['summary']}")
        for item in result["files"]:
            print(item["diff"])
        if result["files"]:
            verb = f"Applied {result['applied']} file(s)." if result["applied"] else "Not applied (suggest mode; use --yes)."
            print(verb)
    if not result["ok"]:
        return 1
    return 3 if result["files"] and not result["applied"] and mode == _approval.APPROVAL_SUGGEST else 0


def list_commands(args):
    registry = _slash.CommandRegistry(Path(args.cwd).resolve())
    print(registry.help_text())
    return 0


def main(argv, core):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "exec":
        return run_exec(args, core)
    if args.command == "commands":
        return list_commands(args)
    if args.command == "ask":
        return run_ask(args, core)
    if args.command == "open":
        return core.launch_window(folder=args.cwd, resume=args.resume, prompt=" ".join(args.prompt))
    parser.print_help()
    return 2
