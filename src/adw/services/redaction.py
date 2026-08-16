"""Redaction — D12, I3, G12.

Runs **before** anything is persisted, never at render time. The store is
append-only, so a value written unredacted stays unredacted permanently; hiding
it at display leaves the secret in the store forever and turns the audit trail
into a credential repository. That is the opposite of what `CLAUDE.md` §4 asks
for, and it is why the order here is not negotiable.

Two mechanisms, because secrets arrive two ways:

* **By key name** — a mapping whose key looks like a credential holder has its
  *value* replaced regardless of shape. This catches the common case where the
  value itself is unremarkable.
* **By value shape** — a string matching a known credential pattern is replaced
  wherever it appears, including inside prose.

Detection is imperfect and that is stated rather than hidden. The backstop is
encryption at rest plus key destruction (D1): a miss is unreadable to anyone
without the tenant key, and permanently unreadable once it is destroyed. The
precision target matters as much as recall — over-redacting a genuine financial
figure would silently corrupt an artifact, so patterns are anchored and specific
rather than greedy.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

REDACTED: Final = "[REDACTED]"

SENSITIVE_KEY_PATTERN: Final = re.compile(
    r"(password|passwd|secret|token|api[-_]?key|access[-_]?key|private[-_]?key"
    r"|credential|authorization|auth[-_]?header|connection[-_]?string|dsn"
    r"|session[-_]?id|cookie|bearer)",
    re.IGNORECASE,
)
"""Key names whose values are replaced whatever they contain."""

VALUE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{16,}=*", re.IGNORECASE)),
    ("basic_auth", re.compile(r"\bBasic\s+[A-Za-z0-9+/]{16,}=*", re.IGNORECASE)),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("url_credentials", re.compile(r"\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s/@]+@")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
)
"""Credential shapes recognisable without knowing the key they arrived under."""


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """A redacted value together with what was removed from it.

    ``findings`` names the *rules* that fired, never the values they matched —
    a redaction report that quotes the secret has not redacted anything.
    """

    value: object
    findings: tuple[str, ...] = field(default=())

    @property
    def count(self) -> int:
        return len(self.findings)

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


def _redact_text(text: str, findings: list[str]) -> str:
    result = text
    for name, pattern in VALUE_PATTERNS:
        if pattern.search(result):
            findings.append(f"value:{name}")
            if name == "url_credentials":
                # Preserve the scheme and user so the record still says which
                # system was reached and as whom — only the secret goes.
                result = pattern.sub(rf"\1:{REDACTED}@", result)
            else:
                result = pattern.sub(REDACTED, result)
    return result


def _walk(value: object, findings: list[str], key_hint: str | None = None) -> object:
    if key_hint is not None and SENSITIVE_KEY_PATTERN.search(key_hint):
        findings.append(f"key:{key_hint}")
        return REDACTED

    if isinstance(value, str):
        return _redact_text(value, findings)
    if isinstance(value, Mapping):
        return {str(k): _walk(v, findings, str(k)) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_walk(item, findings) for item in value]
    if isinstance(value, bytes | bytearray):
        # Bytes cannot be inspected meaningfully and cannot be canonicalized;
        # callers hand over decoded content or an opaque blob reference.
        return value
    return value


def redact(value: object) -> RedactionResult:
    """Return ``value`` with credentials removed, and what was removed.

    Traverses mappings and sequences. Redacts by key name first — a sensitive key
    is redacted whatever its value looks like — then by value shape.
    """
    findings: list[str] = []
    cleaned = _walk(value, findings)
    return RedactionResult(value=cleaned, findings=tuple(findings))
