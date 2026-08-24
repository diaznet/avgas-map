"""Shared chart retrieval from the autorouter WebDAV.

This is the single, fixed source of chart documents for every country (per
CONTEXT.md / R5.1); country parsers never fetch. Retrieval lays out one PDF per
aerodrome as `<dest_dir>/<ICAO>.pdf`, which is exactly what a parser's
`chart_paths()` expects.

Credentials come only from env vars AUTOROUTER_USER / AUTOROUTER_PASS (portable;
GitHub secrets in CI, shell/.env locally). Fetching is polite: bounded
concurrency, retry with exponential backoff, a descriptive User-Agent, and a
fresh fetch each run (no cross-run cache). Secrets are never logged.

The WebDAV client is injected (a small protocol) so the download/discovery logic
is unit-testable without a network or real credentials.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import quote

from avgasmap.logconfig import get_logger

log = get_logger(__name__)

WEBDAV_ROOT = "https://www.autorouter.aero/webdav"
USER_AGENT = "AVGAS-Map/0.1 (+https://github.com/; aerodrome AVGAS map pipeline)"

DEFAULT_WORKERS = 6
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1.5  # seconds, exponential base


class WebDavClient(Protocol):
    """Minimal WebDAV surface used by retrieval (subset of webdavclient3)."""

    def list(self, remote_path: str) -> list[str]: ...
    def download_to_bytes(self, remote_path: str) -> bytes: ...


class MissingCredentialsError(RuntimeError):
    pass


def _require_credentials() -> tuple[str, str]:
    user = os.environ.get("AUTOROUTER_USER")
    pw = os.environ.get("AUTOROUTER_PASS")
    if not user or not pw:
        raise MissingCredentialsError(
            "AUTOROUTER_USER / AUTOROUTER_PASS must be set (env or .env). "
            "No fetch performed."
        )
    return user, pw


class Webdav3Client:
    """Adapter around webdavclient3 implementing WebDavClient.

    Constructed lazily (only when a real fetch runs) so tests and offline/dry
    runs never import or require the dependency or credentials.
    """

    def __init__(self, user: str, password: str, root: str = WEBDAV_ROOT, timeout: int = 60):
        from webdav3.client import Client  # imported lazily

        self._root = root.rstrip("/")
        self._auth = (user, password)
        self._timeout = timeout
        self._client = Client(
            {
                "webdav_hostname": root,
                "webdav_login": user,
                "webdav_password": password,
                "webdav_timeout": timeout,
            }
        )

    def list(self, remote_path: str) -> list[str]:
        return self._client.list(remote_path)

    def download_to_bytes(self, remote_path: str) -> bytes:
        # NOTE: we do NOT use webdavclient3's download_from here. In 3.14.6 it
        # unconditionally reads response.headers['content-length'] for a progress
        # callback, which KeyErrors against the autorouter server (it responds
        # without that header, likely chunked). A plain authenticated GET is
        # simpler and robust. URL-encode each path segment, preserving slashes.
        import requests

        url = self._root + "/" + "/".join(quote(seg) for seg in remote_path.split("/"))
        resp = requests.get(
            url, auth=self._auth, timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return resp.content


@dataclass
class RetrievalResult:
    icao: str
    outcome: str  # "downloaded" | "no-pdf" | "error: ..."
    local_path: str | None = None


# France WebDAV layout (spike): France/<ICAO> - <name>/VFR/AD 2 <ICAO> VAC.pdf
_ICAO_FOLDER_RE = re.compile(r"^(LF[A-Z]{2})\b")
_VAC_RE = re.compile(r"\bVAC\b", re.IGNORECASE)


def _icao_from_folder(folder: str) -> str | None:
    m = _ICAO_FOLDER_RE.match(folder.rstrip("/"))
    return m.group(1) if m else None


def list_france_aerodromes(client: WebDavClient, france_dir: str = "France") -> list[str]:
    """Return LF** aerodrome folder names under the France dir (sorted)."""
    entries = client.list(france_dir)
    folders = [e.rstrip("/") for e in entries if e.endswith("/") and not e.startswith(".")]
    return sorted(f for f in folders if _ICAO_FOLDER_RE.match(f))


def find_vac_pdf(client: WebDavClient, folder: str, france_dir: str = "France") -> str | None:
    """Return the remote path of the VAC PDF in an aerodrome's VFR/ folder, or None."""
    vfr = f"{france_dir}/{folder}/VFR"
    try:
        files = client.list(vfr)
    except Exception:
        return None
    pdfs = [f for f in files if f.lower().endswith(".pdf")]
    if not pdfs:
        return None
    vac = [f for f in pdfs if _VAC_RE.search(f)]
    chosen = (vac or sorted(pdfs))[0]
    return f"{vfr}/{chosen}"


