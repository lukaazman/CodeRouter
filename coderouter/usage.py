"""Token and context usage accounting (free models: cost is always $0)."""

from dataclasses import dataclass, field

DEFAULT_CONTEXT_WINDOW = 32768


def estimate_tokens(text):
    return (len(text or "") + 3) // 4


@dataclass
class UsageMeter:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    last_prompt_tokens: int = 0
    last_context_window: int = DEFAULT_CONTEXT_WINDOW
    last_model: str = ""
    last_latency_ms: int = 0
    by_model: dict = field(default_factory=dict)

    def record(self, model, prompt_tokens, completion_tokens, context_window=None, latency_ms=0):
        prompt_tokens = max(0, int(prompt_tokens or 0))
        completion_tokens = max(0, int(completion_tokens or 0))
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls += 1
        self.last_prompt_tokens = prompt_tokens
        self.last_model = model or self.last_model
        self.last_latency_ms = int(latency_ms or 0)
        if context_window:
            self.last_context_window = int(context_window)
        entry = self.by_model.setdefault(self.last_model or "unknown", [0, 0, 0])
        entry[0] += prompt_tokens
        entry[1] += completion_tokens
        entry[2] += 1

    def reset(self):
        self.__init__()

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    def context_fraction(self):
        window = self.last_context_window or DEFAULT_CONTEXT_WINDOW
        return min(1.0, self.last_prompt_tokens / window) if window else 0.0

    def short_label(self):
        if not self.calls:
            return "0 tokens · $0"
        return f"{format_tokens(self.total_tokens)} tokens · {int(self.context_fraction() * 100)}% ctx · $0"

    def report(self):
        lines = [
            f"Session usage · {self.calls} model call(s)",
            f"  prompt {format_tokens(self.prompt_tokens)} · completion {format_tokens(self.completion_tokens)} · total {format_tokens(self.total_tokens)}",
            f"  last prompt {format_tokens(self.last_prompt_tokens)} of {format_tokens(self.last_context_window)} context ({int(self.context_fraction() * 100)}%)",
            "  cost $0.00 (free models only)",
        ]
        if self.last_latency_ms:
            lines.append(f"  last latency {self.last_latency_ms} ms")
        for model, (prompt, completion, calls) in sorted(self.by_model.items()):
            lines.append(f"  {model}: {calls} call(s), {format_tokens(prompt + completion)} tokens")
        return "\n".join(lines)


def format_tokens(value):
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)
