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

import hashlib
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
from api.reconciliation import DOWNLOAD_HEADERS
from packet.company import COMPANY_SCOPE_NOTE, holdings_in, slice_for
from packet.export import MANIFEST_NAME, Written
from packet.layout import Layout
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

    In the packet AND a gap, and this test used to assert the opposite.

    It read: "counting this row as an open gap sent the auditor after paperwork
    that cannot exist." The paperwork can exist. Jackpocket's 2021 purchase
    agreement is recorded as a declared gap — `not_located`, which is the fund
    saying it has not found it, not that there is nothing to find.

    And the sentence above it already had the answer: the letter asks about
    investments "HELD DURING the period". Jackpocket was held for five months of
    2024, and the FY2024 statements carry the realised gain on its sale. A gain
    is proceeds minus cost. R4 evidences the proceeds; ¶1 is where the cost
    lives; and answering `not_applicable` handed an auditor one half of a figure
    they have to sign and called the other half none of their business.

    So the row is `missing` at 24Q4 rather than `fully_supported`, and the
    period's gap count is 6 rather than 5. The count that changed is the count
    that was wrong.

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
    assert line["totals"]["packet_gap_positions"] == totals["packet_gap_row_count"] == 6
    # ONE, and it is Jackpocket. `unheld_gap_positions` is the difference between
    # every unsupported row and the held ones, and `PacketTotals` has carried
    # that field since it was written — it had simply never had a member,
    # because a position not held at the date could not have a gap. The "held
    # during" reading is what puts one in it: a position sold in May, with a
    # realised gain in the year's statements and no located acquisition
    # document. The count existing and being zero forever was the symptom.
    assert line["totals"]["unheld_gap_positions"] == 1


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


# ── One company's evidence as a download ─────────────────────────────────
# The audit letter's closing request, made obtainable: "the support organized by
# portfolio company", one company at a time.
#
# The archive is the whole packet minus the OTHER companies' source documents,
# and the cases below are arranged around the two ways that can go wrong. It can
# carry too much — another company's documents, which is the one thing
# "organized by portfolio company" must not do. Or it can carry too little — a
# gap report trimmed to one company, which reports fewer findings than the
# packet found while looking complete.

#: Three positions with different shapes, named rather than discovered, so a
#: case that stops covering one of them fails instead of quietly narrowing.
#: Fluidstack holds two documents, Anthropic one, Because Market none.
WITH_DOCUMENTS = "fund_ii_fluidstack"
ANOTHER_COMPANY = "fund_ii_anthropic"
WITHOUT_DOCUMENTS = "fund_ii_because_market"


def _company_url(holding_id: str) -> str:
    fund_id, period_id = DOWNLOADABLE
    return f"/funds/{fund_id}/periods/{period_id}/companies/{holding_id}/export.zip"


