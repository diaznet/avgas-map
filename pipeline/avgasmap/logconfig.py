"""Shared logging setup for the pipeline.

Call `configure(verbose)` once at startup (the CLI does this). Modules obtain a
logger with `logging.getLogger(__name__)` and log normally; output goes to
stderr with timestamps. INFO by default, DEBUG with --verbose.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure(verbose: bool = False) -> None:
    global _CONFIGURED
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                          datefmt="%H:%M:%S")
    )
    root = logging.getLogger("avgasmap")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the 'avgasmap' namespace."""
    return logging.getLogger(name)
