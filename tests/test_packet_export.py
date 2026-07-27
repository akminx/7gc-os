"""Gate: the auditor packet, written to disk.

Two halves, for two different failure modes.

The **synthetic** half builds packets by hand, so the cases the corpus does not
currently contain can still be exercised: an approved-but-unsupported row, a
generation that fails part-way, a quoted passage beginning with `=`, a company
name carrying a path separator. Those are the shapes that would be found in
production if they were not found here.

The **corpus** half exports the real Fund II packets out of the live schema and
checks the figures against `evals/oracle/derived.json`, which is derived without
importing anything from the application. A packet that agrees only with the code
that produced it has not been checked.
"""

from __future__ import annotations

import csv
import json
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from api import ledger
from api.config import dsn, ledger_schema
from packages.contracts.citations import from_stored
from packages.contracts.enums import (
    AuditScope,
    DecisionStatus,
    DecisionType,
    DerivationStatus,
    ExecutionStatus,
    FactState,
    PositionType,
    RequirementCode,
    RequirementVerdict,
    SourceClass,
)
from packages.contracts.fixtures.dream import dream_packet
from packages.contracts.models import (
    Approval,
    Claim,
    HoldingRow,
    Mark,
    Money,
    Packet,
    Period,
    RequirementAssessment,
    SourceFact,
)
from packet import export as export_module
from packet.evidence import Evidence, HoldingEvidence, SourceDocument
from packet.export import MANIFEST_NAME, PacketExportError, export
from packet.layout import safe_name
from packet.tables import approved_fair_value, stated_figure
from packet.workbook import csv_bytes, workbook_bytes

DSN = dsn()
ORACLE = json.loads(Path("evals/oracle/derived.json").read_text(encoding="utf-8"))
needs_db = pytest.mark.skipif(DSN is None, reason="no DATABASE_URL")


# ── synthetic fixtures ───────────────────────────────────────────────────
SEED_TEXT = "Series B Preferred Stock issued at $8.00 per share, 625,000 shares."
QUOTE = "issued at $8.00 per share"


def _document(version_id: str = "dv_x", text: str = SEED_TEXT) -> SourceDocument:
    return SourceDocument(
        document_version_id=version_id,
        source_file_id="sf_x",
        filename="Agreement.pdf",
        content_hash="c" * 64,
        byte_size=4,
        extractor="pdftotext@1",
        text_hash="t" * 64,
        page_count=1,
        payload=b"pdf!",
        canonical_text=text,
    )


def _claim(holding_id: str, version_id: str = "dv_x") -> Claim:
    return Claim(
        id=f"{holding_id}:spa",
        document_version_id=version_id,
        holding_id=holding_id,
        claim_key="spa",
        source_class=SourceClass.EXECUTED_TRANSACTION_DOC,
        execution_status=ExecutionStatus.EXECUTED,
        issued_date=date(2025, 1, 1),
        applicable_from=date(2025, 1, 1),
    )


def _fact(claim_id: str, version_id: str = "dv_x", text: str = SEED_TEXT) -> SourceFact:
    start = text.index(QUOTE)
    return SourceFact(
        id=1,
        claim_id=claim_id,
        field_name="pps",
        value_text="8.00",
        value_numeric=Decimal("8.000000000000"),
        state=FactState.CANONICAL,
        citation=from_stored(
            document_version_id=version_id,
            quote=QUOTE,
            span=(start, start + len(QUOTE)),
            canonical_text=text,
        ),
    )


def _evidence(holding_id: str, text: str = SEED_TEXT) -> Evidence:
    claim = _claim(holding_id)
    return Evidence(
        by_holding={
            holding_id: HoldingEvidence(
                holding_id=holding_id,
                claims=(claim,),
                facts={claim.id: (_fact(claim.id, text=text),)},
                documents=(_document(text=text),),
            )
        },
        decisions=(),
    )


