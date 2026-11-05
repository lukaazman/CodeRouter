"""Search/replace edits, so models need not resend whole files.

A model may return, per file, either ``content`` (full replacement) or
``edits``: ``[{"old": "exact text", "new": "replacement"}]``. Each ``old``
must occur exactly once (or ``"all": true`` replaces every occurrence).
Hunks are resolved locally into full content before review, so diff, apply
and undo keep working unchanged.
"""

EDIT_MAX_HUNKS = 64


class EditApplyError(ValueError):
    pass


def apply_hunks(original, hunks, path="file"):
    if not isinstance(hunks, list) or not 1 <= len(hunks) <= EDIT_MAX_HUNKS:
        raise EditApplyError(f"{path}: edits must be a list of 1-{EDIT_MAX_HUNKS} hunks.")
    text = original
    for number, hunk in enumerate(hunks, 1):
        if not isinstance(hunk, dict) or not set(hunk) <= {"old", "new", "all"}:
            raise EditApplyError(f"{path}: hunk {number} must contain old and new.")
        old, new = hunk.get("old"), hunk.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            raise EditApplyError(f"{path}: hunk {number} old/new must be text.")
        if old == "":
            if text:
                raise EditApplyError(f"{path}: hunk {number} has empty old text for an existing file.")
            text = new
            continue
        count = text.count(old)
        if count == 0:
            stripped = _whitespace_tolerant_find(text, old)
            if stripped is None:
                raise EditApplyError(f"{path}: hunk {number} old text was not found.")
            start, end = stripped
            text = text[:start] + new + text[end:]
            continue
        if count > 1 and not hunk.get("all"):
            raise EditApplyError(f"{path}: hunk {number} old text matches {count} places; add more context.")
        text = text.replace(old, new) if hunk.get("all") else text.replace(old, new, 1)
    return text


def _whitespace_tolerant_find(text, old):
    """Match ignoring trailing whitespace per line; unique match only."""
    want = [line.rstrip() for line in old.splitlines()]
    if not want:
        return None
    lines = text.splitlines(keepends=True)
    hits = []
    for start in range(len(lines) - len(want) + 1):
        if all(lines[start + i].rstrip() == want[i] for i in range(len(want))):
            hits.append(start)
    if len(hits) != 1:
        return None
    begin = sum(len(line) for line in lines[:hits[0]])
    end = begin + sum(len(line) for line in lines[hits[0]:hits[0] + len(want)])
    if not old.endswith("\n") and end and text[end - 1] == "\n":
        end -= 1
    return begin, end
