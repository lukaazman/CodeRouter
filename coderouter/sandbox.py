"""Optional OS sandbox for verification and hook commands.

Modes: "off" (default) and "network-off". Linux uses an unprivileged user and
network namespace (``unshare -rn``); macOS uses ``sandbox-exec`` with a
deny-network profile. When the platform has no supported tool, commands are
refused rather than silently run with network access.
"""

import shutil
import sys

SANDBOX_MODES = ("off", "network-off")
MACOS_PROFILE = "(version 1)(allow default)(deny network*)"


class SandboxUnavailable(RuntimeError):
    pass


def normalize_mode(value):
    value = str(value or "off").strip().lower()
    return value if value in SANDBOX_MODES else "off"


def sandbox_tool():
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        return "unshare"
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    return ""


def wrap(argv, mode):
    argv = list(argv)
    if normalize_mode(mode) == "off":
        return argv
    tool = sandbox_tool()
    if tool == "unshare":
        return ["unshare", "-rn", "--", *argv]
    if tool == "sandbox-exec":
        return ["sandbox-exec", "-p", MACOS_PROFILE, *argv]
    raise SandboxUnavailable("network-off sandbox is not available on this system (needs unshare or sandbox-exec)")


def describe(mode):
    mode = normalize_mode(mode)
    if mode == "off":
        return "off · commands keep network access"
    tool = sandbox_tool() or "unavailable"
    return f"network-off via {tool}"