def _row(
    holding_id: str = "h1",
    company: str = "Acme",
    *,
    held: bool = True,
    amount: str | None = "1000",
    verdict: RequirementVerdict = RequirementVerdict.SUFFICIENT,
    approval: Approval | None = None,
) -> HoldingRow:
    mark = (
        None
        if amount is None
        else Mark(
            id=1,
            holding_id=holding_id,
            period_id="p1",
            reported=Money(amount=Decimal(amount), currency="USD"),
            derivation_status=DerivationStatus.NOT_DERIVABLE,
            derivation_reason="TRACKER_FIGURE_ONLY",
        )
    )
    reasons = [] if verdict is RequirementVerdict.SUFFICIENT else ["NEEDS_EVIDENCE"]
    return HoldingRow(
        holding_id=holding_id,
        company_name=company,
        position_type=PositionType.DIRECT_EQUITY,
        held_at_date=held,
        mark=mark,
        assessments=[
            RequirementAssessment(
                requirement=code,
                verdict=verdict
                if code in (RequirementCode.R1, RequirementCode.R2)
                else RequirementVerdict.NOT_APPLICABLE,
                reason_codes=list(reasons)
                if code in (RequirementCode.R1, RequirementCode.R2)
                else [],
                policy_version="v1",
            )
            for code in RequirementCode
        ],
        approval=approval,
    )


