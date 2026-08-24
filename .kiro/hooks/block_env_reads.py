#!/usr/bin/env python3
"""PreToolUse guard: block the agent from reading/searching secret .env files.

Kiro pipes a JSON object describing the pending tool call on stdin. This script
inspects it and, if the tool targets a `.env` file (but not `.env.example`),
exits 2 to BLOCK the call; stderr is surfaced to the agent. Any other case
exits 0 (allow).

Enforces the AGENTS.md invariant: the agent must never read `.env` / secret
files. Documentation is the directive; this hook is the enforcement.
"""

import json
import re
import sys

# Matches `.env` or `.env.<suffix>` as a path/filename token, but NOT
# `.env.example` (the committed, secret-free template).
_ENV_TOKEN = re.compile(r"(?:^|[\\/\"'\s=])\.env(?:\.[A-Za-z0-9_-]+)?(?=[\"'\s]|$)")
_EXAMPLE = re.compile(r"\.env\.example\b")


def _references_env(blob: str) -> bool:
    # Strip .env.example mentions first so they never trip the guard.
    cleaned = _EXAMPLE.sub("", blob)
    return bool(_ENV_TOKEN.search(cleaned))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # If we can't parse the payload, fail open (don't wedge the agent on
        # unrelated calls). The AGENTS.md directive still binds behaviourally.
        return 0

    # Search the tool input (fall back to the whole payload) for a .env path.
    blob = json.dumps(payload.get("toolInput", payload), ensure_ascii=False)
    if _references_env(blob):
        sys.stderr.write(
            "Blocked: reading or searching .env / secret files is not permitted "
            "(AGENTS.md invariant). Use .env.example for the variable names.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
