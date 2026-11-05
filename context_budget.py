"""Fit a project snapshot into a token budget.

Small projects go in whole. Larger ones send a file tree plus the files most
relevant to the prompt (mentioned paths first, then path/content keyword
matches, then small files), and the model fetches the rest with the
read-only search, list and inspect actions.
"""

import re
from pathlib import Path

from run_types import SourceFile

DEFAULT_BUDGET_TOKENS = 60_000
TREE_MAX_LINES = 600
WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
STOPWORDS = {"the", "and", "for", "with", "this", "that", "add", "fix", "make", "please", "file", "files", "code",
             "into", "from", "when", "should", "use", "new", "all", "also", "then", "test", "tests"}


def estimate(text):
    return (len(text or "") + 3) // 4


def prompt_keywords(prompt):
    words = {word.lower() for word in WORD_PATTERN.findall(prompt or "")}
    return {word for word in words if word not in STOPWORDS}


def file_tree(files):
    paths = sorted(source.relative_path for source in files)
    lines = paths[:TREE_MAX_LINES]
    if len(paths) > TREE_MAX_LINES:
        lines.append(f"... {len(paths) - TREE_MAX_LINES} more files")
    return "\n".join(lines)


def relevance(source, keywords, mentioned):
    path = source.relative_path.lower()
    if path in mentioned:
        return 1_000_000
    score = 0
    stem_parts = set(re.split(r"[/._-]+", path))
    for word in keywords:
        if word in stem_parts:
            score += 40
        elif word in path:
            score += 15
    if keywords:
        head = source.content[:20_000].lower()
        score += sum(min(head.count(word), 5) for word in keywords) * 2
    if Path(path).name in {"readme.md", "agents.md", "pyproject.toml", "package.json"}:
        score += 10
    return score


def fit_context(files, prompt, budget_tokens=DEFAULT_BUDGET_TOKENS, mentioned=()):
    """Return (files, note). note is '' when everything fit."""
    files = list(files)
    total = sum(estimate(source.content) for source in files)
    if total <= budget_tokens:
        return files, ""
    keywords = prompt_keywords(prompt)
    mentioned = {path.lower() for path in mentioned}
    ranked = sorted(files, key=lambda source: (-relevance(source, keywords, mentioned), len(source.content)))
    tree = SourceFile(path=Path("."), relative_path="[file tree]", content=file_tree(files))
    chosen, used = [tree], estimate(tree.content)
    for source in ranked:
        cost = estimate(source.content)
        if used + cost > budget_tokens:
            continue
        chosen.append(source)
        used += cost
    note = (f"lean context: {len(chosen) - 1} of {len(files)} files ({used // 1000}k of {total // 1000}k tokens); "
            "the model can search, list or inspect the rest")
    return chosen, note