def _packet(*rows: HoldingRow) -> Packet:
    return Packet(
        fund_id="fund_x",
        period=Period(
            id="p1",
            fund_id="fund_x",
            period_date=date(2025, 12, 31),
            audit_scope=AuditScope.PACKET,
            label="FY2025",
        ),
        rows=list(rows),
        schema_version="1",
        policy_version="v1",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


# ── the shape of a published packet ──────────────────────────────────────
def test_a_published_packet_carries_every_artefact_the_letter_asks_for(tmp_path: Path) -> None:
    """Workbook, per-company folders, index, approval log, gap report, manifest."""
    written = export(_packet(_row()), _evidence("h1"), tmp_path / "pk")
    names = set(written.paths)
    assert "Valuation_Support.xlsx" in names
    for table in (
        "cover",
        "holdings",
        "requirements",
        "evidence_index",
        "approval_log",
        "gap_report",
    ):
        assert f"{table}.csv" in names, table
    assert "companies/Acme/Agreement.pdf" in names
    assert "companies/Acme/Agreement.pdf.canonical.txt" in names
    assert (written.root / MANIFEST_NAME).is_file()
    # The manifest is not one of its own entries — it cannot hash itself.
    assert MANIFEST_NAME not in names


def test_the_manifest_hashes_what_was_written_and_numbers_it_one_to_n(tmp_path: Path) -> None:
    written = export(_packet(_row()), _evidence("h1"), tmp_path / "pk")
    entries = written.manifest["entries"]
    assert [e["ordinal"] for e in entries] == list(range(1, len(entries) + 1))
    assert [e["path"] for e in entries] == sorted(e["path"] for e in entries)
    import hashlib

    for entry in entries:
        payload = (written.root / entry["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["content_hash"]
    assert len(written.manifest_hash) == 64


def test_editing_a_published_file_no_longer_matches_the_hash_it_carries(tmp_path: Path) -> None:
    """The manifest is content-addressed, so tampering is detectable rather than polite."""
    written = export(_packet(_row()), _evidence("h1"), tmp_path / "pk")
    import hashlib

    target = written.root / "holdings.csv"
    recorded = next(e for e in written.manifest["entries"] if e["path"] == "holdings.csv")
    target.write_bytes(target.read_bytes() + b"tampered\n")
    assert hashlib.sha256(target.read_bytes()).hexdigest() != recorded["content_hash"]


# ── the failures the packet must refuse ──────────────────────────────────
def test_an_approved_row_that_is_unsupported_fails_the_export(tmp_path: Path) -> None:
    """The one figure this system exists to be unable to print.

    `PacketTotals` refuses an approved fair-value total containing unsupported
    inputs. Reaching that state must fail the whole generation, because the
    alternative is a deliverable stating that somebody approved a figure nothing
    supports.
    """
    approval = Approval(
        id=1,
        decision_type=DecisionType.VALUATION,
        status=DecisionStatus.APPROVED,
        mark_id=1,
        evidence_assessment_ids=[7],
        actor_id="cfo",
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    bad = _packet(_row(verdict=RequirementVerdict.MISSING, approval=approval))
    with pytest.raises(ValueError, match="cannot include unsupported positions"):
        approved_fair_value(bad)
    destination = tmp_path / "pk"
    with pytest.raises(PacketExportError):
        export(bad, _evidence("h1"), destination)
    assert not destination.exists()


def test_a_failed_generation_publishes_nothing_and_leaves_the_previous_packet(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "pk"
    first = export(_packet(_row()), _evidence("h1"), destination)
    before = (destination / "holdings.csv").read_bytes()

    # A citation computed against the real text, beside a document version whose
    # text no longer contains it. The database proved the span when the fact was
    # written; the export proves it again against the bytes it just wrote, which
    # is the only copy the auditor will ever open.
    claim = _claim("h1")
    broken = Evidence(
        by_holding={
            "h1": HoldingEvidence(
                holding_id="h1",
                claims=(claim,),
                facts={claim.id: (_fact(claim.id),)},
                documents=(_document(text="a document that states nothing of the kind"),),
            )
        },
        decisions=(),
    )
    with pytest.raises(PacketExportError, match="does not resolve"):
        export(_packet(_row()), broken, destination)
    assert (destination / "holdings.csv").read_bytes() == before
    assert (destination / MANIFEST_NAME).is_file()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith((".staging", ".superseded"))]
    assert first.packet_id


def test_a_cited_document_that_was_not_exported_fails_the_export(tmp_path: Path) -> None:
    claim = _claim("h1", version_id="dv_absent")
    evidence = Evidence(
        by_holding={
            "h1": HoldingEvidence(
                holding_id="h1",
                claims=(claim,),
                facts={claim.id: (_fact(claim.id, version_id="dv_absent"),)},
                documents=(),
            )
        },
        decisions=(),
    )
    with pytest.raises(PacketExportError, match="was not exported"):
        export(_packet(_row()), evidence, tmp_path / "pk")


def test_republishing_replaces_the_packet_rather_than_merging_into_it(tmp_path: Path) -> None:
    destination = tmp_path / "pk"
    export(_packet(_row(company="Acme")), _evidence("h1"), destination)
    assert (destination / "companies/Acme/Agreement.pdf").is_file()
    export(_packet(_row(company="Beta")), _evidence("h1"), destination)
    assert (destination / "companies/Beta/Agreement.pdf").is_file()
    assert not (destination / "companies/Acme").exists()


# ── the distinctions the packet must not collapse ────────────────────────
def test_a_realised_position_renders_the_absence_of_a_mark_not_a_zero(tmp_path: Path) -> None:
    """INV-7 · a position not held at the date has no mark, and no stale figure."""
    packet = _packet(
        _row(),
        _row(
            holding_id="h2",
            company="Sold",
            held=False,
            amount=None,
            verdict=RequirementVerdict.NOT_APPLICABLE,
        ),
    )
    evidence = Evidence(
        by_holding={**_evidence("h1").by_holding, "h2": HoldingEvidence("h2", (), {}, ())},
        decisions=(),
    )
    written = export(packet, evidence, tmp_path / "pk")
    rows = {r["Portfolio company"]: r for r in _read(written.root / "holdings.csv")}
    sold = rows["Sold"]
    assert sold["Tracker-reported amount (unaudited)"] == ""
    assert sold["Currency"] == ""
    assert "not held at 2025-12-31" in sold["Mark at this date"]
    assert "0" not in sold["Tracker-reported amount (unaudited)"]
    # A requirement that does not arise is not a document to chase.
    findings = {
        r["Finding"] for r in _read(written.root / "gap_report.csv") if r["Holding id"] == "h2"
    }
    assert "requirement_not_applicable" in findings
    assert "unsupported_requirement" not in findings
    # And the folder still exists, saying why it is empty.
    assert (written.root / "companies/Sold/NO_SOURCE_DOCUMENTS.txt").is_file()


def test_no_total_is_printed_without_the_kind_and_label_that_qualify_it(tmp_path: Path) -> None:
    """INV-19 · a total must say what it is a total OF.

    Including in the cover's own key column: two blocks both headed "Amount"
    collapse to one entry the moment a reader loads the file into a dictionary,
    and the entry that survives is the wrong one.
    """
    written = export(
        _packet(_row(verdict=RequirementVerdict.MISSING)), _evidence("h1"), tmp_path / "pk"
    )
    rows = _read(written.root / "cover.csv")
    labels = [r["Item"] for r in rows if r["Item"]]
    assert len(labels) == len(set(labels)), "a cover label is used twice"
    cover = {r["Item"]: r["Value"] for r in rows}
    assert cover["held_at_date_reported — amount"] == "1,000.00 USD"
    assert cover["held_at_date_reported — of which unsupported"] == "1,000.00 USD"
    assert cover["held_at_date_reported — contains unsupported inputs"] == "yes"
    assert cover["approved_fair_value — amount"] == "0.00 USD"
    assert "Tracker-reported" in cover["held_at_date_reported — what this total is"]
    kinds = [t["kind"] for t in written.manifest["totals"]]
    assert kinds == ["held_at_date_reported", "approved_fair_value"]
    for total in written.manifest["totals"]:
        assert total["label"] and total["currency"]


def test_a_packet_with_nothing_approved_says_so_rather_than_omitting_it(tmp_path: Path) -> None:
    written = export(
        _packet(_row(verdict=RequirementVerdict.MISSING)), _evidence("h1"), tmp_path / "pk"
    )
    cover = {r["Item"]: r["Value"] for r in _read(written.root / "cover.csv")}
    assert cover["Positions with a recorded valuation approval"] == "0 of 1"
    assert cover["Packet approval"].startswith("not approved")
    assert "No position in this packet carries a recorded valuation approval" in cover["Statement"]
    log = _read(written.root / "approval_log.csv")
    assert [r["Decisions recorded against this mark"] for r in log] == ["none recorded"]
    assert [r["Carries an approved valuation"] for r in log] == ["no"]
    assert "It records no approval of any position." in (written.root / "README.md").read_text()
    assert written.manifest["approvals_recorded"] == 0
    assert written.manifest["packet_approved"] is False


def test_every_indexed_figure_resolves_into_the_exported_text(tmp_path: Path) -> None:
    written = export(_packet(_row()), _evidence("h1"), tmp_path / "pk")
    rows = _read(written.root / "evidence_index.csv")
    assert rows
    for row in rows:
        body = (written.root / row["Exported canonical text"]).read_text(encoding="utf-8")
        start, end = int(row["Passage offset start"]), int(row["Passage offset end"])
        assert body[start:end] == row["Cited passage"]
        assert (written.root / row["Exported source file"]).is_file()


# ── serialisation hazards ────────────────────────────────────────────────
def test_a_quoted_passage_beginning_with_an_equals_sign_is_not_a_formula() -> None:
    """A cited passage is evidence. Excel would otherwise evaluate it."""
    from packet.tables import Table

    table = Table(
        key="t",
        title="T",
        note="",
        headers=("Cited passage",),
        rows=(("=SUM(A1:A9) as stated in the agreement",),),
    )
    payload = workbook_bytes([table])
    with zipfile.ZipFile(__import__("io").BytesIO(payload)) as book:
        sheet = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "<f>" not in sheet
    assert b"=SUM(A1:A9) as stated in the agreement" in csv_bytes(table)


def test_a_company_name_carrying_a_path_separator_cannot_leave_its_folder() -> None:
    assert safe_name("../../etc") == "__/__/etc".replace("/", "_")
    assert "/" not in safe_name("Acme / Beta, Inc.")
    assert ".." not in safe_name("..")
    # Punctuation the corpus actually uses survives, so the exported filename
    # still matches the fund's own document register.
    assert safe_name("Fund I & II (Case Study), v2") == "Fund I & II (Case Study), v2"


def test_a_cited_figure_keeps_its_stated_scale_and_loses_only_padding() -> None:
    assert stated_figure(Decimal("100000000.000000000000")) == Decimal(100000000)
    assert str(stated_figure(Decimal("100000000.000000000000"))) == "100000000"
    assert str(stated_figure(Decimal("3.290000000000"))) == "3.29"
    assert str(stated_figure(Decimal("0.000100000000"))) == "0.0001"
    assert stated_figure(None) is None


def test_the_dream_fixture_exports_with_its_gaps_intact(tmp_path: Path) -> None:
    """The hand-written slice, through the real writer. $5,000,000, all unsupported."""
    packet = dream_packet()
    evidence = Evidence(by_holding={"dream": HoldingEvidence("dream", (), {}, ())}, decisions=())
    written = export(packet, evidence, tmp_path / "pk")
    cover = {r["Item"]: r["Value"] for r in _read(written.root / "cover.csv")}
    assert cover["held_at_date_reported — amount"] == "5,000,000.00 USD"
    assert cover["held_at_date_reported — of which unsupported"] == "5,000,000.00 USD"
    assert cover["Positions with a recorded valuation approval"] == "0 of 1"


# ── the corpus, against the oracle ───────────────────────────────────────
@pytest.fixture(scope="module")
def demo() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    assert DSN is not None
    conn = psycopg.connect(DSN, options=f"-c search_path={ledger_schema()}", connect_timeout=30)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _oracle(fund: str, on: str) -> dict[str, object]:
    found = [t for t in ORACLE["totals"] if t["fund"] == fund and t["date"] == on]
    assert len(found) == 1, f"no oracle total for {fund} at {on}"
    return dict(found[0])


@needs_db
@pytest.mark.parametrize(
    ("period_id", "on"),
    [
        ("fund_ii_23q4", "2023-12-31"),
        ("fund_ii_24q4", "2024-12-31"),
        ("fund_ii_25q4", "2025-12-31"),
    ],
)
def test_each_fund_ii_packet_exports_the_figures_the_oracle_derived(
    demo: psycopg.Connection[tuple[object, ...]], tmp_path: Path, period_id: str, on: str
) -> None:
    """The corpus, end to end, checked against the independently derived answer key."""
    written = export_module.export_packet(demo, "fund_ii", period_id, tmp_path / period_id)
    expected = _oracle("fund_ii", on)
    held = next(t for t in written.manifest["totals"] if t["kind"] == "held_at_date_reported")
    assert Decimal(str(held["amount"])) == Decimal(str(expected["held_at_date_reported_total"]))
    assert Decimal(str(held["unsupported_amount"])) == Decimal(
        str(expected["unsupported_subtotal"])
    )
    assert held["unsupported_positions"] == expected["unsupported_row_count"]
    assert held["currency"] == "USD"

    holdings = _read(written.root / "holdings.csv")
    assert sum(1 for r in holdings if r[f"Held at {on}"] == "yes") == expected["positions_held"]

    # The oracle names the positions nothing has approved. The packet must name
    # the same set, and it must not be shorter.
    unapproved = {
        r["Holding id"].removeprefix("fund_ii_")
        for r in _read(written.root / "approval_log.csv")
        if r["Carries an approved valuation"] == "no"
    }
    named = expected["unapproved_marks"]
    assert isinstance(named, list)
    assert set(named) <= unapproved

    approved = next(t for t in written.manifest["totals"] if t["kind"] == "approved_fair_value")
    assert expected["approved_fair_value_total"] is None
    assert Decimal(str(approved["amount"])) == 0
    assert approved["unsupported_positions"] == 0


@needs_db
def test_the_fund_ii_25q4_packet_is_the_deliverable_and_states_its_own_gaps(
    demo: psycopg.Connection[tuple[object, ...]], tmp_path: Path
) -> None:
    written = export_module.export_packet(demo, "fund_ii", "fund_ii_25q4", tmp_path / "pk")
    cover = {r["Item"]: r["Value"] for r in _read(written.root / "cover.csv")}
    assert cover["Positions in this packet"] == "8"
    assert cover["held_at_date_reported — amount"] == "25,648,515.00 USD"
    assert cover["held_at_date_reported — of which unsupported"] == "25,648,515.00 USD"
    assert cover["held_at_date_reported — unsupported positions held at this date"] == "8 of 8"
    assert cover["approved_fair_value — amount"] == "0.00 USD"
    assert cover["Positions with a recorded valuation approval"] == "0 of 8"
    assert cover["Packet approval"].startswith("not approved")

    holdings = _read(written.root / "holdings.csv")
    assert len(holdings) == 8
    assert all(r["Valuation approval"] == "none recorded" for r in holdings)
    # The companies the letter would be organised by, one folder each.
    companies = sorted(p.name for p in (written.root / "companies").iterdir())
    assert companies == sorted(r["Portfolio company"] for r in holdings)

    gaps = _read(written.root / "gap_report.csv")
    assert len(gaps) >= 8
    assert {r["Holding id"] for r in gaps if r["Finding"] == "no_valuation_approval"} == {
        r["Holding id"] for r in holdings
    }
    # Because Market holds no document at all, and the packet says so twice.
    assert any(r["Finding"] == "no_source_documents" for r in gaps)
    assert (written.root / "companies/Because Market/NO_SOURCE_DOCUMENTS.txt").is_file()


@needs_db
def test_every_citation_in_the_real_packet_resolves_in_the_text_it_exported(
    demo: psycopg.Connection[tuple[object, ...]], tmp_path: Path
) -> None:
    """The claim that makes this audit support: a figure reaches its passage."""
    written = export_module.export_packet(demo, "fund_ii", "fund_ii_25q4", tmp_path / "pk")
    rows = _read(written.root / "evidence_index.csv")
    assert len(rows) > 100
    for row in rows:
        body = (written.root / row["Exported canonical text"]).read_text(encoding="utf-8")
        start, end = int(row["Passage offset start"]), int(row["Passage offset end"])
        assert body[start:end] == row["Cited passage"], row["Claim id"]
        assert (written.root / row["Exported source file"]).is_file()


@needs_db
def test_the_realised_position_appears_with_no_mark_rather_than_a_stale_one(
    demo: psycopg.Connection[tuple[object, ...]], tmp_path: Path
) -> None:
    """Jackpocket at 2024-12-31: `held_at_date: false`, `reported_amount: null`."""
    written = export_module.export_packet(demo, "fund_ii", "fund_ii_24q4", tmp_path / "pk")
    rows = {r["Holding id"]: r for r in _read(written.root / "holdings.csv")}
    jack = rows["fund_ii_jackpocket"]
    assert jack["Held at 2024-12-31"] == "no"
    assert jack["Tracker-reported amount (unaudited)"] == ""
    assert jack["R4 realization_support"] == "sufficient"
    oracle_row = next(
        r for r in ORACLE["rows"] if r["holding"] == "jackpocket" and r["date"] == "2024-12-31"
    )
    assert oracle_row["reported_amount"] is None
    assert oracle_row["held_at_date"] is False


@needs_db
def test_the_manifest_binds_the_packet_to_the_marks_and_documents_it_used(
    demo: psycopg.Connection[tuple[object, ...]], tmp_path: Path
) -> None:
    written = export_module.export_packet(demo, "fund_ii", "fund_ii_25q4", tmp_path / "pk")
    packet = ledger.packet(demo, "fund_ii", "fund_ii_25q4")
    assert packet is not None
    recorded = {
        (m["holding_id"], m["mark_id"], m["revision"]) for m in written.manifest["mark_revisions"]
    }
    assert recorded == {(r.holding_id, r.mark.id, r.mark.revision) for r in packet.rows if r.mark}
    assert written.manifest["policy_version"] == packet.policy_version
    assert written.manifest["ledger_schema_version"] == packet.schema_version
    assert written.manifest["extraction"]["model"] is None
    assert written.manifest["document_versions"]
    for document in written.manifest["document_versions"]:
        assert len(document["content_hash"]) == 64
        assert document["text_hash"]


@needs_db
def test_a_generated_packet_version_and_its_manifest_are_accepted_by_the_schema(
    demo: psycopg.Connection[tuple[object, ...]], tmp_path: Path
) -> None:
    """`record()` writes rows the packet-approval trigger will later read.

    Rolled back. The point is that the schema accepts the manifest this generator
    produces — the ordinals contiguous from one, the packet scoped to a packet
    period — rather than that the demo database keeps them.
    """
    written = export_module.export_packet(demo, "fund_ii", "fund_ii_25q4", tmp_path / "pk")
    try:
        export_module.record(demo, written)
        stored = demo.execute(
            "select count(*), min(ordinal), max(ordinal) from packet_manifest_entry"
            " where packet_id = %s",
            (written.packet_id,),
        ).fetchone()
        assert stored is not None
        assert stored[0] == len(written.manifest["entries"])
        assert (stored[1], stored[2]) == (1, stored[0])
    finally:
        demo.rollback()
