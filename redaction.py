"""Credential redaction helpers shared across the app."""

import re

SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|x-api-key|authorization|bearer|token|secret|credential|password)\s*[:=]?\s*\S+|\b(?:sk-or-v1|sk-proj|sk)-[A-Za-z0-9._-]+"
)


def redact_sensitive_text(text, secrets=None):
    """Remove API keys and common credential-shaped values from UI/log text."""
    redacted = str(text or "")
    candidates = [str(secret) for secret in (secrets or []) if secret and len(str(secret)) >= 8]
    for secret in sorted(set(candidates), key=len, reverse=True):
        redacted = redacted.replace(secret, "[redacted]")
    paired_patterns = (
        r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)",
        r"(?i)(x-api-key\s*[:=]\s*)([^\s,;]+)",
        r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)",
        r"(?i)(authorization\s*[:=]\s*)([^\s,;]+(?:\s+[^\s,;]+)?)",
        r"(?i)(bearer\s+)([^\s,;]+)",
        r"(?i)(\b(?:token|secret|credential|password|private[_-]?key)\s*[:=]\s*)([^\s,;]+)",
    )
    for pattern in paired_patterns:
        redacted = re.sub(pattern, lambda match: match.group(1) + "[redacted]", redacted)
    redacted = re.sub(r"(?i)\b(?:sk-or-v1|sk-proj|sk)-[A-Za-z0-9._-]+", "[redacted]", redacted)
    redacted = re.sub(
        r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        "[redacted private key]",
        redacted,
    )
    return redacted
