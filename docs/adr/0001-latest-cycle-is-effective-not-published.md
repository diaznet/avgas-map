# ADR-0001: "Latest" cycle and the publish/effective relationship

## Status
Accepted

## Context
AIRAC data is published roughly 28 days before it becomes legally effective. The
front-end defaults to the "latest" cycle and most pilots will never change the
selector, so "latest" must never resolve to data that is not yet in force.

Under the current pipeline trigger, the pipeline runs **on** an AIRAC effective
date and publishes that cycle at that moment. It does **not** pre-publish future
cycles. Therefore the newest *published* cycle is always already in force, and
"newest published" and "newest effective on or before today" coincide.

## Decision
"Latest" is the newest AIRAC cycle whose effective date is on or before today.
Because the pipeline only publishes a cycle on its effective date (no
pre-publishing), the pipeline may bake `latest` = the newest successfully
published cycle into the manifest, and the front-end simply reads it. No daily
recomputation is required.

## Consequences
- The default map view never shows not-yet-in-force data, because no
  future-effective cycle is ever published.
- If a run fails or is skipped on an effective date, the newest published cycle
  lags the in-force cycle. `latest` then points at the newest data we actually
  have, which is the honest and safe answer.
- **Tripwire**: this simplification depends entirely on the "publish only on the
  effective date, never pre-publish" trigger. If a future change pre-publishes
  upcoming cycles (e.g. to stage data early), future-effective cycles become
  possible and `latest` MUST revert to effective-date logic computed against
  today (newest cycle with effective_date <= today), not "newest published".
  The manifest already carries per-cycle effective dates to support this.

## Alternatives considered
- **Front-end computes latest from per-cycle effective dates on every load**:
  necessary only if future-effective cycles can exist. Not needed under the
  current no-pre-publish trigger; kept as the documented fallback if that
  assumption ever changes.