def _members(payload: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        return set(archive.namelist())


def _member_text(payload: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return archive.read(name).decode("utf-8")


def _folder(members: set[str], company: str) -> set[str]:
    return {name for name in members if name.startswith(f"companies/{company}/")}


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_company_archive_carries_that_company_and_not_another() -> None:
    """The whole point of the route, as the only assertion that can catch it
    getting the prefix wrong: Fluidstack's two documents arrive, and no file
    under any other company folder does. Checked in both directions — an archive
    holding nothing at all would satisfy "no other company's documents"."""
    response = _client().get(_company_url(WITH_DOCUMENTS))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    members = _members(response.content)

    mine = _folder(members, "Fluidstack")
    assert mine, "the company's own folder is empty — the archive carries no evidence"
    #: Each document is exported twice: the bytes the fund holds and the
    #: canonical text every citation offset indexes into. An archive with the
    #: PDFs and none of the text files leaves every offset pointing at nothing.
    assert {name for name in mine if name.endswith(".canonical.txt")}
    assert {name for name in mine if not name.endswith(".canonical.txt")}

    others = {name for name in members if name.startswith("companies/")} - mine
    assert others == set(), f"another company's evidence rode along: {sorted(others)}"


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_two_company_archives_from_one_packet_do_not_share_a_document() -> None:
    """Two positions, two archives, no overlapping company folder.

    The case above compares one archive against a prefix. This compares two
    archives against each other, which is the form that survives a filter that
    is wrong for every company in the same way.
    """
    first = _client().get(_company_url(WITH_DOCUMENTS))
    second = _client().get(_company_url(ANOTHER_COMPANY))
    assert first.status_code == second.status_code == 200
    mine = {n for n in _members(first.content) if n.startswith("companies/")}
    theirs = {n for n in _members(second.content) if n.startswith("companies/")}
    assert mine and theirs
    assert mine & theirs == set(), f"both archives carry {sorted(mine & theirs)}"


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_company_archive_members_are_what_the_manifest_and_the_note_account_for() -> None:
    """Every member is accounted for, and every manifest entry is either present
    or listed as withheld.

    This is the property that makes the archive readable against the packet it
    was cut from. `MANIFEST.json` is the full packet's, so its entry list is
    LONGER than the archive — an auditor comparing the two would otherwise find
    twenty missing files and no statement about why.
    """
    listing = _client().get(f"/funds/{DOWNLOADABLE[0]}/periods/{DOWNLOADABLE[1]}/export").json()
    response = _client().get(_company_url(WITH_DOCUMENTS))
    assert response.status_code == 200
    members = _members(response.content)

    entries = set(listing["files"])
    extras = {MANIFEST_NAME, COMPANY_SCOPE_NOTE}
    assert extras <= members
    present = members - extras
    assert present < entries, "the company archive is not a subset of the packet"

    note = _member_text(response.content, COMPANY_SCOPE_NOTE)
    withheld = {line.strip() for line in note.splitlines() if line.startswith("  companies/")}
    assert withheld == entries - present, "the note does not account for what is missing"
    assert response.headers["x-file-count"] == str(len(present))
    assert response.headers["x-withheld-file-count"] == str(len(withheld))
    assert int(response.headers["x-withheld-file-count"]) > 0


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_company_archive_carries_the_gap_report_whole() -> None:
    """The CSVs are the packet's, byte for byte, and are not trimmed to the
    company the archive is named for.

    This is the design decision, asserted rather than described. A gap report cut
    to one company reports fewer findings than the packet found; a holdings table
    cut to one company's rows sits under a footer stating the fund's total. Both
    are a deliverable that says less than the system knows while looking complete
    — which is the defect this project exists to be unable to ship.

    Byte equality against the full download, so "whole" cannot decay into
    "mostly". The tables only — `MANIFEST.json` and `README.md` carry the
    generation time, so two runs a minute apart differ there and that is not
    drift. SPEC §12 calls reproducibility logical rather than byte-identical,
    and the check below is what makes the tables' identity checkable anyway.
    """
    whole = _client().get(f"/funds/{DOWNLOADABLE[0]}/periods/{DOWNLOADABLE[1]}/export.zip")
    company = _client().get(_company_url(WITH_DOCUMENTS))
    assert whole.status_code == company.status_code == 200
    for name in ("gap_report.csv", "evidence_index.csv", "holdings.csv"):
        assert _member_text(company.content, name) == _member_text(whole.content, name), name
    #: And the content is what makes it worth carrying: the gap report names a
    #: company this archive is not about, which a trimmed copy could not do.
    assert "Because Market" in _member_text(company.content, "gap_report.csv")


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_every_file_in_a_company_archive_hashes_to_what_its_manifest_records() -> None:
    """The archive is checkable against the manifest travelling with it.

    This is what "carried whole and unmodified" means as something that can go
    red. Trimming a CSV to one company would leave a file whose bytes no
    manifest attests to — a figure nobody can trace, arriving inside the packet
    whose entire purpose is that every figure can be — and this is the assertion
    that would catch it.
    """
    response = _client().get(_company_url(WITH_DOCUMENTS))
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME))
        recorded = {e["path"]: e["content_hash"] for e in manifest["entries"]}
        members = set(archive.namelist()) - {MANIFEST_NAME, COMPANY_SCOPE_NOTE}
        assert members, "no member to hash — this check would pass vacuously"
        for name in sorted(members):
            assert hashlib.sha256(archive.read(name)).hexdigest() == recorded[name], name


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_a_company_with_no_documents_downloads_a_stated_absence() -> None:
    """Because Market holds no source document, and that is a finding.

    Not a 404 and not an empty archive: the folder carries a note saying the
    document is not held, the gap report carries the same finding, and the scope
    note says it too. An absence that produced no file would be an absence the
    deliverable does not state — which is the failure the empty-folder note was
    written for in the first place.
    """
    response = _client().get(_company_url(WITHOUT_DOCUMENTS))
    assert response.status_code == 200
    members = _members(response.content)
    folder = _folder(members, "Because Market")
    assert folder == {"companies/Because Market/NO_SOURCE_DOCUMENTS.txt"}

    stated = _member_text(response.content, "companies/Because Market/NO_SOURCE_DOCUMENTS.txt")
    assert "No source document is held for Because Market" in stated
    assert "reported as a gap, not an omission" in stated
    assert "NO SOURCE DOCUMENT" in _member_text(response.content, COMPANY_SCOPE_NOTE)
    assert "no_source_documents" in _member_text(response.content, "gap_report.csv")


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_a_position_the_packet_does_not_hold_is_a_404_that_names_the_ones_it_does() -> None:
    """404, and the answer to the next question in the same sentence.

    An empty archive would render "this company has no evidence" and "you named
    a company that is not in this packet" identically, and the first of those is
    a finding about the fund.
    """
    response = _client().get(_company_url("fund_ii_not_a_position"))
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "fund_ii_not_a_position" in detail
    assert WITH_DOCUMENTS in detail and WITHOUT_DOCUMENTS in detail


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_company_download_refuses_exactly_as_the_packet_download_does() -> None:
    """A refusal is a finding and reaches the browser in the exporter's own
    words, whichever of the three export routes was asked. The per-company route
    filters a packet that was already validated whole, so a refusal naming
    another company's citation blocks this download too — and says which one,
    rather than failing as though this company were the problem.

    Compared against the JSON route rather than against the packet download. The
    two downloads share the code that builds the packet, so they would agree
    with each other while both being wrong; `GET .../export` raises its own 409
    from its own line, which is what makes this an independent comparison rather
    than two ends of the same wire.
    """
    listing = _client().get("/funds/fund_ii/periods/nonexistent/export")
    company = _client().get(
        f"/funds/fund_ii/periods/nonexistent/companies/{WITH_DOCUMENTS}/export.zip"
    )
    assert company.status_code == 409, "a refusal must not be reported as a fault"
    assert listing.status_code == 409
    assert listing.json()["detail"] == company.json()["detail"]
    assert "nonexistent" in company.json()["detail"]


