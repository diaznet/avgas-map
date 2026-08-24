"""Publish a cycle's dataset as a GitHub Release asset + regenerate the manifest.

Each AIRAC cycle is one GitHub Release, tag `airac-<YYNN>`, with a single asset
`dataset.geojson`. The manifest `index.json` lists every published cycle (with
effective_date + schema_version) and marks `latest` = the newest successfully
published cycle. Valid because the pipeline never pre-publishes future cycles
(ADR-0001).

The pipeline commits NOTHING to the repo (R7.3): datasets live in Releases, the
manifest ships with the deployed site. The GitHub API client is injectable so
this is unit-testable without network or a token.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from avgasmap import airac

ASSET_NAME = "dataset.geojson"
MANIFEST_NAME = "index.json"


def tag_for_cycle(cycle_id: str) -> str:
    return f"airac-{cycle_id}"


def dataset_filename(cycle_id: str) -> str:
    """Relative, same-origin manifest URL for a cycle's dataset (under web/data/)."""
    return f"dataset-{cycle_id}.geojson"


def cycle_from_tag(tag: str) -> str | None:
    if tag.startswith("airac-"):
        rest = tag[len("airac-"):]
        if len(rest) == 4 and rest.isdigit():
            return rest
    return None


@dataclass
class Release:
    tag: str
    asset_url: str  # download URL for the dataset.geojson asset


class GitHubReleases(Protocol):
    """Minimal GitHub Releases surface used by publishing."""

    def list_releases(self) -> list[Release]: ...
    def upsert_release_asset(self, tag: str, asset_name: str, data: bytes) -> Release: ...
    def download_asset(self, tag: str) -> bytes | None:
        """Return the `dataset.geojson` bytes for `tag`, or None if absent."""
        ...


class RestGitHubReleases:
    """Adapter over the GitHub REST API using GITHUB_TOKEN.

    Constructed lazily (only for a real publish) so tests/offline never need a
    token or the requests dependency at import time.
    """

    def __init__(self, repo: str, token: str, api_base: str = "https://api.github.com"):
        self._repo = repo
        self._token = token
        self._api = api_base.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "AVGAS-Map/0.1",
        }

    def list_releases(self) -> list[Release]:
        import requests

        out: list[Release] = []
        url = f"{self._api}/repos/{self._repo}/releases?per_page=100"
        resp = requests.get(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        for rel in resp.json():
            tag = rel.get("tag_name", "")
            asset_url = ""
            for asset in rel.get("assets", []):
                if asset.get("name") == ASSET_NAME:
                    asset_url = asset.get("browser_download_url", "")
                    break
            out.append(Release(tag=tag, asset_url=asset_url))
        return out

    def upsert_release_asset(self, tag: str, asset_name: str, data: bytes) -> Release:
        import requests

        headers = self._headers()
        repo_url = f"{self._api}/repos/{self._repo}"

        # Find or create the release for this tag.
        r = requests.get(f"{repo_url}/releases/tags/{tag}", headers=headers, timeout=60)
        if r.status_code == 404:
            r = requests.post(
                f"{repo_url}/releases",
                headers=headers,
                json={"tag_name": tag, "name": tag},
                timeout=60,
            )
        r.raise_for_status()
        rel = r.json()
        release_id = rel["id"]

        # Delete an existing same-named asset (replace semantics).
        for asset in rel.get("assets", []):
            if asset.get("name") == asset_name:
                requests.delete(
                    f"{repo_url}/releases/assets/{asset['id']}", headers=headers, timeout=60
                )

        # Upload the new asset.
        upload_base = rel["upload_url"].split("{", 1)[0]
        up_headers = dict(headers)
        up_headers["Content-Type"] = "application/geo+json"
        up = requests.post(
            f"{upload_base}?name={asset_name}",
            headers=up_headers,
            data=data,
            timeout=120,
        )
        up.raise_for_status()
        return Release(tag=tag, asset_url=up.json().get("browser_download_url", ""))

    def download_asset(self, tag: str) -> bytes | None:
        """Download the dataset.geojson bytes for a tag, server-side (no CORS).

        Uses the GitHub API asset endpoint with Accept: octet-stream, which
        redirects to storage; `requests` follows it. Returns None if the release
        or asset is missing.
        """
        import requests

        repo_url = f"{self._api}/repos/{self._repo}"
        r = requests.get(f"{repo_url}/releases/tags/{tag}", headers=self._headers(), timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        for asset in r.json().get("assets", []):
            if asset.get("name") == ASSET_NAME:
                dl_headers = dict(self._headers())
                dl_headers["Accept"] = "application/octet-stream"
                a = requests.get(
                    f"{repo_url}/releases/assets/{asset['id']}",
                    headers=dl_headers, timeout=120, allow_redirects=True,
                )
                a.raise_for_status()
                return a.content
        return None


def build_manifest(releases: list[Release]) -> dict:
    """Build index.json from all AIRAC releases (with an asset).

    `latest` = newest published cycle by effective date (ADR-0001; valid because
    no future cycle is pre-published). Cycles are sorted newest-first and each
    echoes effective_date + schema_version.
    """
    from avgasmap import schema

    cycles = []
    for rel in releases:
        cid = cycle_from_tag(rel.tag)
        if not cid or not rel.asset_url:
            continue
        cycles.append(
            {
                "cycle": cid,
                "effective_date": airac.effective_date(cid).isoformat(),
                "schema_version": schema.SCHEMA_VERSION,
                # Relative, same-origin path to the dataset materialized into the
                # site at deploy (Release URLs are not CORS-fetchable in-browser).
                "url": dataset_filename(cid),
            }
        )
    # Sort newest effective date first.
    cycles.sort(key=lambda c: c["effective_date"], reverse=True)
    latest = cycles[0]["cycle"] if cycles else None
    return {"latest": latest, "cycles": cycles}


@dataclass
class PublishResult:
    published_tag: str
    manifest: dict
    dataset_bytes: bytes           # the just-published dataset (avoid re-download)
    retained_tags: list[str]       # all airac tags in the manifest (for materializing)


def publish_cycle(
    cycle_id: str,
    dataset: dict,
    gh: GitHubReleases,
) -> PublishResult:
    """Publish `dataset` as the asset for `cycle_id`, then regenerate the manifest.

    Returns the published tag, the fresh manifest (relative same-origin URLs), the
    published dataset bytes (so the caller writes the site copy without a
    re-download), and the retained cycle tags (so the caller can materialize all
    cycles into the site). Any exception from `gh` propagates so the caller aborts
    without touching the prior published state (R7.5).
    """
    tag = tag_for_cycle(cycle_id)
    data = json.dumps(dataset, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    published = gh.upsert_release_asset(tag, ASSET_NAME, data)

    # Rebuild the manifest from the full set of releases. Merge in the release we
    # just published from the upsert's own return value: a `list_releases()`
    # immediately after an upload can lag (GitHub read-after-write consistency),
    # sometimes returning the release with an empty asset list — which would drop
    # the just-published cycle and yield an empty manifest. Trust our own upload.
    releases = list(gh.list_releases())
    if published.asset_url:
        releases = [r for r in releases if r.tag != published.tag] + [published]
    manifest = build_manifest(releases)
    retained = [tag_for_cycle(c["cycle"]) for c in manifest["cycles"]]
    return PublishResult(
        published_tag=tag, manifest=manifest, dataset_bytes=data, retained_tags=retained
    )
