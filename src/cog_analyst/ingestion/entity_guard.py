"""Deterministic entity guard (domain-agnostic).

The LLM cannot be trusted to only emit real entity names. An ``EntityRegistry``
is a hardcoded allowlist for one field (e.g. ``reef_name``): a value that is not
EXACTLY in the registry is a data violation. The write path stays raw; callers
use these registries to validate or filter values against a known set.

Exact matching is intentional. Fuzzy matching would reintroduce the ambiguity
we are trying to eliminate. Alias reconciliation, when needed, is a deliberate
downstream step (normalize + exact match against the WEG catalog), not a guess.
"""

from __future__ import annotations

import logging
from typing import Iterable, List

logger = logging.getLogger("cog_analyst.entity_guard")


class EntityGuardViolation(Exception):
    """Raised when an extracted entity name is not in its registry."""

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(
            f"DATA VIOLATION: {field}={value!r} is not in the registry; "
            f"refusing to persist."
        )


class EntityRegistry:
    """A strict allowlist guard for a single named field.

    Parameters
    ----------
    field:
        The name of the field this registry validates (used in logs/errors),
        e.g. ``"reef_name"``.
    allowed:
        The exact set of permitted values.
    """

    def __init__(self, field: str, allowed: Iterable[str]) -> None:
        self.field = field
        self.allowed: List[str] = list(allowed)
        self._allowed_set = frozenset(self.allowed)

    def is_known(self, value: str) -> bool:
        """Return True only if ``value`` matches an allowed entry exactly.

        Leading/trailing whitespace is ignored; casing and spelling are NOT
        normalized. Unknown or misspelled values return False by design.
        """
        if not isinstance(value, str):
            return False
        return value.strip() in self._allowed_set

    def enforce(self, value: str) -> str:
        """Return the canonical value, or log + raise ``EntityGuardViolation``."""
        candidate = value.strip() if isinstance(value, str) else value
        if candidate in self._allowed_set:
            return candidate
        logger.error(
            "Blocked hallucinated/unknown %s: %r (allowed: %s)",
            self.field,
            value,
            ", ".join(self.allowed),
        )
        raise EntityGuardViolation(self.field, str(value))
