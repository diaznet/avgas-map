"""AVGAS-Map data pipeline.

Retrieves aerodrome charts (shared, from the autorouter WebDAV), parses fuel
information per country behind a common interface, joins coordinates from
OpenAIP by ICAO, validates and assembles a normalized GeoJSON dataset, and
publishes it per AIRAC cycle. See .kiro/specs/avgas-map/ for the full spec and
CONTEXT.md for domain vocabulary.
"""

__version__ = "0.1.0"
