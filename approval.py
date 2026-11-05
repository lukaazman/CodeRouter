"""Approval modes and persistent allow/deny rules.

Modes (Codex style):
    suggest    - every edit is reviewed, inspect and commands ask (default)
    auto-edit  - edits are applied automatically, inspect and commands ask
    full-auto  - edits applied, inspect allowed, allow-listed commands run

Rules (Claude Code style) are strings such as ``Bash(pytest*)``,
``Bash(npm run test:*)``, ``Read(src/**)``, ``Edit(docs/**)``. Deny wins.
"""

import fnmatch
import re
import shlex

APPROVAL_SUGGEST = "suggest"
APPROVAL_AUTO_EDIT = "auto-edit"
APPROVAL_FULL_AUTO = "full-auto"
APPROVAL_MODES = (APPROVAL_SUGGEST, APPROVAL_AUTO_EDIT, APPROVAL_FULL_AUTO)
APPROVAL_LABELS = {
    APPROVAL_SUGGEST: "Suggest · review everything",
    APPROVAL_AUTO_EDIT: "Auto-edit · apply edits, ask for commands",
    APPROVAL_FULL_AUTO: "Full auto · apply edits, allow reads and safe commands",
}
RULE_TOOLS = ("Bash", "Read", "Edit")
RULE_PATTERN = re.compile(r"^(Bash|Read|Edit)(?:\((.*)\))?$")
MAX_RULES = 100


def normalize_approval_mode(value, apply_mode="review"):
    value = str(value or "").strip().lower().replace("_", "-")
    aliases = {"review": APPROVAL_SUGGEST, "auto": APPROVAL_AUTO_EDIT, "full": APPROVAL_FULL_AUTO,
               "yolo": APPROVAL_FULL_AUTO, "auto-apply": APPROVAL_AUTO_EDIT}
    value = aliases.get(value, value)
    if value in APPROVAL_MODES:
        return value
    return APPROVAL_AUTO_EDIT if apply_mode == "auto" else APPROVAL_SUGGEST


def apply_mode_for(approval_mode):
    return "review" if approval_mode == APPROVAL_SUGGEST else "auto"


def parse_rule(rule):
    match = RULE_PATTERN.match(str(rule or "").strip())
    if not match:
        raise ValueError("Rules look like Bash(pytest*), Read(src/**) or Edit(docs/**).")
    tool, pattern = match.group(1), (match.group(2) or "*").strip()
    if not pattern:
        pattern = "*"
    return tool, pattern


def normalize_rules(values):
    rules = []
    for value in values or ():
        try:
            tool, pattern = parse_rule(value)
        except ValueError:
            continue
        text = f"{tool}({pattern})"
        if text not in rules:
            rules.append(text)
    return rules[:MAX_RULES]


def _command_text(argv_or_text):
    if isinstance(argv_or_text, (list, tuple)):
        return " ".join(argv_or_text)
    return " ".join(str(argv_or_text or "").split())


def _matches(tool, pattern, subject):
    if tool == "Bash":
        # "npm run test:*" (Claude prefix syntax) == "npm run test*"
        if pattern.endswith(":*"):
            pattern = pattern[:-2] + "*"
        return fnmatch.fnmatchcase(subject, pattern)
    subject = subject.replace("\\", "/").lstrip("./")
    if pattern.endswith("/**"):
        base = pattern[:-3]
        return subject == base or subject.startswith(base + "/")
    return fnmatch.fnmatchcase(subject, pattern.replace("**", "*"))


class RuleSet:
    def __init__(self, allow=(), deny=()):
        self.allow = normalize_rules(allow)
        self.deny = normalize_rules(deny)

    def decide(self, tool, subject):
        """'deny', 'allow' or None (ask)."""
        subject = _command_text(subject) if tool == "Bash" else str(subject or "")
        for rule in self.deny:
            rule_tool, pattern = parse_rule(rule)
            if rule_tool == tool and _matches(tool, pattern, subject):
                return "deny"
        for rule in self.allow:
            rule_tool, pattern = parse_rule(rule)
            if rule_tool == tool and _matches(tool, pattern, subject):
                return "allow"
        return None

    def decide_paths(self, tool, paths):
        """Combined decision for several paths: any deny -> deny, all allow -> allow."""
        decisions = [self.decide(tool, path) for path in paths]
        if "deny" in decisions:
            return "deny"
        if decisions and all(item == "allow" for item in decisions):
            return "allow"
        return None

    def add(self, kind, rule):
        tool, pattern = parse_rule(rule)
        text = f"{tool}({pattern})"
        target = self.allow if kind == "allow" else self.deny
        if text not in target:
            target.append(text)
        return text

    def to_config(self):
        return {"allow": list(self.allow), "deny": list(self.deny)}

    @classmethod
    def from_config(cls, data):
        data = data if isinstance(data, dict) else {}
        return cls(data.get("allow", ()), data.get("deny", ()))


def command_rule_for(command_text):
    """Suggested 'always allow' rule: the executable plus first argument."""
    try:
        argv = shlex.split(command_text)
    except ValueError:
        argv = command_text.split()
    if not argv:
        return ""
    head = " ".join(argv[:2]) if len(argv) > 1 and not argv[1].startswith("-") else argv[0]
    return f"Bash({head}*)"


def auto_decision(mode, kind, rules, subject, command_policy_allowed=False):
    """Decide a gate without asking. Returns 'allow', 'deny' or None (ask).

    kind: 'inspect' (subject = paths) or 'verify' (subject = command text).
    """
    rules = rules or RuleSet()
    if kind == "inspect":
        decision = rules.decide_paths("Read", subject)
        if decision:
            return decision
        return "allow" if mode == APPROVAL_FULL_AUTO else None
    if kind == "verify":
        decision = rules.decide("Bash", subject)
        if decision:
            return decision
        if mode == APPROVAL_FULL_AUTO and command_policy_allowed:
            return "allow"
        return None
    return None


def edits_blocked(rules, paths):
    """Paths denied by Edit(...) rules."""
    rules = rules or RuleSet()
    return [path for path in paths if rules.decide("Edit", path) == "deny"]
