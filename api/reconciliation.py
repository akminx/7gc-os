"""Two read-only projections the fund asked for by name.

**The reconciliation report.** `ingest/trackers/real_findings.json` is the
committed output of `ingest/trackers/snapshot.py` — 32 places where the
valuation tracker and the master breakdown disagree with each other. It ships
without the private workbooks, so this route answers identically in CI and in
production. Until now it was a file nobody could see.

**The completeness scorecard.** One line per fund-period: how many positions the
packet holds, how many are fully supported, how many carry an open gap, and how
many are marked pro forma. Every one of those is a count over rows, and SPEC
§5.3 assigns counts to the API — "0 of 8" reaches the browser as two integers,
never as a division.

Two distinctions are load-bearing here and neither may be flattened:

* **`scope`.** SPEC §2 closes the auditor's packet at six measurement dates; the
  other six fund-periods are ingested for lineage. A finding about 6/30/2025 is
  not a finding about 12/31/2025. The findings are therefore delivered already
  partitioned by scope, in three separate buckets with three separate counts, so
  a caller cannot render one list by accident. One finding — the fund-wide cost
  basis column — carries no period at all, which is why there are three buckets
  and not two: dropping it would lose a real disagreement, and filing it under
  either date would assert something the workbook does not say.
* **`stated` vs `computed`.** They are two different facts about the same
  column, and the delta between them is the finding. It is subtracted here
  because §5.3 forbids the browser subtracting two canonical figures, and
  because a delta whose sign nobody wrote down is a number that can be read
  backwards — hence `delta_computed_minus_stated`, which says which way round it
  goes.

SPEC §3.1 · the public surface is read-only. Both routes are GETs.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException

from api import ledger
from api.config import dsn, ledger_schema
from api.serialize import totals_json
from packages.contracts.fixtures.dream import dream_packet
from packages.contracts.models import Packet
from packet.export import PacketExportError, export_packet

router = APIRouter()

SNAPSHOT = Path(__file__).resolve().parents[1] / "ingest" / "trackers" / "real_findings.json"

#: Where a generated packet lands. Gitignored: a packet is a build artefact of a
#: private corpus and does not belong in the repository.
PACKET_OUT = Path(os.environ.get("PACKET_OUT_DIR", "out/packets"))

#: The bucket a finding with no `scope` falls in. It is a named third state, not
#: a default: the cost-basis column is stated once for the whole fund and belongs
#: to no measurement date, so it is neither in the auditor's packet nor ingested
#: for one period's lineage.
UNSCOPED = "unscoped"

#: Rendering order, fixed, so a bucket cannot vanish from the report by being
#: empty. `packet` leads because it is the only one the audit letter asks about.
SCOPE_ORDER: tuple[str, ...] = ("packet", "lineage_only", UNSCOPED)

PERIOD_SCOPES = frozenset({"packet", "lineage_only"})


def _connect() -> psycopg.Connection[tuple[object, ...]] | None:
    """A ledger connection, or `None` when no database is configured.

    `prepare_threshold=None` is not optional and not a tuning knob. Supabase's
    pooler runs in TRANSACTION mode, so a statement prepared on one backend
    session is absent on the next; psycopg prepares a query automatically after
    its fifth execution, and the scorecard runs `packet()` six times in one
    request. Left at the default this route is a 500 in production while every
    test passes locally against the direct session-mode connection.

    The schema name is validated before a socket is opened, because it is
    interpolated as an identifier — `set search_path to %s` quotes it as a
    string literal and silently selects nothing.
    """
    url = dsn("MIGRATION_DATABASE_URL") or dsn("DATABASE_URL")
    if not url:
        return None
    schema = ledger_schema()
    if not schema.replace("_", "").isalnum():
        raise HTTPException(status_code=500, detail="LEDGER_SCHEMA is not an identifier")
    try:
        conn = psycopg.connect(url, connect_timeout=10, prepare_threshold=None)
        conn.execute(f"set search_path to {schema}")
    except psycopg.Error:
        # A configured but unreachable database must not read as "no database",
        # which would serve the one-row demo stub under the fund's name.
        raise HTTPException(status_code=503, detail="ledger unavailable") from None
    return conn


# ── The reconciliation snapshot ──────────────────────────────────────────
# psycopg and `json.load` both hand values back untyped. The alternative to
# narrowing each one is a type-suppression comment, and this repo holds that
# ceiling at zero, because a suppression is how a type check quietly stops
# checking. `api/ledger.py` does the same thing for the same reason.


def _text(value: object) -> str:
    assert isinstance(value, str)
    return value


def _opt_text(value: object) -> str | None:
    assert value is None or isinstance(value, str)
    return value


def _count(value: object) -> int:
    assert isinstance(value, int)
    return value


def _as_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def _plain(value: Decimal) -> str:
    """A decimal as digits, never in exponent form.

    `Decimal.normalize()` renders 2000000 as `2E+6`, which is the same number and
    a different string — and a figure that reaches a screen as `2E+6` is one an
    auditor cannot compare to the workbook cell it came from. The snapshot
    writer normalises the same way, so a delta and its two operands are rendered
    by the same rule.
    """
    normalised = value.normalize()
    if normalised == normalised.to_integral_value():
        normalised = normalised.to_integral_value()
    return f"{normalised:f}"


def _delta(stated: str | None, computed: str | None) -> str | None:
    """`computed − stated`, or `None` when the finding states only one figure.

    Subtracted here rather than in the browser: SPEC §5.3 puts arithmetic on
    canonical figures on this side of the line. `Decimal`, never `float` — the
    whole money path exists to keep these figures out of binary floating point,
    and a delta computed in floats is wrong before anyone reads it (INV-11).
    """
    if stated is None or computed is None:
        return None
    return _plain(Decimal(computed) - Decimal(stated))


def _scope_of(value: object) -> str:
    if value is None:
        return UNSCOPED
    scope = _text(value)
    if scope not in PERIOD_SCOPES:
        raise HTTPException(status_code=500, detail=f"unknown finding scope {scope!r}")
    return scope


def _finding(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    stated = _opt_text(value["stated"])
    computed = _opt_text(value["computed"])
    return {
        "kind": _text(value["kind"]),
        "subject": _text(value["subject"]),
        "scope": _scope_of(value["scope"]),
        "stated": stated,
        "computed": computed,
        "delta_computed_minus_stated": _delta(stated, computed),
        "detail": _text(value["detail"]),
    }


def _snapshot() -> dict[str, object]:
    """The committed findings, read per request rather than at import.

    Read at import time, a missing or malformed snapshot takes the whole service
    down at startup instead of failing the one route that needs it.
    """
    if not SNAPSHOT.exists():
        raise HTTPException(status_code=500, detail="reconciliation snapshot is missing")
    parsed: object = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _bucket(scope: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    mine = [f for f in findings if f["scope"] == scope]
    kinds = sorted({_text(f["kind"]) for f in mine})
    return {
        "scope": scope,
        "finding_count": len(mine),
        "by_kind": [{"kind": k, "count": sum(1 for f in mine if f["kind"] == k)} for k in kinds],
        "findings": mine,
    }


@router.get("/reconciliation")
def get_reconciliation() -> dict[str, Any]:
    """Where the fund's two workbooks disagree, partitioned by audit scope.

    The findings arrive already split into buckets rather than as one list with
    a scope field on each row. A flat list is one `.filter()` away from a screen
    that reports a 6/30/2025 disagreement as a finding about the packet, and the
    shape of the response is a stronger guarantee than a rule someone remembers.
    """
    doc = _snapshot()
    findings = [_finding(f) for f in _as_list(doc["findings"])]
    return {
        "source": "tracker_snapshot",
        "snapshot": "ingest/trackers/real_findings.json",
        "positions": _count(doc["positions"]),
        "tranches": _count(doc["tranches"]),
        "fund_periods": _count(doc["fund_periods"]),
        #: Every finding the reconciler produced, across all twelve tracker
        #: fund-periods. It is NOT a packet figure and is never the headline: the
        #: three bucket counts are, and they are reported separately because
        #: adding them answers a question the audit letter does not ask.
        "finding_count": len(findings),
        "scopes": [_bucket(scope, findings) for scope in SCOPE_ORDER],
    }


# ── The completeness scorecard ───────────────────────────────────────────


def _totals(built: Packet) -> dict[str, Any] | None:
    """The packet's total, or `None` when no row carries a mark.

    `Packet.totals()` refuses a packet whose rows hold no mark at all, because
    there is no currency to sum in and no figure to report. That is a legitimate
    state — a fund that exited every position still files a packet — and it is
    an absence the screen states rather than a 500.
    """
    if not any(row.mark is not None for row in built.rows):
        return None
    return totals_json(built.totals())


def _line(built: Packet) -> dict[str, Any]:
    """One fund-period, as a partner reads it.

    Every field is a count this function performs, so the browser performs none.
    `fully_supported` and `positions` travel as two integers precisely so that
    "0 of 8" is a sentence assembled from two supplied numbers rather than a
    ratio the display layer derived (SPEC §5.3).

    `open_gap_positions` counts rows that are not fully supported — the same
    quantity `PacketTotals.packet_gap_positions` reports, computed here as well
    because a packet with no marks has counts and no totals. The two are checked
    against each other in `tests/test_reconciliation.py`, so the second
    derivation cannot drift away from the first in silence.

    `held_at_date` is INV-7 and is not decoration: a position realised during the
    period under audit is in the packet — the audit letter asks for realised
    investments by name — and is not an input to the total beside it.
    """
    rows = built.rows
    held = sum(1 for row in rows if row.held_at_date)
    return {
        "fund_id": built.fund_id,
        "period_id": built.period.id,
        "label": built.period.label,
        "period_date": built.period.period_date.isoformat(),
        "audit_scope": built.period.audit_scope.value,
        "counts": {
            "positions": len(rows),
            "fully_supported": sum(1 for row in rows if row.supported),
            "open_gap_positions": sum(1 for row in rows if not row.supported),
            "pro_forma_positions": sum(
                1 for row in rows if any(a.pro_forma for a in row.assessments)
            ),
            "held_at_date": held,
            "not_held_at_date": len(rows) - held,
        },
        "totals": _totals(built),
        "absent_reason": None,
    }


def _absent_line(fund_id: str, period_id: str, label: str) -> dict[str, Any]:
    """A fund-period the ledger lists but cannot assemble a packet for.

    The counts are `null` rather than zero. "Zero of zero positions supported"
    is a scorecard line a partner would read as a finding about the fund; "no
    packet could be assembled" is a finding about the ledger, and the two must
    not render the same way.
    """
    return {
        "fund_id": fund_id,
        "period_id": period_id,
        "label": label,
        "period_date": None,
        "audit_scope": None,
        "counts": None,
        "totals": None,
        "absent_reason": "the ledger lists this fund-period but holds no position for it",
    }


@router.get("/scorecard")
def get_scorecard() -> dict[str, Any]:
    """SPEC §12.1 · completeness, one line per fund-period.

    Every packet-scope fund-period the ledger can build, in the order it lists
    them, rather than a hard-coded six. The list of periods is a property of the
    ledger; writing it down here would make the screen right until the day the
    fund adds a measurement date.
    """
    conn = _connect()
    if conn is None:
        # No DSN: the same honest fallback the packet routes use. `source` says
        # so, because a scorecard showing one holding under the fund's name is a
        # figure nobody can trace.
        return {"source": "fixture", "periods": [_line(dream_packet())]}
    with conn:
        lines = []
        for fund_id, period_id, label in ledger.packet_periods(conn):
            built = ledger.packet(conn, fund_id, period_id)
            lines.append(_absent_line(fund_id, period_id, label) if built is None else _line(built))
    return {"source": "ledger", "periods": lines}


# ── The document behind a citation ───────────────────────────────────────
# A citation is `quote` plus `[span_start, span_end)` into a stored
# `canonical_text`, and `0008_citations_resolve.sql` enforces that
# `substring(canonical_text, span) = quote`. Sending only the quote makes that
# constraint unverifiable from the screen: a reader is shown the sentence
# somebody says is in the document rather than the sentence in the document.
#
# So the text travels. The browser highlights `[span_start, span_end)` in it and
# the reader sees the passage in its own surroundings — which is also the only
# way the offsets stop being debug output and become what they are, the
# auditor's instruction for finding it again by hand.
#
# The whole text, never a window around the span. A server that decided how much
# context to send would be deciding what an auditor is allowed to read next to
# the quote, and the corpus is 700 to 4,000 characters a document.


@router.get("/documents/{document_version_id}")
def get_document(document_version_id: str) -> dict[str, Any]:
    """One document version's canonical text, with the file it was extracted from.

    `extractor` and `text_hash` are on the response because a passage is only
    re-verifiable against a NAMED extraction: the same PDF through two
    extractors produces two canonical texts and therefore two different sets of
    offsets (SPEC §8).
    """
    conn = _connect()
    if conn is None:
        # The fixture branch has no corpus behind it. Answering with an empty
        # text would render as a document that says nothing, which is a claim
        # about the fund rather than about this deployment.
        raise HTTPException(
            status_code=404,
            detail="no database is configured, so this deployment holds no document text",
        )
    with conn:
        found = conn.execute(
            "select dv.canonical_text, dv.extractor, dv.text_hash, dv.page_count, sf.filename"
            " from document_version dv join source_file sf on sf.id = dv.source_file_id"
            " where dv.id = %s",
            (document_version_id,),
        ).fetchone()
    if found is None:
        raise HTTPException(status_code=404, detail=f"no document version {document_version_id!r}")
    text = _text(found[0])
    return {
        "source": "ledger",
        "document_version_id": document_version_id,
        "filename": _text(found[4]),
        "extractor": _text(found[1]),
        "text_hash": _text(found[2]),
        "page_count": _count(found[3]),
        #: Counted here so the browser never takes `.length` of the text and
        #: calls it a figure. An offset past this is a citation that does not
        #: resolve, and the screen can say so without measuring anything.
        "text_length": len(text),
        "text": text,
    }


# ── Exporting the auditor packet ─────────────────────────────────────────
# A GET that writes a file, which deserves stating rather than hiding. SPEC
# §3.1 keeps the public surface read-only, and what it is read-only about is the
# LEDGER: this route records nothing, supersedes nothing and touches no table —
# `packet.export.record()` is the function that would, and it is deliberately
# not called here. What it writes is a build artefact into a gitignored
# directory, reproducible from the ledger it just read.
#
# `export_packet` validates before it publishes: every citation is resolved
# against the text actually exported, every manifest entry is re-hashed from
# disk, and a packet containing an approved-but-unsupported position is refused
# by `PacketTotals` itself. A failure therefore leaves no partial packet, and
# this route reports the refusal verbatim instead of a status code — the refusal
# names which citation or which position, and that sentence is the deliverable.


@router.get("/funds/{fund_id}/periods/{period_id}/export")
def export_auditor_packet(fund_id: str, period_id: str) -> dict[str, Any]:
    """Generate the auditor packet for one fund-period and report what was written."""
    conn = _connect()
    if conn is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "no database is configured, so there is no ledger to export. "
                "A packet built from the demo stub would carry the fund's name over one holding."
            ),
        )
    destination = PACKET_OUT / period_id
    with conn:
        try:
            written = export_packet(conn, fund_id, period_id, destination)
        except PacketExportError as exc:
            # 409, not 500. The export did not fail; it REFUSED, and it says
            # why — an unresolved citation or an unsupported approved position
            # is a finding about the packet, not a fault in the service.
            raise HTTPException(status_code=409, detail=str(exc)) from None
    return {
        "source": "ledger",
        "fund_id": written.fund_id,
        "period_id": written.period_id,
        "packet_id": written.packet_id,
        "root": str(written.root),
        "manifest_hash": written.manifest_hash,
        "schema_version": written.schema_version,
        "policy_version": written.policy_version,
        #: Counted here, like every other count in this module, so the browser
        #: renders a supplied integer rather than taking `.length` of a list and
        #: calling it a figure (SPEC §5.3).
        "file_count": len(written.paths),
        "files": written.paths,
        #: Stated, not implied. The packet is on the API host's disk; a reader
        #: who assumes a browser download gets a silent no-op.
        "recorded_in_ledger": False,
    }
