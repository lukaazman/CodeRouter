"""Context-aware, local inline recommendations for CodeRouter commands."""

from __future__ import annotations

from dataclasses import dataclass

import model_router as _model_router


LOCAL_COMMAND_COMPLETIONS = ("/status", "/model", "/permissions", "/review")
LOCAL_MODEL_COMPLETIONS = ("/model auto", "/model reset")
ACTIVE_TASK_STATES = frozenset({"collecting", "planning", "plan", "running"})


@dataclass(frozen=True)
class LocalCommandRecommendation:
    """One safe completion that the user may explicitly accept or dismiss."""

    typed: str
    completion: str
    suffix: str
    reason: str
    category: str


def _has_pending_edits(value):
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError, OverflowError):
        return bool(value)


def _context_order(
    *,
    prompt,
    task_state,
    has_pending_proposal,
    has_pending_plan,
    has_inspect_request,
    has_verification_request,
    pending_edits,
):
    category = _model_router.classify_prompt_category(prompt)
    state = str(task_state or "").strip().casefold()
    if has_pending_proposal or has_pending_plan or _has_pending_edits(pending_edits) or state == "review":
        primary = "/review"
        reason = "pending review"
    elif has_inspect_request or has_verification_request:
        primary = "/permissions"
        reason = "pending permission gate"
    elif state in ACTIVE_TASK_STATES:
        primary = "/status"
        reason = "active run"
    elif category != _model_router.MODEL_CATEGORY_GENERAL:
        primary = "/model"
        reason = f"prompt category · {category}"
    else:
        primary = "/status"
        reason = "current task status"
    ordered = [primary]
    ordered.extend(command for command in LOCAL_COMMAND_COMPLETIONS if command not in ordered)
    return ordered, category, reason


def _completion_suffix(typed, completion):
    return completion[len(typed):]


def recommend_local_command(
    value,
    *,
    prompt="",
    task_state="idle",
    has_pending_proposal=False,
    has_pending_plan=False,
    has_inspect_request=False,
    has_verification_request=False,
    pending_edits=0,
    model_selection_mode="auto",
):
    """Return a safe local command completion for the current input.

    The recommendation is advisory only. It is never added to the input until
    the user explicitly accepts it with the keyboard or the ghost text.
    """
    typed = str(value or "")
    if not typed.startswith("/") or any(char in typed for char in "\r\n"):
        return None

    lowered = typed.casefold()
    ordered, category, context_reason = _context_order(
        prompt=prompt,
        task_state=task_state,
        has_pending_proposal=has_pending_proposal,
        has_pending_plan=has_pending_plan,
        has_inspect_request=has_inspect_request,
        has_verification_request=has_verification_request,
        pending_edits=pending_edits,
    )

    if lowered.startswith("/model") and lowered != "/model":
        candidates = [
            completion
            for completion in LOCAL_MODEL_COMPLETIONS
            if completion.startswith(lowered)
        ]
        if not candidates:
            return None
        preferred = "/model auto"
        completion = preferred if preferred in candidates else candidates[0]
        reason = f"free routing · {category}"
    else:
        if lowered in {command.casefold() for command in LOCAL_COMMAND_COMPLETIONS}:
            return None
        candidates = [command for command in ordered if command.startswith(lowered)]
        if not candidates:
            return None
        completion = candidates[0]
        reason = context_reason if completion == ordered[0] else "command prefix"

    return LocalCommandRecommendation(
        typed=typed,
        completion=completion,
        suffix=_completion_suffix(typed, completion),
        reason=reason,
        category=category,
    )
