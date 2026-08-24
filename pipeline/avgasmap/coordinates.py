"""Shared aerodrome coordinates via OpenAIP (join by ICAO).

OpenAIP publishes daily per-country airport exports as GeoJSON at a public S3
bucket. We fetch `<base><cc>_apt.geojson`, index by ICAO code, and join each
fuel record's coordinates by EXACT ICAO (ADR-0002: ICAO is the sole identity, no
fuzzy matching). An AVGAS aerodrome with no exact match is dropped from the map
dataset and recorded, never placed at a null/wrong location (R6.3).

The endpoint is configurable (OpenAIP has relocated it before). The HTTP getter
is injectable so the join logic is unit-testable without network.

Confirmed OpenAIP feature shape: properties.icaoCode, properties.name,
properties.country; geometry.coordinates = [lon, lat].
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from avgasmap.logconfig import get_logger

log = get_logger(__name__)

# Configurable endpoint (confirmed against the live bucket listing).
OPENAIP_EXPORT_BASE = "https://storage.openaip.net/openaip-system-exports/"
OPENAIP_KEY_TEMPLATE = "{country}_apt.geojson"  # {country} = ISO cc, lowercase

ATTRIBUTION = "OpenAIP"

# A JSON HTTP getter: url -> parsed JSON. Default uses requests.
JsonGetter = Callable[[str], dict]


def _default_getter(url: str) -> dict:
    import requests

    resp = requests.get(
        url,
        timeout=60,
        headers={"User-Agent": "AVGAS-Map/0.1 (aerodrome AVGAS map pipeline)"},
    )
    resp.raise_for_status()
    return resp.json()


@dataclass
class Coordinate:
    lon: float
    lat: float
    name: str | None


@dataclass
class JoinResult:
    """Outcome of joining fuel records to coordinates for the report."""

    joined: dict[str, tuple[dict, Coordinate]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)  # ICAOs with no coordinate


def export_url(country: str, base: str = OPENAIP_EXPORT_BASE,
               key_template: str = OPENAIP_KEY_TEMPLATE) -> str:
    return base + key_template.format(country=country.lower())


def build_index(geojson: dict) -> dict[str, Coordinate]:
    """Build ICAO -> Coordinate from an OpenAIP airports GeoJSON."""
    index: dict[str, Coordinate] = {}
    for feat in geojson.get("features", []):
        props = feat.get("properties") or {}
        icao = props.get("icaoCode")
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        if not icao or not isinstance(coords, list) or len(coords) != 2:
            continue
        lon, lat = coords
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            continue
        index[icao.upper()] = Coordinate(lon=float(lon), lat=float(lat), name=props.get("name"))
    return index


def fetch_country_index(
    country: str,
    getter: JsonGetter = _default_getter,
    *,
    base: str = OPENAIP_EXPORT_BASE,
    key_template: str = OPENAIP_KEY_TEMPLATE,
) -> dict[str, Coordinate]:
    """Fetch and index one country's OpenAIP airport export."""
    url = export_url(country, base, key_template)
    log.info("Fetching OpenAIP export: %s", url)
    index = build_index(getter(url))
    log.info("OpenAIP %s: %d aerodromes with coordinates", country, len(index))
    return index


def join(
    records: dict[str, dict],
    index: dict[str, Coordinate],
) -> JoinResult:
    """Join ICAO-keyed fuel records to coordinates by exact ICAO.

    Only records intended for the map (fuel_state 'available') should be passed
    in; an unmatched ICAO is reported and omitted from `joined`.
    """
    result = JoinResult()
    for icao, record in records.items():
        coord = index.get(icao.upper())
        if coord is None:
            result.unmatched.append(icao)
            continue
        result.joined[icao] = (record, coord)
    result.unmatched.sort()
    return result
