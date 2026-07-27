"""The reconciliation report and the completeness scorecard, driven end to end.

The router under test is deliberately NOT mounted on `api.main.app` — it is
wired up at integration — so every case here builds a throwaway `FastAPI()`,
includes the router on it, and drives it with `TestClient`. That proves the
routes answer, rather than proving that a function returns a dictionary.

Two properties get a second, independent derivation rather than an assertion
that the code agrees with itself:

* the delta is re-subtracted here with `Decimal`, from the two figures the route
  sent, and
* `open_gap_positions` is checked against `packet_gap_positions`, which the
  contract computes by its own route through `PacketTotals`.

Both exist because a count that is only ever compared to itself is a count that
can be wrong in exactly one consistent way.
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import ledger, reconciliation
from api.config import ledger_schema
from packet.export import MANIFEST_NAME
from tests.schema_helpers import DSN

ROOT = Path(__file__).resolve().parents[1]

#: The finding the client's stated core pain reduces to: one column, two
#: numbers, 2,000,000 apart, in the fund's own books.
SHARPEST = "Fund II Holdings by Quarter · 23Q4"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(reconciliation.router)
    return TestClient(app)


def _report() -> dict[str, Any]:
    response = _client().get("/reconciliation")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _bucket(report: dict[str, Any], scope: str) -> dict[str, Any]:
    found = [b for b in report["scopes"] if b["scope"] == scope]
    assert len(found) == 1, f"expected exactly one {scope} bucket, got {len(found)}"
    return dict(found[0])


def _snapshot() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        (ROOT / "ingest/trackers/real_findings.json").read_text(encoding="utf-8")
    )
    return raw


# ── The reconciliation report ────────────────────────────────────────────


def test_the_report_serves_the_committed_snapshot_rather_than_the_workbooks() -> None:
    """`real_findings.json` ships in the repository, so this route answers the
    same way in CI, on a laptop with no case-study material, and in production.
    A report that could only be produced where the private workbooks live is a
    report nobody can see."""
    report = _report()
    assert report["source"] == "tracker_snapshot"
    assert report["snapshot"] == "ingest/trackers/real_findings.json"
    assert (report["positions"], report["tranches"], report["fund_periods"]) == (14, 18, 12)
    assert report["finding_count"] == 32


def test_findings_arrive_partitioned_by_scope_and_never_as_one_list() -> None:
    """SPEC §2 · six measurement dates are in the auditor's packet and six
    fund-periods are ingested for lineage only. A finding about 6/30/2025 must
    not read as a finding about 12/31/2025.

    The partition is in the SHAPE of the response, not in a field a caller is
    trusted to filter on: there is no top-level `findings` key to render by
    accident.
    """
    report = _report()
    assert "findings" not in report
    assert [b["scope"] for b in report["scopes"]] == ["packet", "lineage_only", "unscoped"]
    counts = {b["scope"]: b["finding_count"] for b in report["scopes"]}
    assert counts == {"packet": 17, "lineage_only": 14, "unscoped": 1}
    for bucket in report["scopes"]:
        assert {f["scope"] for f in bucket["findings"]} == {bucket["scope"]}
        assert len(bucket["findings"]) == bucket["finding_count"]


def test_the_route_and_the_snapshot_agree_about_the_scope_split() -> None:
    """The snapshot states its own scope counts. This route recounts them from
    the findings themselves, and the two must not drift: a header that disagrees
    with the rows beneath it is the exact defect the reconciler exists to find."""
    snapshot = _snapshot()
    report = _report()
    assert _bucket(report, "packet")["finding_count"] == snapshot["packet_scope_findings"]
    assert _bucket(report, "lineage_only")["finding_count"] == snapshot["lineage_only_findings"]
    #: The remainder is real and is neither. Filing the fund-wide cost-basis
    #: column under a measurement date would assert something the workbook does
    #: not say; dropping it would lose a disagreement.
    assert (
        snapshot["finding_count"]
        - snapshot["packet_scope_findings"]
        - snapshot["lineage_only_findings"]
        == _bucket(report, "unscoped")["finding_count"]
    )


def test_the_packet_bucket_holds_no_lineage_only_subject() -> None:
    report = _report()
    packet_subjects = {f["subject"] for f in _bucket(report, "packet")["findings"]}
    lineage_subjects = {f["subject"] for f in _bucket(report, "lineage_only")["findings"]}
    assert packet_subjects & lineage_subjects == set()
    assert SHARPEST in packet_subjects


def test_the_sharpest_finding_keeps_stated_and_computed_apart_and_states_the_delta() -> None:
    """One column of the fund's own workbook: four positions summing to
    6,000,000 under a total row that states 4,000,000.

    Both figures survive to the wire, unmerged, with the difference between them
    subtracted here rather than in the browser — SPEC §5.3 — and named for the
    direction it runs in, because a delta whose sign nobody wrote down is a
    number that can be read backwards.
    """
    finding = next(f for f in _bucket(_report(), "packet")["findings"] if f["subject"] == SHARPEST)
    assert finding["kind"] == "stated_total_disagrees_with_cells"
    assert finding["scope"] == "packet"
    assert finding["stated"] == "4000000"
    assert finding["computed"] == "6000000"
    assert finding["delta_computed_minus_stated"] == "2000000"
    assert finding["detail"] == (
        "the column sums to 6,000,000 across 4 positions "
        "(Because Market, Moonfare, Sway, Jackpocket) but the sheet states 4,000,000"
    )


def test_every_two_figure_finding_carries_a_delta_the_browser_never_subtracts() -> None:
    """Re-derived here from the two figures the route sent, with `Decimal`. If
    the route ever computed the delta in floats, or the wrong way round, this
    fails — which an assertion that the field is merely present would not."""
    seen = 0
    for bucket in _report()["scopes"]:
        for finding in bucket["findings"]:
            stated, computed = finding["stated"], finding["computed"]
            delta = finding["delta_computed_minus_stated"]
            if stated is None or computed is None:
                assert delta is None
                continue
            seen += 1
            assert Decimal(delta) == Decimal(computed) - Decimal(stated)
    assert seen == 32, "every finding in this snapshot states both figures"


def test_figures_cross_the_wire_as_strings_not_floats() -> None:
    """INV-11 · a float amount is wrong before anyone reads it, and JSON has no
    decimal type. Exponent form is refused too: `2E+6` is the same number and a
    string an auditor cannot match against a workbook cell."""
    raw = _client().get("/reconciliation").content.decode()
    assert "e+" not in raw.lower()
    for bucket in _report()["scopes"]:
        for finding in bucket["findings"]:
            for key in ("stated", "computed", "delta_computed_minus_stated"):
                assert isinstance(finding[key], str)


def test_an_unknown_scope_fails_rather_than_landing_in_a_default_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`scope` is a closed vocabulary of two plus a named absence. A third value
    appearing in the snapshot is a reconciler change nobody reviewed, and
    silently filing it under `unscoped` would hide it."""
    doc = _snapshot()
    doc["findings"][0]["scope"] = "somewhere_else"
    bad = tmp_path / "real_findings.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(reconciliation, "SNAPSHOT", bad)
    assert _client().get("/reconciliation").status_code == 500


