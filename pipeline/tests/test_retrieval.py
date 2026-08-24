"""Tests for shared autorouter WebDAV retrieval (mock client, no network)."""

from __future__ import annotations

import os

import pytest

from avgasmap import retrieval
from avgasmap.retrieval import MissingCredentialsError, RetrievalResult, retrieve_france


class MockWebDav:
    """In-memory WebDAV: a tree of folders/files and per-path download bytes."""

    def __init__(self, listings: dict[str, list[str]], files: dict[str, bytes],
                 fail_first: dict[str, int] | None = None):
        self._listings = listings
        self._files = files
        self._fail_first = dict(fail_first or {})
        self.download_calls: list[str] = []

    def list(self, remote_path: str) -> list[str]:
        if remote_path not in self._listings:
            raise FileNotFoundError(remote_path)
        return self._listings[remote_path]

    def download_to_bytes(self, remote_path: str) -> bytes:
        self.download_calls.append(remote_path)
        # Simulate transient failures for retry testing.
        if self._fail_first.get(remote_path, 0) > 0:
            self._fail_first[remote_path] -= 1
            raise ConnectionError("transient")
        return self._files[remote_path]


def _france_fixture() -> MockWebDav:
    listings = {
        "France": [
            "LFAV - Valenciennes Denain/",
            "LFOH - Le Havre/",
            "LF12 - ULM strip/",      # LF## -> skipped
            "HLLT - Tripoli/",         # non-French -> skipped
            ".hidden/",                # skipped
        ],
        "France/LFAV - Valenciennes Denain/VFR": ["AD 2 LFAV VAC.pdf", "other.pdf"],
        "France/LFOH - Le Havre/VFR": ["AD 2 LFOH VAC.pdf"],
    }
    files = {
        "France/LFAV - Valenciennes Denain/VFR/AD 2 LFAV VAC.pdf": b"%PDF-AV",
        "France/LFOH - Le Havre/VFR/AD 2 LFOH VAC.pdf": b"%PDF-OH",
    }
    return MockWebDav(listings, files)


def test_lists_only_french_lf_aerodromes():
    client = _france_fixture()
    folders = retrieval.list_france_aerodromes(client)
    assert folders == ["LFAV - Valenciennes Denain", "LFOH - Le Havre"]


def test_finds_vac_pdf_prefers_vac_named():
    client = _france_fixture()
    p = retrieval.find_vac_pdf(client, "LFAV - Valenciennes Denain")
    assert p.endswith("AD 2 LFAV VAC.pdf")


def test_retrieve_downloads_to_icao_named_files(tmp_path):
    client = _france_fixture()
    results = retrieve_france(str(tmp_path), client=client, sleep=lambda s: None)
    by_icao = {r.icao: r for r in results}
    assert by_icao["LFAV"].outcome == "downloaded"
    assert by_icao["LFOH"].outcome == "downloaded"
    assert os.path.isfile(tmp_path / "LFAV.pdf")
    assert (tmp_path / "LFAV.pdf").read_bytes() == b"%PDF-AV"


def test_no_pdf_is_recorded_not_fatal(tmp_path):
    client = _france_fixture()
    # Aerodrome folder with an empty VFR listing.
    client._listings["France"].append("LFZZ - No Charts/")
    client._listings["France/LFZZ - No Charts/VFR"] = []
    results = retrieve_france(str(tmp_path), client=client, sleep=lambda s: None)
    by_icao = {r.icao: r for r in results}
    assert by_icao["LFZZ"].outcome == "no-pdf"
    assert not (tmp_path / "LFZZ.pdf").exists()


def test_retry_then_success(tmp_path):
    client = _france_fixture()
    target = "France/LFAV - Valenciennes Denain/VFR/AD 2 LFAV VAC.pdf"
    client._fail_first[target] = 2  # fail twice, succeed on 3rd
    results = retrieve_france(
        str(tmp_path), client=client, retries=3, backoff=0.0, sleep=lambda s: None
    )
    by_icao = {r.icao: r for r in results}
    assert by_icao["LFAV"].outcome == "downloaded"
    assert client.download_calls.count(target) == 3


def test_retry_exhausted_records_error(tmp_path):
    client = _france_fixture()
    target = "France/LFOH - Le Havre/VFR/AD 2 LFOH VAC.pdf"
    client._fail_first[target] = 99  # always fail
    results = retrieve_france(
        str(tmp_path), client=client, retries=3, backoff=0.0, sleep=lambda s: None
    )
    by_icao = {r.icao: r for r in results}
    assert by_icao["LFOH"].outcome.startswith("error:")
    assert not (tmp_path / "LFOH.pdf").exists()  # partial cleaned up


def test_missing_credentials_errors_without_client(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOROUTER_USER", raising=False)
    monkeypatch.delenv("AUTOROUTER_PASS", raising=False)
    with pytest.raises(MissingCredentialsError):
        retrieve_france(str(tmp_path), client=None)


def test_keyboard_interrupt_propagates_and_does_not_hang(tmp_path):
    # A Ctrl-C during a download must abort the whole fetch promptly, not get
    # swallowed into an "error:" result nor block on the submitted queue.
    class _InterruptingClient(MockWebDav):
        def download_to_bytes(self, remote_path: str) -> bytes:
            raise KeyboardInterrupt

    fx = _france_fixture()
    client = _InterruptingClient(fx._listings, fx._files)
    with pytest.raises(KeyboardInterrupt):
        retrieve_france(str(tmp_path), client=client, sleep=lambda s: None)
