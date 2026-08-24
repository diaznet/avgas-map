"""The never-worse guard: refuse to publish a dataset that looks broken.

Before publishing a new cycle we compare its feature count against the most
recent successfully published dataset (whatever cycle that was — cycle-agnostic,
so a re-run of the same cycle is compared to the last good publish). Two checks:

  1. Absolute floor  — catches total breakage (e.g. WebDAV auth failed -> ~0).
  2. Relative drop    — catches partial breakage (a parser regression silently
                        dropping a chunk).

On failure the pipeline must NOT publish and must leave the previous published
cycle intact (R7.4/R7.5). A documented manual override allows a legitimately
large change to proceed.

Thresholds are configurable constants; defaults suit France alone (~296 AVGAS
aerodromes in the spike, so floor 200 leaves headroom).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_FLOOR = 200
DEFAULT_MAX_DROP = 0.20  # abort if new count < previous * (1 - 0.20)


@dataclass
class GuardResult:
    ok: bool
    reason: str  # "" when ok, else a human-readable failure explanation


def check(
    new_count: int,
    previous_count: int | None,
    *,
    floor: int = DEFAULT_FLOOR,
    max_drop: float = DEFAULT_MAX_DROP,
    override: bool = False,
) -> GuardResult:
    """Return whether a dataset with `new_count` features may be published.

    previous_count: feature count of the last successfully published dataset,
    or None if there is no prior publish (first run).
    override: bypasses the relative-drop check for a legitimately large change;
    the absolute floor is ALWAYS enforced (even total breakage is never ok).
    """
    # Absolute floor is non-negotiable — a near-empty dataset is breakage.
    if new_count < floor:
        return GuardResult(
            ok=False,
            reason=(
                f"feature count {new_count} is below the absolute floor {floor}; "
                "refusing to publish (likely a retrieval/parse failure)."
            ),
        )

    if previous_count is None or previous_count == 0:
        # No prior good publish to compare against; the floor passing is enough.
        return GuardResult(ok=True, reason="")

    if override:
        return GuardResult(ok=True, reason="relative-drop check overridden by operator")

    min_allowed = previous_count * (1.0 - max_drop)
    if new_count < min_allowed:
        drop_pct = (1.0 - new_count / previous_count) * 100
        return GuardResult(
            ok=False,
            reason=(
                f"feature count dropped {drop_pct:.1f}% "
                f"({previous_count} -> {new_count}), exceeding the "
                f"{max_drop*100:.0f}% max-drop threshold; refusing to publish. "
                "Re-run, or pass the manual override if this change is legitimate."
            ),
        )

    return GuardResult(ok=True, reason="")