def test_a_missing_snapshot_fails_the_route_and_not_the_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read per request, not at import: a malformed snapshot must take down the
    one route that needs it, not the whole API at startup."""
    monkeypatch.setattr(reconciliation, "SNAPSHOT", tmp_path / "absent.json")
    assert _client().get("/reconciliation").status_code == 500


# ── The completeness scorecard ───────────────────────────────────────────


def test_the_scorecard_says_when_it_is_answering_from_the_demo_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no DSN the route serves the one-holding Dream fixture, exactly as
    the packet routes do — and says so. A scorecard that has silently fallen
    back to a stub is a partner reading one holding as a fund."""
    monkeypatch.setattr(reconciliation, "dsn", lambda key="DATABASE_URL": None)
    body = _client().get("/scorecard").json()
    assert body["source"] == "fixture"
    assert len(body["periods"]) == 1
    line = body["periods"][0]
    assert line["counts"] == {
        "positions": 1,
        "fully_supported": 0,
        "open_gap_positions": 1,
        "pro_forma_positions": 1,
        "held_at_date": 1,
        "not_held_at_date": 0,
    }
    assert line["totals"]["kind"] == "held_at_date_reported"


def test_a_fund_period_with_no_packet_reports_no_counts_rather_than_zeros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Zero of zero positions supported" reads as a finding about the fund.
    "No packet could be assembled" is a finding about the ledger. They must not
    render the same way, so the counts are absent rather than zero."""
    monkeypatch.setattr(ledger, "packet_periods", lambda conn: [("fund_x", "p1", "P1")])
    monkeypatch.setattr(ledger, "packet", lambda conn, fund, period: None)
    monkeypatch.setattr(reconciliation, "_connect", lambda: _FakeConn())
    line = _client().get("/scorecard").json()["periods"][0]
    assert line["counts"] is None
    assert line["totals"] is None
    assert line["absent_reason"]
    assert (line["fund_id"], line["period_id"], line["label"]) == ("fund_x", "p1", "P1")


class _FakeConn:
    """Stands in for a ledger connection the monkeypatched reads never touch."""

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_scorecard_reports_one_line_for_every_packet_fund_period() -> None:
    """Both funds, three measurement dates each, in the order the ledger lists
    them. The six are read from the ledger rather than written down here — a
    hard-coded list is right until the fund adds a date."""
    body = _client().get("/scorecard").json()
    assert body["source"] == "ledger"
    assert [(p["fund_id"], p["period_id"]) for p in body["periods"]] == [
        ("fund_i", "fund_i_fy2023"),
        ("fund_i", "fund_i_fy2024"),
        ("fund_i", "fund_i_fy2025"),
        ("fund_ii", "fund_ii_23q4"),
        ("fund_ii", "fund_ii_24q4"),
        ("fund_ii", "fund_ii_25q4"),
    ]
    assert all(p["audit_scope"] == "packet" for p in body["periods"])


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_fund_ii_25q4_is_nothing_supported_out_of_eight_with_three_pro_forma() -> None:
    """The line a partner reads first, against the real ledger. `fully_supported`
    and `positions` are two integers so that "0 of 8" is assembled from supplied
    numbers rather than divided in the browser (SPEC §5.3)."""
    body = _client().get("/scorecard").json()
    line = next(p for p in body["periods"] if p["period_id"] == "fund_ii_25q4")
    assert line["counts"] == {
        "positions": 8,
        "fully_supported": 0,
        "open_gap_positions": 8,
        "pro_forma_positions": 3,
        "held_at_date": 8,
        "not_held_at_date": 0,
    }
    assert line["totals"]["amount"] == {"amount": "25648515.0000", "currency": "USD"}
    assert line["totals"]["contains_unsupported_inputs"] is True


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_24q4_keeps_a_realised_position_in_the_packet_and_out_of_the_total() -> None:
    """INV-7 · Jackpocket was sold in May 2024, so it is one of the period's
    eight positions and is not an input to the held-at-date total. A scorecard
    that reported only held positions would drop the row the audit letter asks
    for by name.

    In the packet and NOT a gap. `packet_gap_positions` read 6 here against the
    oracle's 5, because `HoldingRow.unsupported_reasons` demanded R1 and R2 on
    every row — including one whose position did not exist at the measurement
    date, where `derived.json` states both as `not_applicable` and the row as
    `fully_supported`. The letter asks for existence and cost for investments
    HELD during the period (¶1) and for realisation support separately (¶4);
    counting this row as an open gap sent the auditor after paperwork that
    cannot exist.

    The counts are read from the oracle rather than typed, so this cannot drift
    back to agreeing with the implementation instead of with the answer key.
    """
    totals = next(
        t
        for t in json.loads((ROOT / "evals/oracle/derived.json").read_text())["totals"]
        if t["fund"] == "fund_ii" and t["date"] == "2024-12-31"
    )
    body = _client().get("/scorecard").json()
    line = next(p for p in body["periods"] if p["period_id"] == "fund_ii_24q4")
    assert line["counts"]["positions"] == 8
    assert line["counts"]["held_at_date"] == totals["positions_held"] == 7
    assert line["counts"]["not_held_at_date"] == 1
    assert line["totals"]["unsupported_positions"] == totals["unsupported_row_count"] == 5
    assert line["totals"]["packet_gap_positions"] == totals["packet_gap_row_count"] == 5
    assert line["totals"]["unheld_gap_positions"] == 0


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_two_gap_counts_are_derived_twice_and_agree() -> None:
    """`open_gap_positions` is counted by this route; `packet_gap_positions` is
    counted by `PacketTotals`. They are the same quantity by two routes, and the
    scorecard needs its own because a packet with no marks has counts and no
    totals. Checked against each other so the second cannot drift in silence."""
    for line in _client().get("/scorecard").json()["periods"]:
        counts, totals = line["counts"], line["totals"]
        assert counts["positions"] == counts["held_at_date"] + counts["not_held_at_date"]
        assert counts["fully_supported"] + counts["open_gap_positions"] == counts["positions"]
        assert counts["open_gap_positions"] == totals["packet_gap_positions"]


# ── The packet as a download ─────────────────────────────────────────────
# SPEC §1 calls the assembled package the deliverable. It was written to the API
# host's disk, which on Render is ephemeral and unreachable, so the deliverable
# could not be obtained by the person it is for. `export.zip` streams it.
#
# The guard below is deliberately not "the response was 200". A 200 carrying an
# empty archive is the failure worth catching, because it is what a download
# button would render as success.

#: A fund-period that exists in the demo ledger and is in the auditor's packet.
DOWNLOADABLE = ("fund_ii", "fund_ii_24q4")


def _archive_matches_manifest(payload: bytes, expected_files: list[str]) -> bool:
    """The guard, as one predicate, so a mutation can be shown to turn it red.

    Three conditions, and an empty archive fails all three: the bytes open as a
    zip, `MANIFEST.json` is present, and the members other than the manifest are
    exactly the files the JSON route reported. Set equality rather than a count,
    because two wrong files and two right ones is the same number.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                return False
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return MANIFEST_NAME in names and names - {MANIFEST_NAME} == set(expected_files)


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_download_carries_every_file_the_json_route_manifested() -> None:
    """The deliverable arrives whole. The file list is taken from the JSON route
    rather than written down here, so the two routes cannot drift: if the
    exporter starts emitting a table, both move together or this fails."""
    fund_id, period_id = DOWNLOADABLE
    listing = _client().get(f"/funds/{fund_id}/periods/{period_id}/export").json()
    response = _client().get(f"/funds/{fund_id}/periods/{period_id}/export.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert _archive_matches_manifest(response.content, listing["files"])
    #: `file_count` counts the manifest's entries; the archive holds those plus
    #: `MANIFEST.json`, which is not one of its own entries.
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == listing["file_count"] + 1
    assert response.headers["x-file-count"] == str(listing["file_count"])
    assert int(listing["file_count"]) > 0


def test_an_empty_archive_fails_the_guard() -> None:
    """The mutation that proves the guard can go red.

    A 200 with an empty zip is the shape a broken download takes — the button
    works, the file opens, and there is nothing in it. If this ever passes, the
    test above has stopped checking anything."""
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w"):
        pass
    assert not _archive_matches_manifest(empty.getvalue(), ["README.md"])
    assert not _archive_matches_manifest(b"", ["README.md"])
    #: And a manifest with nothing beside it fails too, which is the subtler
    #: version: an archive that opens and looks structured but delivers no packet.
    manifest_only = io.BytesIO()
    with zipfile.ZipFile(manifest_only, "w") as archive:
        archive.writestr(MANIFEST_NAME, "{}")
    assert not _archive_matches_manifest(manifest_only.getvalue(), ["README.md"])


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_download_refuses_exactly_as_the_json_route_does() -> None:
    """Both routes answer a fund-period with no packet with the same 409 and the
    same sentence. The refusal names what is wrong, and it must not be reduced to
    a download that simply does not arrive."""
    listing = _client().get("/funds/fund_ii/periods/nonexistent/export")
    download = _client().get("/funds/fund_ii/periods/nonexistent/export.zip")
    assert listing.status_code == download.status_code == 409
    assert listing.json()["detail"] == download.json()["detail"]
    assert "nonexistent" in download.json()["detail"]


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_a_download_registers_nothing_and_leaves_nothing_behind() -> None:
    """SPEC §3.1 is read-only about the LEDGER, and this is the evidence rather
    than the assertion: `packet_manifest_entry` has the same row count after the
    download as before, and no staging directory survives the request."""
    fund_id, period_id = DOWNLOADABLE
    assert DSN is not None
    with psycopg.connect(DSN, prepare_threshold=None) as conn:
        conn.execute(f"set search_path to {ledger_schema()}")
        before = conn.execute("select count(*) from packet_manifest_entry").fetchone()

    leftovers = set(Path(tempfile.gettempdir()).glob("packet-download-*"))
    response = _client().get(f"/funds/{fund_id}/periods/{period_id}/export.zip")
    assert response.status_code == 200
    assert set(Path(tempfile.gettempdir()).glob("packet-download-*")) == leftovers

    with psycopg.connect(DSN, prepare_threshold=None) as conn:
        conn.execute(f"set search_path to {ledger_schema()}")
        after = conn.execute("select count(*) from packet_manifest_entry").fetchone()
    assert before == after
    #: Stated on the response itself, because the browser is where the wrong
    #: conclusion gets drawn. Generating a packet is not registering one.
    assert response.headers["x-recorded-in-ledger"] == "false"


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_download_does_not_publish_into_the_shared_packet_directory() -> None:
    """The JSON route publishes to `PACKET_OUT`; this one builds in a temporary
    directory and keeps nothing. A download that quietly overwrote the published
    packet would make two callers race over one directory."""
    fund_id, period_id = DOWNLOADABLE
    published = reconciliation.PACKET_OUT / period_id
    before = sorted(p.name for p in published.iterdir()) if published.is_dir() else None
    assert _client().get(f"/funds/{fund_id}/periods/{period_id}/export.zip").status_code == 200
    after = sorted(p.name for p in published.iterdir()) if published.is_dir() else None
    assert before == after


def test_the_download_says_there_is_no_ledger_rather_than_shipping_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no DSN the scorecard falls back to the Dream fixture and says so. A
    packet must not: a one-holding stub zipped under the fund's name is a
    deliverable that is wrong rather than absent."""
    monkeypatch.setattr(reconciliation, "dsn", lambda key="DATABASE_URL": None)
    response = _client().get("/funds/fund_ii/periods/fund_ii_24q4/export.zip")
    assert response.status_code == 503
    assert "no database is configured" in response.json()["detail"]


def test_the_download_filename_cannot_carry_a_header_break() -> None:
    """The ids reach `Content-Disposition` from the URL. A newline there is a
    split response, not an odd filename, so everything outside the safe set is
    replaced before it gets near a header."""
    assert reconciliation._download_name("fund_ii", "24q4") == "fund_ii-24q4.zip"
    hostile = reconciliation._download_name("a\r\nX-Evil: 1", "../../etc/passwd")
    assert "\r" not in hostile and "\n" not in hostile and "/" not in hostile
    assert hostile.endswith(".zip")
