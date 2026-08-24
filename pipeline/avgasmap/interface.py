"""The common country-parser interface.

A country parser's sole responsibility is to turn that country's chart documents
(already retrieved from the shared autorouter WebDAV) into ICAO-keyed fuel
records that conform to the normalized schema. A parser:
  - does NOT perform retrieval (that is shared),
  - does NOT assign coordinates (the shared OpenAIP join does),
  - may parse its documents however it likes (chart type, layout, language).

See CONTEXT.md ("Country parser", "Fuel record") and design.md.
"""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict, runtime_checkable


class FuelRecord(TypedDict):
    """One aerodrome's fuel facts, keyed by ICAO. No coordinates."""

    icao: str
    name: str | None            # parser may provide; OpenAIP is the fallback
    fuel_state: Literal["available", "nil", "unknown"]
    avgas_grades: list[str]     # subset of schema.AVGAS_GRADES
    jet_a1: bool                # secondary; never affects AVGAS classification
    conditions: dict            # closed shape, see CONTEXT.md "Condition flags"
    source_text: str            # verbatim source fuel text (FR: raw AVT block)
    amdt: str | None            # source effective-date marker (FR: "NN/YY")


@runtime_checkable
class CountryParser(Protocol):
    """Interface every country module implements.

    A provider is identified by its lowercased ICAO prefix (`code`, e.g. "lf"
    for France) everywhere — folder, registry key, iteration, and the published
    `country`/attribution (uppercased there). The ISO country code(s) are
    declared separately in `openaip_iso` and used ONLY for the OpenAIP fetch,
    whose files are ISO-keyed. See CONTEXT.md.
    """

    code: str                   # lowercased ICAO prefix, e.g. "lf"
    icao_pattern: str           # regex an ICAO must match, e.g. r"^LF[A-Z]{2}$"
    openaip_iso: list[str]      # ISO cc(s) for the OpenAIP fetch, e.g. ["fr"]

    def chart_paths(self, country_dir: str) -> dict[str, str]:
        """Map ICAO -> local path of the chart document to parse.

        `country_dir` is a local directory populated by the shared retrieval
        step. Implementations filter to their own aerodromes (via icao_pattern)
        and skip entries without a usable chart.
        """
        ...

    def parse(self, icao: str, chart_path: str, md_dump_dir: str = "") -> FuelRecord:
        """Parse one aerodrome's chart document into a FuelRecord.

        `md_dump_dir`, when non-empty, is a directory into which the provider may
        write the converted intermediate text (e.g. `<ICAO>.md`) for debugging
        (`--keep-intermediates`). Providers without an intermediate form may
        ignore it.
        """
        ...

    # Optional: providers with heavy/native chart-conversion dependencies may
    # implement `check_dependencies()` to import-probe them at the start of a
    # live run, raising an actionable error if they are missing/broken. The
    # pipeline calls it if present. Providers without such deps omit it.
