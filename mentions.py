"""@path mentions in prompts."""

import re

MENTION_PATTERN = re.compile(r"(?<![\w@])@([\w./\\-]+[\w/\\-])")
MENTION_MAX = 12


def extract_mentions(prompt):
    """Return unique mentioned relative paths in order of appearance."""
    seen = []
    for match in MENTION_PATTERN.finditer(prompt or ""):
        path = match.group(1).replace("\\", "/").lstrip("./")
        if path and path not in seen and ".." not in path.split("/"):
            seen.append(path)
        if len(seen) >= MENTION_MAX:
            break
    return seen


def resolve_mentions(mentions, known_paths):
    """Match mentions against scanned relative paths (exact, then suffix)."""
    known = list(known_paths)
    lowered = {path.casefold(): path for path in known}
    resolved, missing = [], []
    for mention in mentions:
        key = mention.casefold().rstrip("/")
        if key in lowered:
            resolved.append(lowered[key])
            continue
        prefix = [path for path in known if path.casefold().startswith(key + "/")]
        if prefix:
            resolved.extend(item for item in prefix[:20] if item not in resolved)
            continue
        suffix = [path for path in known if path.casefold().endswith("/" + key)]
        if len(suffix) == 1:
            resolved.append(suffix[0])
        else:
            missing.append(mention)
    return resolved, missing


def prioritise_files(files, mentioned):
    """Move mentioned SourceFile-like items (with .relative_path) to the front."""
    if not mentioned:
        return list(files)
    wanted = {path.casefold() for path in mentioned}
    first = [item for item in files if item.relative_path.casefold() in wanted]
    rest = [item for item in files if item.relative_path.casefold() not in wanted]
    return first + rest


def current_mention_prefix(text_before_cursor):
    """The partial @token under the cursor, or None."""
    match = re.search(r"(?:^|\s)@([\w./\\-]*)$", text_before_cursor or "")
    return match.group(1) if match else None


def complete_mention(prefix, known_paths, limit=8):
    prefix = (prefix or "").replace("\\", "/").casefold()
    starts = [path for path in known_paths if path.casefold().startswith(prefix)]
    if len(starts) < limit:
        contains = [path for path in known_paths if prefix in path.casefold() and path not in starts]
        starts += contains
    return starts[:limit]
