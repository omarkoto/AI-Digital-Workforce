"""The domain exception hierarchy."""

from __future__ import annotations

import pytest

from adw.domain.errors import (
    CanonicalizationFailedError,
    ChainIntegrityError,
    DomainError,
    InvalidIdentifierError,
    TransitionsNotAvailableError,
)

ALL_ERRORS = [
    CanonicalizationFailedError,
    ChainIntegrityError,
    InvalidIdentifierError,
    TransitionsNotAvailableError,
]


@pytest.mark.unit
@pytest.mark.parametrize("error_type", ALL_ERRORS)
def test_every_domain_error_derives_from_the_common_base(error_type: type[Exception]) -> None:
    """One base means callers can catch the whole domain in a single clause."""
    assert issubclass(error_type, DomainError)


@pytest.mark.unit
@pytest.mark.parametrize("error_type", ALL_ERRORS)
def test_every_domain_error_is_catchable_as_the_base(error_type: type[Exception]) -> None:
    with pytest.raises(DomainError):
        raise error_type("boom")


@pytest.mark.unit
def test_domain_error_derives_from_exception_not_baseexception() -> None:
    """A domain failure must never escape a broad `except Exception` handler."""
    assert issubclass(DomainError, Exception)
