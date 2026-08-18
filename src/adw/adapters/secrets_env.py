"""A development secret store backed by environment variables.

Refuses to start outside ``dev``, the same refusal the local key store and blob
store already carry. Production resolves references from a managed secret store;
this exists so the gateway's resolution seam is exercised from the first commit
rather than stubbed out and retrofitted later.

Mapping: ``secret://ollama/api-key`` reads ``ADW_SECRET_OLLAMA_API_KEY``. The
prefix keeps secrets out of the ``Settings`` namespace deliberately — ``Settings``
uses ``extra="forbid"`` and would reject them, and more importantly a secret has
no business being a validated application setting that gets logged with the rest
of the configuration.
"""

from __future__ import annotations

import os
from typing import Final

from adw.config import AppEnv, get_settings
from adw.ports.secrets import (
    SecretNotFoundError,
    SecretValue,
    validate_reference,
)

ENV_PREFIX: Final = "ADW_SECRET_"


def environment_variable_for(reference: str) -> str:
    """Return the variable name a reference maps to.

    Public because an operator needs to know what to set, and a mapping that
    lives only inside a resolver is a mapping nobody can configure against.
    """
    path = validate_reference(reference).removeprefix("secret://")
    return ENV_PREFIX + path.replace("/", "_").replace("-", "_").upper()


class EnvironmentSecretStore:
    """Resolves secret references from environment variables. Development only."""

    def __init__(self) -> None:
        settings = get_settings()
        if settings.app_env is not AppEnv.DEV:
            msg = (
                f"EnvironmentSecretStore is development-only and refuses to start in "
                f"{settings.app_env.value!r}; configure a managed secret store instead"
            )
            raise RuntimeError(msg)

    def resolve(self, reference: str) -> SecretValue:
        variable = environment_variable_for(reference)
        value = os.environ.get(variable)
        if value is None:
            # Names the reference and the variable, never a value — there is no
            # value to name, and the habit of not interpolating one matters here
            # more than anywhere else.
            msg = f"no secret configured for {reference!r} (expected {variable})"
            raise SecretNotFoundError(msg)
        return SecretValue(reference, value)

    def has(self, reference: str) -> bool:
        return os.environ.get(environment_variable_for(reference)) is not None