def _download_with_retry(
    client: WebDavClient,
    remote_path: str,
    dest_path: str,
    retries: int,
    backoff: float,
    sleep: Callable[[float], None],
) -> None:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            data = client.download_to_bytes(remote_path)
            with open(dest_path, "wb") as fh:
                fh.write(data)
            return
        except Exception as exc:  # noqa: BLE001 — retry any transport error
            last_exc = exc
            if attempt < retries - 1:
                sleep(backoff ** attempt)
    # Clean up any partial file.
    if os.path.exists(dest_path):
        os.remove(dest_path)
    raise last_exc  # type: ignore[misc]


def retrieve_france(
    dest_dir: str,
    client: WebDavClient | None = None,
    *,
    workers: int = DEFAULT_WORKERS,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    france_dir: str = "France",
    sleep: Callable[[float], None] = time.sleep,
) -> list[RetrievalResult]:
    """Fetch all French VAC PDFs into dest_dir as <ICAO>.pdf.

    If `client` is None, a real Webdav3Client is built from env-var credentials.
    Bounded concurrency + retry/backoff keep it polite. Returns per-aerodrome
    outcomes (including no-pdf / error) for the processing report.
    """
    os.makedirs(dest_dir, exist_ok=True)

    if client is None:
        user, pw = _require_credentials()
        log.info("Connecting to autorouter WebDAV as %s", user)
        client = Webdav3Client(user, pw)

    log.info("Listing French aerodromes under %s/%s ...", WEBDAV_ROOT, france_dir)
    folders = list_france_aerodromes(client, france_dir)
    total = len(folders)
    log.info("Found %d LF** aerodrome folders; fetching VAC PDFs with %d workers",
             total, workers)

    def work(folder: str) -> RetrievalResult:
        icao = _icao_from_folder(folder)
        if icao is None:
            return RetrievalResult(folder, "error: no ICAO in folder name")
        remote = find_vac_pdf(client, folder, france_dir)
        if not remote:
            return RetrievalResult(icao, "no-pdf")
        dest = os.path.join(dest_dir, f"{icao}.pdf")
        try:
            _download_with_retry(client, remote, dest, retries, backoff, sleep)
            return RetrievalResult(icao, "downloaded", dest)
        except Exception as exc:  # noqa: BLE001
            return RetrievalResult(icao, f"error: {exc}")

    results: list[RetrievalResult] = []
    done = ok = failed = missing = 0
    # Log progress every ~5% (at least every 10) so a long fetch shows movement.
    step = max(10, total // 20) if total else 1
    # Keep our own pool handle so a Ctrl-C can shut it down WITHOUT waiting for
    # the whole submitted queue to drain. A plain `with ThreadPoolExecutor(...)`
    # block calls shutdown(wait=True) on exit, which blocks until every one of
    # the ~400 already-submitted downloads finishes — making Ctrl-C feel dead.
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        futures = {pool.submit(work, f): f for f in folders}
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            done += 1
            if res.outcome == "downloaded":
                ok += 1
            elif res.outcome == "no-pdf":
                missing += 1
            else:
                failed += 1
                log.warning("  %s: %s", res.icao, res.outcome)
            # Progress line reports success/failure so health is visible, not
            # inferred from the warnings above (done counts every outcome).
            if done % step == 0 or done == total:
                log.info("  processed %d/%d — %d ok, %d failed, %d no-pdf",
                         done, total, ok, failed, missing)
    except KeyboardInterrupt:
        # Drop all pending downloads immediately and don't wait; only the few
        # in-flight requests (each bounded by the client timeout) linger.
        log.warning("Interrupted — cancelling %d pending downloads ...",
                    total - done)
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        # Normal completion still needs an explicit shutdown (no `with` block).
        pool.shutdown(wait=False)

    log.info("Retrieval done: %d downloaded, %d no-pdf, %d errors",
             ok, missing, failed)

    results.sort(key=lambda r: r.icao)
    return results
