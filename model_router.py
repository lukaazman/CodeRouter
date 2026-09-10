"""Prompt-aware, zero-cost model routing helpers for CodeRouter.

The module deliberately has no network or UI dependency. OpenRouter catalog
metadata is supplied by the caller and prompt classification stays local.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation


MODEL_SELECTION_AUTO = "auto"
MODEL_SELECTION_OVERRIDE = "override"
MODEL_SELECTION_MODES = frozenset({MODEL_SELECTION_AUTO, MODEL_SELECTION_OVERRIDE})
MODEL_OVERRIDE_MAX_CHARS = 240
MODEL_OVERRIDE_PATTERN = re.compile(
    r"^(?:openrouter/free|[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*:free)$"
)
MODEL_SELECTION_ENV = "CODEROUTER_MODEL"

MODEL_CATEGORY_GENERAL = "general"
MODEL_CATEGORIES = (
    "coding",
    "reasoning",
    "math",
    "writing",
    "analysis",
    "vision",
    "translation",
    MODEL_CATEGORY_GENERAL,
)

MODEL_CATEGORY_TERMS = {
    "coding": (
        "coding",
        "coder",
        "code",
        "programming",
        "programmer",
        "developer",
        "software",
        "swe",
        "terminal",
        "repository",
        "debug",
        "koda",
        "kodiranje",
        "programiranje",
        "programers",
        "readme",
        "github",
        "api",
    ),
    "reasoning": (
        "reasoning",
        "reason",
        "logic",
        "logical",
        "thinking",
        "deliberate",
        "step by step",
        "zaklju",
        "logi",
        "premisli",
        "qwq",
        "deepseek-r1",
        "nemotron",
    ),
    "math": (
        "math",
        "mathemat",
        "algebra",
        "calculus",
        "arithmetic",
        "equation",
        "theorem",
        "proof",
        "matemat",
        "enač",
        "izrač",
    ),
    "writing": (
        "writing",
        "creative",
        "story",
        "storytelling",
        "narrative",
        "poetry",
        "poem",
        "copywriting",
        "rewrite",
        "prose",
        "pisanje",
        "zgodbo",
        "besedilo",
        "preoblik",
    ),
    "analysis": (
        "analysis",
        "analyze",
        "research",
        "summar",
        "extract",
        "classif",
        "compare",
        "document",
        "investigate",
        "analiz",
        "razisk",
        "povzem",
        "primerj",
    ),
    "vision": (
        "vision",
        "image",
        "visual",
        "multimodal",
        "ocr",
        "photo",
        "picture",
        "video",
        "slik",
        "fotograf",
        "vid",
        "qwen-vl",
        "llava",
    ),
    "translation": (
        "translation",
        "translate",
        "multilingual",
        "localization",
        "language",
        "prevod",
        "preved",
        "jezik",
        "lokaliz",
    ),
    MODEL_CATEGORY_GENERAL: (
        "general",
        "instruct",
        "assistant",
        "chat",
        "conversation",
        "splošn",
        "pogovor",
    ),
}

# Family hints make a catalog with sparse descriptions useful while staying
# deterministic. They are routing preferences, not benchmark guarantees.
MODEL_CATEGORY_PREFERENCES = {
    "coding": ("qwen", "deepseek", "mistral", "llama", "glm", "kimi"),
    "reasoning": ("deepseek-r1", "qwq", "qwen", "nemotron", "glm", "kimi", "llama"),
    "math": ("deepseek", "qwen", "nemotron", "llama", "mistral", "glm"),
    "writing": ("mistral", "llama", "kimi", "qwen", "glm", "deepseek"),
    "analysis": ("deepseek", "qwen", "llama", "mistral", "kimi", "glm"),
    "vision": ("qwen-vl", "qwen2-vl", "llava", "gemma", "llama", "mistral"),
    "translation": ("qwen", "llama", "mistral", "gemma", "deepseek", "glm"),
    MODEL_CATEGORY_GENERAL: ("qwen", "llama", "mistral", "deepseek", "gemma", "glm", "kimi"),
}

FREE_PRICING_FIELDS = (
    "prompt",
    "completion",
    "request",
    "image",
    "web_search",
    "internal_reasoning",
    "input_cache_read",
    "input_cache_write",
)

MODEL_FAILURE_BUSY = "busy"
MODEL_FAILURE_UNAVAILABLE = "unavailable"
MODEL_FAILURE_ERROR = "failed"


def _is_zero_price(value):
    if value is None or isinstance(value, bool):
        return False
    try:
        return Decimal(str(value).strip()) == Decimal("0")
    except (InvalidOperation, ValueError):
        return False


def pricing_is_zero(pricing):
    """Return true only when all advertised costs are explicitly zero."""
    if not isinstance(pricing, dict):
        return False
    if not _is_zero_price(pricing.get("prompt")) or not _is_zero_price(pricing.get("completion")):
        return False
    for value in pricing.values():
        if value is not None and not _is_zero_price(value):
            return False
    return True


def is_explicit_free_model_id(model_id):
    value = str(model_id or "").strip()
    lowered = value.casefold()
    return bool(value) and (lowered.endswith(":free") or lowered == "openrouter/free")


def normalize_model_override(value):
    if value is None or not str(value).strip():
        return ""
    candidate = str(value).strip()
    if (
        len(candidate) > MODEL_OVERRIDE_MAX_CHARS
        or any(char.isspace() or ord(char) < 32 for char in candidate)
        or not MODEL_OVERRIDE_PATTERN.fullmatch(candidate)
    ):
        raise ValueError("Model override must be an OpenRouter :free model id.")
    return candidate


def normalize_model_selection_settings(mode=None, model_override=None):
    """Normalize settings and fail closed when a manual value is unsafe."""
    try:
        override = normalize_model_override(model_override)
    except ValueError:
        override = ""
    raw_mode = str(mode or "").strip().casefold()
    if raw_mode not in MODEL_SELECTION_MODES:
        raw_mode = MODEL_SELECTION_OVERRIDE if override else MODEL_SELECTION_AUTO
    if raw_mode == MODEL_SELECTION_OVERRIDE and not override:
        raw_mode = MODEL_SELECTION_AUTO
    if raw_mode == MODEL_SELECTION_AUTO:
        return MODEL_SELECTION_AUTO, ""
    return MODEL_SELECTION_OVERRIDE, override


def load_model_selection_settings(config_data):
    """Read local settings, with an optional non-secret environment override."""
    config = config_data if isinstance(config_data, dict) else {}
    raw_mode = config.get("model_selection_mode")
    raw_override = config.get("model_override", "")
    env_override = os.environ.get(MODEL_SELECTION_ENV, "").strip()
    if env_override:
        try:
            raw_override = normalize_model_override(env_override)
        except ValueError:
            pass
        else:
            raw_mode = MODEL_SELECTION_OVERRIDE
    return normalize_model_selection_settings(raw_mode, raw_override)


def model_selection_summary(mode, model_override=""):
    normalized_mode, normalized_override = normalize_model_selection_settings(mode, model_override)
    if normalized_mode == MODEL_SELECTION_OVERRIDE:
        return f"override · {normalized_override}"
    return "auto · prompt category"


def parse_model_selection_command(value):
    """Parse a local model setting command without accepting paid ids."""
    if not isinstance(value, str):
        raise ValueError("Model command must be text.")
    command = value.strip()
    if command.casefold() in {"/model auto", "/model reset"}:
        return MODEL_SELECTION_AUTO, ""
    if not command.casefold().startswith("/model "):
        raise ValueError("Unknown model command.")
    return MODEL_SELECTION_OVERRIDE, normalize_model_override(command[7:])


def _term_matches(text, term):
    lowered = str(text or "").casefold()
    term = str(term or "").casefold()
    if not lowered or not term:
        return False
    if " " in term or "-" in term:
        return term in lowered
    return bool(re.search(rf"(?<!\w){re.escape(term)}\w*", lowered, flags=re.UNICODE))


def score_prompt_categories(prompt):
    text = " ".join(str(prompt or "").casefold().split())
    scores = {category: 0 for category in MODEL_CATEGORIES}
    for category, terms in MODEL_CATEGORY_TERMS.items():
        for term in terms:
            if _term_matches(text, term):
                scores[category] += 2 if " " in term else 1
    return scores


def classify_prompt_category(prompt):
    scores = score_prompt_categories(prompt)
    specialized = MODEL_CATEGORIES[:-1]
    best = max(specialized, key=lambda category: (scores[category], -specialized.index(category)))
    if scores[best] <= 0:
        return MODEL_CATEGORY_GENERAL
    return best


def explain_prompt_category(prompt):
    scores = score_prompt_categories(prompt)
    category = classify_prompt_category(prompt)
    signals = [
        term
        for term in MODEL_CATEGORY_TERMS.get(category, ())
        if _term_matches(prompt, term)
    ][:4]
    detail = ", ".join(signals) if signals else "no strong signal"
    return f"{category} · {detail}"


def normalize_task_category(category):
    value = str(category or "").strip().casefold()
    return value if value in MODEL_CATEGORIES else MODEL_CATEGORY_GENERAL


def _flatten_text(value, depth=0):
    if depth > 3:
        return []
    if isinstance(value, dict):
        values = []
        for key, item in value.items():
            values.extend(_flatten_text(key, depth + 1))
            values.extend(_flatten_text(item, depth + 1))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_flatten_text(item, depth + 1))
        return values
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def _candidate_value(candidate, key, default=None):
    if isinstance(candidate, dict):
        return candidate.get(key, default)
    return getattr(candidate, key, default)


def candidate_model_id(candidate):
    return str(
        _candidate_value(candidate, "model_id", _candidate_value(candidate, "id", candidate)) or ""
    ).strip()


def candidate_context_length(candidate):
    value = _candidate_value(candidate, "context_length")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def candidate_source(candidate, default="discovered"):
    return str(_candidate_value(candidate, "source", default) or default)


def candidate_static_order(candidate, default=0):
    value = _candidate_value(candidate, "static_order", default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def category_signals_for_candidate(candidate, metadata=None):
    record = metadata if isinstance(metadata, dict) else {}
    values = []
    for key in (
        "id",
        "name",
        "canonical_slug",
        "description",
        "categories",
        "capabilities",
        "supported_parameters",
        "architecture",
        "input_modalities",
        "output_modalities",
        "instruct_type",
    ):
        values.extend(_flatten_text(record.get(key)))
    model_id = candidate_model_id(candidate)
    values.append(model_id)
    coding_signals = _candidate_value(candidate, "coding_signals", ())
    values.extend(_flatten_text(coding_signals))
    combined = " ".join(values)
    signals = {}
    for category, terms in MODEL_CATEGORY_TERMS.items():
        hits = [term for term in terms if _term_matches(combined, term)]
        if hits:
            signals[category] = tuple(dict.fromkeys(hits))
    return signals


def _preference_rank(model_id, category, preferences=None):
    values = (preferences or MODEL_CATEGORY_PREFERENCES).get(category, ())
    lowered = str(model_id or "").casefold()
    for index, family in enumerate(values):
        if str(family).casefold() in lowered:
            return index
    return len(values)


def _health_key(candidate, health_tracker):
    if health_tracker is None:
        return (1, 120_001)
    try:
        return health_tracker.preference_key(candidate_model_id(candidate))
    except (AttributeError, TypeError, ValueError):
        return (1, 120_001)


def rank_candidates(
    candidates,
    *,
    task_context_tokens=0,
    task_category=MODEL_CATEGORY_GENERAL,
    model_override="",
    health_tracker=None,
    metadata_by_id=None,
    source_discovered="discovered",
    source_static="static",
    category_preferences=None,
):
    """Rank already-validated free candidates for one prompt."""
    normalized_category = normalize_task_category(task_category)
    override = normalize_model_override(model_override) if model_override else ""
    metadata_by_id = metadata_by_id if isinstance(metadata_by_id, dict) else {}
    required_context = 0
    try:
        required_context = max(0, int(task_context_tokens or 0))
    except (TypeError, ValueError, OverflowError):
        required_context = 0

    unique = []
    seen = set()
    for candidate in candidates or ():
        model_id = candidate_model_id(candidate)
        key = model_id.casefold()
        if not model_id or key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    if required_context:
        known_context = [item for item in unique if candidate_context_length(item) is not None]
        fitting_context = [
            item for item in known_context
            if candidate_context_length(item) >= required_context
        ]
        if known_context and not fitting_context:
            return []
        if fitting_context:
            unique = fitting_context + [item for item in unique if candidate_context_length(item) is None]

    override_key = override.casefold()

    def key(candidate):
        model_id = candidate_model_id(candidate)
        metadata = metadata_by_id.get(model_id.casefold())
        signals = category_signals_for_candidate(candidate, metadata)
        source_rank = 0 if candidate_source(candidate, source_discovered) == source_discovered else 1
        static_rank = candidate_static_order(candidate)
        context_length = candidate_context_length(candidate)
        context_rank = 0 if context_length is not None and context_length >= required_context else 1
        category_rank = 0 if signals.get(normalized_category) else 1
        category_strength = -len(signals.get(normalized_category, ()))
        health_rank = _health_key(candidate, health_tracker)
        return (
            0 if override and model_id.casefold() == override_key else 1,
            context_rank,
            category_rank,
            _preference_rank(model_id, normalized_category, category_preferences),
            health_rank,
            category_strength,
            source_rank,
            static_rank,
            -context_length if context_length is not None else 0,
            model_id.casefold(),
            model_id,
        )

    return sorted(unique, key=key)


def selection_reason(
    candidate,
    *,
    task_context_tokens=0,
    task_category=MODEL_CATEGORY_GENERAL,
    model_override="",
    health_tracker=None,
    metadata=None,
):
    if candidate is None:
        return "no eligible explicitly free candidate"
    model_id = candidate_model_id(candidate)
    override = normalize_model_override(model_override) if model_override else ""
    if override and model_id.casefold() == override.casefold():
        base = "override-explicit-free"
    else:
        category = normalize_task_category(task_category)
        signals = category_signals_for_candidate(candidate, metadata)
        if signals.get(category):
            base = f"{category}-matched"
        elif category == MODEL_CATEGORY_GENERAL and signals.get("coding"):
            base = "coding-capable"
        else:
            base = f"{category}-fallback"
    context_length = candidate_context_length(candidate)
    if context_length is None:
        context = "context-unknown"
    elif context_length >= max(0, int(task_context_tokens or 0)):
        context = "context-fit"
    else:
        context = "context-too-small"
    health = ""
    if health_tracker is not None:
        try:
            health = f"; {health_tracker.selection_reason(model_id)}"
        except (AttributeError, TypeError, ValueError):
            pass
    return f"{base}; {context}{health}"


def classify_model_failure(error):
    """Classify provider failures so fallback evidence explains busy models."""
    text = str(error or "").casefold()
    if re.search(r"\b(?:408|409|425|429|500|502|503|504)\b", text):
        return MODEL_FAILURE_BUSY
    if any(term in text for term in (
        "rate limit",
        "ratelimit",
        "too many request",
        "overloaded",
        "over capacity",
        "temporarily busy",
        "provider is busy",
        "model is busy",
    )):
        return MODEL_FAILURE_BUSY
    if any(term in text for term in (
        "timeout",
        "timed out",
        "unavailable",
        "connection failed",
        "connection reset",
        "service down",
    )):
        return MODEL_FAILURE_UNAVAILABLE
    return MODEL_FAILURE_ERROR


def failure_label(failure_kind):
    return {
        MODEL_FAILURE_BUSY: "busy/rate-limited",
        MODEL_FAILURE_UNAVAILABLE: "unavailable",
        MODEL_FAILURE_ERROR: "failed",
    }.get(failure_kind, "failed")
