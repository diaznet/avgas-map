"""Country parser registry.

Each enabled country provides a CountryParser implementation. A parser's sole
job is to turn that country's chart documents (already retrieved) into
ICAO-keyed fuel records conforming to the normalized schema. Retrieval and the
OpenAIP coordinate join are shared and live outside the providers.
"""

from __future__ import annotations

from avgasmap.interface import CountryParser

# Populated below once concrete parsers are imported. Kept as a function to
# avoid import cycles and to make the enabled set explicit.
_REGISTRY: dict[str, CountryParser] = {}


def register(parser: CountryParser) -> None:
    """Register a country parser under its `code` (lowercased ICAO prefix)."""
    _REGISTRY[parser.code] = parser


def enabled_parsers() -> dict[str, CountryParser]:
    """Return the mapping of provider code (lowercased ICAO prefix) -> parser."""
    return dict(_REGISTRY)


def get_parser(code: str) -> CountryParser:
    """Look up a provider by its code (lowercased ICAO prefix, e.g. 'lf')."""
    return _REGISTRY[code]


def _load_builtin_parsers() -> None:
    """Import built-in parsers so they self-register. Called lazily."""
    # Import here to avoid import cycles at module load.
    from avgasmap.providers.lf import LfParser  # noqa: F401

    if "lf" not in _REGISTRY:
        register(LfParser())


def ensure_loaded() -> dict[str, CountryParser]:
    """Ensure built-in parsers are registered, then return the registry."""
    _load_builtin_parsers()
    return enabled_parsers()
