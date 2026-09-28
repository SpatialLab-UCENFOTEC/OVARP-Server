"""
Open Virtual Agent Research Platform (OVARP) — Identifier Validation

Profile and scenario ids become filenames. An id carrying path separators would
write outside the directory it belongs to, so every entry point that persists
one runs it through here first.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import re
from pathlib import Path

SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UnsafeIdentifierError(ValueError):
    """Raised when an id could not be used as a filename safely."""


def validate_identifier(value: str, kind: str = "id") -> str:
    """Return the id unchanged, or raise if it is not a bare filename."""
    if not SAFE_IDENTIFIER.fullmatch(value or ""):
        raise UnsafeIdentifierError(
            f"Invalid {kind} '{value}': use only letters, digits, hyphen and "
            "underscore, up to 64 characters"
        )
    return value


def safe_path(directory: Path, identifier: str, suffix: str = ".yaml") -> Path:
    """Build ``<directory>/<identifier><suffix>`` and prove it stayed inside.

    The pattern check already rejects separators; resolving afterwards is the
    belt that catches anything the pattern is later relaxed to allow.
    """
    validate_identifier(identifier)
    directory = Path(directory).resolve()
    candidate = (directory / f"{identifier}{suffix}").resolve()
    if directory not in candidate.parents:
        raise UnsafeIdentifierError(f"Refusing to write outside {directory}")
    return candidate
