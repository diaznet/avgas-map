# ADR-0002: ICAO code is the sole identity; no fuzzy matching

## Status
Accepted

## Context
Fuel records (from chart parsing) and coordinates (from OpenAIP) are two separate
data sources that must be joined to produce a map feature. They could be joined
on ICAO code, or on a looser combination of name and geographic proximity.

Sources occasionally disagree: a VFR strip may lack an ICAO, or OpenAIP may list
an aerodrome under a slightly different code, so an exact-ICAO join will
sometimes fail to match an aerodrome that a human could tell is "the same place".

## Decision
The ICAO code is the sole identity and join key across all data sources. Two
records refer to the same aerodrome only if their ICAO codes match exactly. When
an AVGAS aerodrome's ICAO has no exact OpenAIP match, it is dropped from the map
dataset and recorded in the processing report. No fuzzy name or coordinate
matching is performed.

## Consequences
- Some genuinely AVGAS-capable aerodromes may be absent from the map when sources
  disagree on the code. This is visible in the processing report.
- The join is deterministic, auditable, and cannot place a pin at a wrong
  location — the safe failure mode for a flight-planning aid.
- If the drop rate proves high in practice, a fuzzy-fallback strategy can be
  reconsidered in a future ADR.

## Alternatives considered
- **Name + coordinate fuzzy match**: recovers more aerodromes but risks
  attaching fuel facts to the wrong place. Rejected: a wrong pin is worse than a
  missing pin on a safety tool.
