"""Domain exception hierarchy.

One base so a caller can catch the whole domain in a single clause, and so a
domain failure is always distinguishable from a library or infrastructure one.

Error messages describe *what* was wrong structurally. They never interpolate a
payload, a plaintext, or a secret, because messages reach logs and log output is
subject to the same redaction rule as everything else (D12).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for every error raised by the domain layer."""


class InvalidIdentifierError(DomainError):
    """An identifier was not of the form the operation requires."""


class CanonicalizationFailedError(DomainError):
    """A value could not be canonicalized under RFC 8785.

    Raised in place of the library's own exception type so that callers depend
    on the domain's vocabulary rather than on a third-party package.
    """


class ChainIntegrityError(DomainError):
    """An audit chain is inconsistent, or an input to sealing was invalid.

    Raised both when a chain fails verification and when a record cannot be
    sealed safely — for example an ambiguous timestamp, which would make the
    resulting hash meaningless.
    """


class TransitionsNotAvailableError(DomainError):
    """A state transition was requested before the rules exist.

    Task 2 deliberately ships no transition tables. See
    :mod:`adw.domain.transitions` for the unresolved decisions that block them.
    """
