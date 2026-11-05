"""Gitignore-style rules from .gitignore and .coderouterignore at the project root.

Supports comments, blank lines, negation (!), directory-only patterns
(trailing /), anchored patterns (leading / or a slash inside), * ? [..] and
**. Last matching rule wins, as in git.
"""

import re
from pathlib import Path

IGNORE_FILES = (".gitignore", ".coderouterignore")
MAX_RULES = 2000


def _translate(pattern):
    """Glob -> regex over a posix relative path."""
    out, index = [], 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern[index:index + 3] == "**/":
                out.append("(?:.*/)?")
                index += 3
                continue
            if pattern[index:index + 2] == "**":
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                out.append(re.escape(char))
            else:
                body = pattern[index + 1:end].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                index = end
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out)


class IgnoreRules:
    def __init__(self, lines=()):
        self.rules = []
        for raw in lines:
            line = raw.rstrip("\n").rstrip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            if line.startswith("\\"):
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            anchored = line.startswith("/") or "/" in line
            line = line.lstrip("/")
            body = _translate(line)
            regex = re.compile(("^" if anchored else r"^(?:.*/)?") + body + r"(?:/.*)?$")
            self.rules.append((regex, negate, dir_only))
            if len(self.rules) >= MAX_RULES:
                break

    def __bool__(self):
        return bool(self.rules)

    def _match_one(self, path, is_dir):
        ignored = False
        for regex, negate, dir_only in self.rules:
            if dir_only and not is_dir:
                # A dir-only rule still ignores files under that directory.
                head = path.rsplit("/", 1)[0] if "/" in path else ""
                if not head or not regex.match(head):
                    continue
            if regex.match(path):
                ignored = not negate
        return ignored

    def ignored(self, relative_path, is_dir=False):
        path = str(relative_path).replace("\\", "/").strip("/")
        if not path or not self.rules:
            return False
        parts = path.split("/")
        for depth in range(1, len(parts)):
            if self._match_one("/".join(parts[:depth]), True):
                return True
        return self._match_one(path, is_dir)


def load_ignore_rules(root):
    lines = []
    for name in IGNORE_FILES:
        path = Path(root) / name
        try:
            if path.is_file() and path.stat().st_size <= 256 * 1024:
                lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    return IgnoreRules(lines)
