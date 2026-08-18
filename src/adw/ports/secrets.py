"""The secret store port — `CLAUDE.md` §4, `ARCHITECTURE.md` §13.

**Never expose a secret to an LLM.** No credential, token, key, or connection
string enters a prompt, a tool argument the model composes, a log the model
reads, or an artifact. The model sees a *reference name* and nothing else.

This port is where a reference becomes a value, and the Tool Gateway is the only
component that may call it — step 4 of the eleven, inside the gateway, after
authorization and before execution. Nothing above the gateway ever holds a
resolved secret, which is why nothing above the gateway can leak one.

Neither Phase 3 tool needs a credential. The port exists anyway, because
retrofitting a secret boundary after tools already pass raw arguments is exactly
the change that never gets made.

**A resolved value must never be returned to a caller, put in evidence, or
written to a log.** :class:`SecretValue` exists to make that hard to do by
accident: it refuses to render itself.
"""

from __future__ import annotations

import re
from typing import Final, Protocol, runtime_checkable

from adw.domain.errors import DomainError

REFERENCE_PATTERN: Final = re.compile(r"^secret://[a-z][a-z0-9_-]*(/[a-z0-9_-]+)*$")
"""What a reference looks like: ``secret://ollama/api-key``.

Constrained deliberately. A reference is the one part of the secret path a tool
descriptor can carry, and a descriptor is content — so the syntax has to be
narrow enough that a name cannot smuggle a path traversal or a URL."""


class SecretError(DomainError):
    """Base for secret resolution failures.

    Messages here name the *reference*, never the value. An error that quotes a
    secret has leaked it into every log that catches it.
    """


class InvalidSecretReferenceError(SecretError):
    """The reference was not of the required form."""


class SecretNotFoundError(SecretError):
    """No secret is stored under that reference."""


class SecretValue:
    """A resolved secret that refuses to appear in output.

    ``repr`` and ``str`` both return a placeholder, so an accidental f-string, a
    log line, a traceback, or a dict dumped into evidence yields nothing useful.
    Reading the real value takes an explicit call, which is greppable in review.

    This is a guardrail, not a guarantee — the value is in memory and Python
    cannot prevent a determined caller from getting at it. It exists to make the
    unsafe thing deliberate rather than the default.
    """

    __slots__ = ("_reference", "_value")

    def __init__(self, reference: str, value: str) -> None:
        self._reference = reference
        self._value = value

    @property
    def reference(self) -> str:
        """The name. Safe to log, safe to record as evidence."""
        return self._reference

    def reveal(self) -> str:
        """Return the secret. Call this only at the boundary that consumes it."""
        return self._value

    def __repr__(self) -> str:
        return f"SecretValue(reference={self._reference!r}, value=<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


def validate_reference(reference: str) -> str:
    """Return ``reference`` if it is well-formed, else raise.

    Raises:
        InvalidSecretReferenceError: if it does not match the reference syntax.
    """
    if not REFERENCE_PATTERN.match(reference):
        msg = f"not a valid secret reference: {reference!r}"
        raise InvalidSecretReferenceError(msg)
    return reference


@runtime_checkable
class SecretStore(Protocol):
    """Resolves secret references to values.

    Called only by the Tool Gateway. Any other caller is a bug, and the layering
    test enforces it.
    """

    def resolve(self, reference: str) -> SecretValue:
        """Return the secret stored under ``reference``.

        Raises:
            InvalidSecretReferenceError: the reference was malformed.
            SecretNotFoundError: nothing is stored under it.
        """
        ...

    def has(self, reference: str) -> bool:
        """Whether a secret exists, without resolving it.

        Lets the gateway fail a call *before* execution when a descriptor names a
        secret nobody configured, rather than part-way through.
        """
        ...
