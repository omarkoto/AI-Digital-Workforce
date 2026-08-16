"""RFC 8785 JSON Canonicalization — D23.

A hash is meaningless without a deterministic byte representation. Key ordering,
number formatting, and Unicode escaping must be fixed before the first record is
written, or verification silently fails later against records that can no longer
be recomputed.

The scheme is *not* implemented here. It is delegated to ``rfc8785`` (Trail of
Bits, Apache-2.0, pure Python, no transitive dependencies, ships ``py.typed``),
and pinned by the official test vectors committed under
``tests/fixtures/rfc8785``. A canonicalizer sitting directly beneath the audit
chain is the wrong place for a hand-rolled implementation.

Scope: this applies only to structures the platform itself constructs for
hashing. Content is digested over raw bytes — see :mod:`adw.domain.hashing` and
D29.
"""

from __future__ import annotations

from typing import Any, cast

import rfc8785

from adw.domain.errors import CanonicalizationFailedError


def canonicalize(value: object) -> bytes:
    """Return the RFC 8785 canonical UTF-8 encoding of ``value``.

    The parameter is typed ``object`` deliberately: this is a runtime boundary,
    and rejecting unsupported input is part of its job rather than something a
    caller is trusted to have done.

    Raises:
        CanonicalizationFailedError: if ``value`` contains anything RFC 8785
            cannot represent — a non-finite float, an out-of-range integer, or a
            type with no JSON equivalent.
    """
    try:
        # The cast is the point of this wrapper, not a shortcut around it: the
        # library's signature assumes pre-validated JSON, and validating is
        # exactly the job being delegated. Rejection happens below.
        return rfc8785.dumps(cast(Any, value))
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        # The offending value is not interpolated: it may be tenant content.
        msg = f"value is not canonicalizable under RFC 8785 ({exc.__class__.__name__})"
        raise CanonicalizationFailedError(msg) from exc
