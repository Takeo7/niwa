"""Secret redaction for logs and event payloads (Phase 6, SEC-02).

Applies a set of regex patterns to replace known secret shapes with
``[REDACTED]``. Designed to run before persisting build logs and before
rendering task events in the UI.

Patterns covered:
- GitHub tokens (ghp_, gho_, ghs_, ghr_, github_pat_)
- Anthropic API keys (sk-ant-)
- Bearer tokens
- AWS-style access keys
- Generic high-entropy strings in key=value form
- Niwa API tokens (niwa_)
"""

from __future__ import annotations

import re

_PATTERNS: list[re.Pattern[str]] = [
    # GitHub personal/app tokens
    re.compile(r"(ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}", re.IGNORECASE),
    # Anthropic API key
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}", re.IGNORECASE),
    # Niwa API token
    re.compile(r"niwa_[A-Fa-f0-9]{30,}", re.IGNORECASE),
    # Bearer tokens (header value)
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    # AWS-style access keys
    re.compile(r"AKIA[A-Z0-9]{16,}", re.IGNORECASE),
    # Generic: key=<long token> or key: <long token>
    re.compile(
        r"(?i)(token|secret|password|api[-_]?key|auth[-_]?key)\s*[=:]\s*[\"']?([A-Za-z0-9_\-\.]{20,})[\"']?"
    ),
    # URLs with credentials: scheme://user:pass@host
    re.compile(r"://[^:@\s]+:[^:@\s]+@"),
]

_REPLACEMENT = "[REDACTED]"


def redact(text: str) -> str:
    """Return text with known secret patterns replaced by [REDACTED]."""
    for pattern in _PATTERNS:
        text = pattern.sub(_redact_match, text)
    return text


def _redact_match(m: re.Match[str]) -> str:
    full = m.group(0)
    # For key=value patterns, keep the key name visible
    if m.lastindex and m.lastindex >= 2:
        key = m.group(1)
        return f"{key}=[REDACTED]"
    # For URLs with credentials keep scheme
    if "://" in full:
        scheme = full.split("://")[0]
        return f"{scheme}://[REDACTED]@"
    return _REPLACEMENT