def test_the_company_download_says_there_is_no_ledger_rather_than_shipping_the_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same 503 the packet download gives, for the same reason: a one-holding
    demo stub zipped under a portfolio company's name is a deliverable that is
    wrong rather than absent."""
    monkeypatch.setattr(reconciliation, "dsn", lambda key="DATABASE_URL": None)
    response = _client().get(_company_url(WITH_DOCUMENTS))
    assert response.status_code == 503
    assert "no database is configured" in response.json()["detail"]


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_a_company_download_registers_nothing_and_leaves_nothing_behind() -> None:
    """The read-only claim holds for the narrower route as well: no
    `packet_manifest_entry` row, no staging directory, and the response says so
    itself rather than leaving the browser to assume it."""
    assert DSN is not None
    with psycopg.connect(DSN, prepare_threshold=None) as conn:
        conn.execute(f"set search_path to {ledger_schema()}")
        before = conn.execute("select count(*) from packet_manifest_entry").fetchone()

    leftovers = set(Path(tempfile.gettempdir()).glob("packet-download-*"))
    response = _client().get(_company_url(WITH_DOCUMENTS))
    assert response.status_code == 200
    assert set(Path(tempfile.gettempdir()).glob("packet-download-*")) == leftovers

    with psycopg.connect(DSN, prepare_threshold=None) as conn:
        conn.execute(f"set search_path to {ledger_schema()}")
        after = conn.execute("select count(*) from packet_manifest_entry").fetchone()
    assert before == after
    assert response.headers["x-recorded-in-ledger"] == "false"


def _slice_over(company_dir: dict[str, str], paths: list[str]) -> Written:
    """A published packet, constructed rather than exported.

    The collision this pins cannot be produced from the corpus — no two of the
    fund's companies have names where one folder is a prefix of another — and a
    guard that can only be exercised by data nobody has is a guard that will be
    written wrong and stay green.
    """
    return Written(
        packet_id="pkx_test",
        root=Path("/nonexistent"),
        manifest={"entries": [{"path": p} for p in paths], "manifest_hash": "h"},
        fund_id="fund_ii",
        period_id="fund_ii_24q4",
        schema_version="0.1.0",
        policy_version="v1",
        layout=Layout(company_dir=company_dir),
    )


def test_one_company_folder_is_not_a_prefix_of_another() -> None:
    """`companies/Ada` must not collect `companies/Adafruit`'s documents.

    A prefix test without the separator attached is the single most likely way
    this filter is wrong, it is invisible on this corpus, and its consequence is
    one portfolio company's private documents inside another's archive.
    """
    written = _slice_over(
        {"ada": "companies/Ada", "adafruit": "companies/Adafruit"},
        ["companies/Ada/a.pdf", "companies/Adafruit/b.pdf", "gap_report.csv"],
    )
    chosen = slice_for(written, "ada")
    assert chosen is not None
    assert chosen.documents == ("companies/Ada/a.pdf",)
    assert chosen.present == ("companies/Ada/a.pdf", "gap_report.csv")
    assert chosen.withheld == ("companies/Adafruit/b.pdf",)
    assert chosen.label == "Ada"


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_both_downloads_describe_themselves_the_same_way() -> None:
    """Every fact `_download_facts` states reaches the wire, on both routes.

    The browser cannot look inside a zip it has just saved, so these headers are
    the whole of what a screen can report about it. Read off the function rather
    than typed out, so a header renamed in one place fails here instead of
    arriving as an absence the page renders as a blank.
    """
    stub = _slice_over({}, [])
    facts = {name.lower() for name in reconciliation._download_facts(stub, present=1, withheld=0)}
    assert facts, "no header to check — this would pass vacuously"
    whole = _client().get(f"/funds/{DOWNLOADABLE[0]}/periods/{DOWNLOADABLE[1]}/export.zip")
    company = _client().get(_company_url(WITH_DOCUMENTS))
    assert whole.status_code == company.status_code == 200
    assert facts <= set(whole.headers)
    assert facts <= set(company.headers)
    #: Stated on the whole packet too, reading zero. A count that appears only
    #: when it is non-zero is a count a caller learns to stop looking for.
    assert whole.headers["x-withheld-file-count"] == "0"
    assert whole.headers["x-file-count"] == str(len(_members(whole.content)) - 1)


def test_a_holding_the_layout_does_not_place_has_no_slice() -> None:
    """`None`, not an empty slice. The route turns it into a 404 naming the
    positions the packet does hold, and an empty slice would have turned it into
    a valid archive of nothing."""
    written = _slice_over({"ada": "companies/Ada"}, ["companies/Ada/a.pdf"])
    assert slice_for(written, "adafruit") is None
    assert holdings_in(written) == ("ada",)


# ── what a BROWSER can read, which is not what TestClient can ────────────


def test_every_header_the_download_sets_is_exposed_across_origins() -> None:
    """`TestClient` does not enforce CORS, so this is the one property none of
    the download tests above can see.

    A cross-origin response hands JavaScript seven safelisted headers —
    cache-control, content-language, content-length, content-type, expires,
    last-modified, pragma — and nothing else unless the server names it in
    `Access-Control-Expose-Headers`. `Content-Disposition` is not on that list,
    and neither is any `X-` header this route sets.

    Unexposed, the packet download saves under a fallback name and the facts
    panel beside it reads blank — in a browser, on the deployed site, while
    every assertion in this file passes. `api/main.py` carries the same lesson
    about `allow_methods`, where a GET-only list left the approve control dead
    in the browser and green in the suite.
    """
    from api.main import app

    # Read off the app's own middleware stack rather than off a literal, so a
    # list edited in `api/main.py` and not here cannot pass.
    declared = next(
        m.kwargs["expose_headers"]
        for m in app.user_middleware
        if "expose_headers" in getattr(m, "kwargs", {})
    )
    assert isinstance(declared, list)
    exposed = {str(h).strip().lower() for h in declared}
    for name in DOWNLOAD_HEADERS:
        assert name.lower() in exposed, (
            f"{name} is set by a download route and not exposed, so a browser on "
            "another origin reads null while this suite reads the value"
        )


def test_the_download_headers_named_for_cors_are_the_ones_actually_sent() -> None:
    """The other direction, and the one that makes the list above worth having.

    A name in `DOWNLOAD_HEADERS` that no response carries exposes nothing and
    reads as coverage; a header a response carries that the list omits is the
    defect this pair exists to prevent. Checked against a real response rather
    than against the dict literal that builds one.
    """
    response = _client().get("/funds/fund_ii/periods/fund_ii_25q4/export.zip")
    assert response.status_code == 200
    sent = {k.lower() for k in response.headers}
    named = {h.lower() for h in DOWNLOAD_HEADERS}
    assert named <= sent, f"named for CORS but never sent: {sorted(named - sent)}"

    # THE ACTUAL CORS RULE, not a proxy for it. The first version of this
    # assertion checked only `x-` headers, so deleting `Content-Disposition`
    # from the list passed both tests — and that is the header the saved file is
    # NAMED by. A guard with a hole exactly where the important case lives is
    # the shape this repository keeps finding.
    #
    # `Access-Control-Expose-Headers` is needed for everything a response sends
    # EXCEPT the seven the fetch spec safelists, so those seven are the
    # exemption and every other header must be named.
    SAFELISTED = {
        "cache-control",
        "content-language",
        "content-length",
        "content-type",
        "expires",
        "last-modified",
        "pragma",
    }
    unreadable = sent - SAFELISTED - named - {"date", "server"}
    assert not unreadable, (
        f"sent but not exposed, so a browser on another origin reads null: {sorted(unreadable)}"
    )
