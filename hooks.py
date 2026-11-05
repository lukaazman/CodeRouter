"""Opt-in lifecycle hooks, configured in local_config.json:

    "hooks": {
      "UserPromptSubmit": [["python", "tools/check_prompt.py"]],
      "PreApply":  [["python", "-m", "black", "--check", "."]],
      "PostApply": [["python", "-m", "pytest", "-q"]],
      "Stop":      [["notify-send", "CodeRouter", "Run finished"]]
    }

Each hook is an argv list (no shell). It runs in the project root with a
cleaned environment, a timeout and bounded output. Hook context is passed as
JSON on stdin. A non-zero exit from PreApply or UserPromptSubmit blocks the
action; other events only report.
"""

import json
import os
import subprocess

HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreApply", "PostApply", "Notification", "Stop")
BLOCKING_EVENTS = ("UserPromptSubmit", "PreToolUse", "PreApply")
HOOK_TIMEOUT_SECONDS = 30
HOOK_MAX_OUTPUT = 8 * 1024
HOOK_MAX_PER_EVENT = 8
SHELL_EXECUTABLES = {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"}


def normalize_hooks(data):
    hooks = {}
    if not isinstance(data, dict):
        return hooks
    for event in HOOK_EVENTS:
        entries = data.get(event) or []
        clean = []
        for entry in entries[:HOOK_MAX_PER_EVENT]:
            if isinstance(entry, str):
                entry = entry.split()
            if isinstance(entry, list) and entry and all(isinstance(part, str) and part for part in entry):
                clean.append(list(entry))
        if clean:
            hooks[event] = clean
    return hooks


def hook_problem(argv):
    name = os.path.basename(argv[0]).lower()
    if name in SHELL_EXECUTABLES:
        return "shell interpreters are not allowed as hooks"
    return ""


def run_hooks(hooks, event, root, payload=None, env=None, runner=subprocess.run):
    """Run every hook for event. Returns list of (argv, code, output)."""
    results = []
    stdin = json.dumps({"event": event, **(payload or {})}, ensure_ascii=False)
    for argv in hooks.get(event, ()):
        problem = hook_problem(argv)
        if problem:
            results.append((argv, 126, problem))
            continue
        try:
            completed = runner(
                argv,
                cwd=str(root),
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=HOOK_TIMEOUT_SECONDS,
                env=env,
                shell=False,
            )
            output = ((completed.stdout or "") + (completed.stderr or ""))[-HOOK_MAX_OUTPUT:]
            results.append((argv, completed.returncode, output.strip()))
        except subprocess.TimeoutExpired:
            results.append((argv, 124, f"timed out after {HOOK_TIMEOUT_SECONDS}s"))
        except OSError as exc:
            results.append((argv, 127, str(exc)))
    return results


def blocked(event, results):
    return event in BLOCKING_EVENTS and any(code != 0 for _argv, code, _out in results)


def describe_hooks(hooks):
    if not hooks:
        return "No hooks configured. Add \"hooks\" to local_config.json (events: " + ", ".join(HOOK_EVENTS) + ")."
    lines = []
    for event in HOOK_EVENTS:
        for argv in hooks.get(event, ()):
            lines.append(f"{event}: {' '.join(argv)}")
    return "\n".join(lines)
