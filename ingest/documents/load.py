"""Every document in the corpus, into the ledger, with its citations.

The four extractor families each know how to read their own documents and none
of them knows where the documents are or which holding they concern. That is
deliberate — an extractor that owned a path would be untestable without the
corpus — so the mapping lives here, in one table, and it is the only place a
document is bound to a holding.

    .venv/bin/python -m ingest.documents.load            # what would be written
    .venv/bin/python -m ingest.documents.load --commit   # write it

Every citation is verified against the canonical text before insert and again by
the trigger in `0008_citations_resolve.sql`. A document that fails is reported
and skipped; the others still land. The point is the complete list of what did
not parse, not the first failure — an ingestion run that stops at the first bad
document tells you nothing about the other nineteen.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import psycopg

from ingest.documents import (
    extract_cap_table,
    extract_irregular,
    extract_memo,
    extract_spa,
    extract_term_sheet,
)
from ingest.documents.claims import ClaimDraft, store_claim, store_document
from ingest.documents.extract_dream import dream_claim
from ingest.documents.parse import ExtractionFailed, ParsedDocument, parse
from packages.contracts.citations import CitationError

Conn = psycopg.Connection[tuple[object, ...]]

CORPUS = Path("7GC Audit Case Study/02_Portfolio Documentation")

#: A builder takes the parsed document and its holding and returns the claims
#: that document makes. One document may make several — INV-15, authority lives
#: on the claim — so every entry returns a sequence even when it is of length 1.
Builder = Callable[[str, ParsedDocument, str], Sequence[ClaimDraft]]


def _one(fn: Callable[..., ClaimDraft], **extra: object) -> Builder:
    def build(version_id: str, parsed: ParsedDocument, holding_id: str) -> Sequence[ClaimDraft]:
        return [
            fn(
                document_version_id=version_id,
                parsed=parsed,
                holding_id=holding_id,
                **extra,
            )
        ]

    return build


def _many(fn: Callable[..., Sequence[ClaimDraft]], **extra: object) -> Builder:
    def build(version_id: str, parsed: ParsedDocument, holding_id: str) -> Sequence[ClaimDraft]:
        return fn(
            document_version_id=version_id,
            parsed=parsed,
            holding_id=holding_id,
            **extra,
        )

    return build


@dataclass(frozen=True)
class Source:
    """One file, the holding it concerns, and what reads it."""

    path: Path
    holding_id: str
    build: Builder


#: The corpus. Twenty documents, fourteen companies, and the reason the packet
#: can say anything at all about what supports a mark.
#:
#: Because Market appears nowhere on this list, and that is the single most
#: important fact in it: the fund holds a $1,000,000 position with no document
#: of any kind. A pipeline that produced an empty record for it rather than no
#: record would read as coverage.
SOURCES: tuple[Source, ...] = (
    # ── executed transaction documents ────────────────────────────────
    *(
        Source(
            path=spec.path,
            holding_id=holding,
            build=_many(extract_spa.spa_claims, spec=spec),
        )
        for spec, holding in (
            (extract_spa.FLUIDSTACK, "fund_ii_fluidstack"),
            (extract_spa.POOLSIDE, "fund_ii_poolside"),
            (extract_spa.ROOFSTOCK, "fund_i_roofstock"),
        )
    ),
    # ── pro forma capitalisation tables ───────────────────────────────
    Source(
        CORPUS / "Dream/Dream - Series B - Pro Forma Capitalization Table (November 14, 2025).pdf",
        "fund_ii_dream",
        _one(dream_claim),
    ),
    Source(
        CORPUS / "Fluidstack/Fluidstack - Series B - Pro Forma Capitalization Table Excerpt"
        " (December 18, 2025).pdf",
        "fund_ii_fluidstack",
        _many(extract_cap_table.fluidstack_claims),
    ),
    Source(
        CORPUS / "Sway/Sway - Series A-3 Recapitalization - Pro Forma Capitalization Table"
        " (September 30, 2025).pdf",
        "fund_ii_sway",
        _one(extract_cap_table.sway_claim),
    ),
    # ── third-party memos, fund memos, administrator statements ───────
    Source(
        CORPUS / "Moonfare/Moonfare - Third-Party Valuation Memorandum - FY2023"
        " (December 31, 2023).pdf",
        "fund_ii_moonfare",
        _one(extract_memo.moonfare_memo_claim),
    ),
    Source(
        CORPUS / "Moonfare/Moonfare - FX Re-measurement Memo - FY2024 (December 31, 2024).pdf",
        "fund_ii_moonfare",
        _one(extract_memo.moonfare_fx_claim),
    ),
    Source(
        CORPUS
        / "Capsule/Capsule - Third-Party Valuation Memorandum - FY2022 (December 31, 2022).pdf",
        "fund_i_capsule",
        _one(extract_memo.capsule_memo_claim),
    ),
    *(
        Source(
            CORPUS / f"Jio/Horizon Access Fund IV (Jio Feeder) - Capital Account Statement"
            f" - 12.31.{year}.pdf",
            "fund_i_jio_indirect",
            _one(extract_memo.jio_statement_claim, as_of=date(year, 12, 31)),
        )
        for year in (2023, 2024, 2025)
    ),
    Source(
        CORPUS / "Jio/Email - Meridian Fund Services - Annual Capital Account Statement"
        " (January 30, 2026).txt",
        "fund_i_jio_indirect",
        _one(extract_memo.meridian_email_claim),
    ),
    # ── the irregulars ────────────────────────────────────────────────
    Source(
        CORPUS / "Anthropic/The Signal - Anthropic Said to Close Round at 120B Valuation"
        " (December 9, 2025).pdf",
        "fund_ii_anthropic",
        _one(extract_irregular.anthropic_claim),
    ),
    Source(
        CORPUS / "Banzai/Banzai (BNZA) - Saved Quote Record - Year-End Closing Prices.txt",
        "fund_i_banzai",
        _many(extract_irregular.banzai_claims),
    ),
    Source(
        CORPUS / "Jackpocket/Jackpocket - Notice of Merger Consideration to Stockholders"
        " (May 20, 2024).pdf",
        "fund_ii_jackpocket",
        _one(extract_irregular.jackpocket_claim),
    ),
    Source(
        CORPUS / "Lucra/Lucra - Series A-1 - Term Sheet Excerpt (May 2024).pdf",
        "fund_ii_lucra",
        _one(extract_irregular.lucra_term_sheet_claim),
    ),
    Source(
        CORPUS / "Lucra/Lucra - Email from CEO re Series A-2 Close (October 17, 2025).txt",
        "fund_ii_lucra",
        _one(extract_irregular.lucra_email_claim),
    ),
    Source(
        CORPUS / "Dream/Dream - Series B Closing Notice Email (November 17, 2025).txt",
        "fund_ii_dream",
        _one(extract_irregular.dream_email_claim),
    ),
    Source(
        CORPUS / "The Mom Project/The Mom Project - Series C - Term Sheet Excerpt"
        " (September 2021).pdf",
        "fund_i_the_mom_project",
        _one(extract_term_sheet.mom_project_claim),
    ),
)


@dataclass(frozen=True)
class Outcome:
    """What one document did."""

    path: Path
    claims: int
    facts: int
    error: str | None = None


def ingest(conn: Conn, sources: Sequence[Source] = SOURCES) -> list[Outcome]:
    """Parse, store and cite every document. One savepoint each."""
    out: list[Outcome] = []
    for source in sources:
        if not source.path.exists():
            out.append(Outcome(source.path, 0, 0, "not in the corpus"))
            continue
        try:
            with conn.transaction():
                parsed = parse(source.path)
                version_id = store_document(conn, parsed)
                drafts = source.build(version_id, parsed, source.holding_id)
                for draft in drafts:
                    store_claim(conn, version_id, draft, parsed.canonical_text)
                out.append(
                    Outcome(
                        source.path,
                        len(drafts),
                        sum(len(d.facts) for d in drafts),
                    )
                )
        except (ExtractionFailed, CitationError, psycopg.Error, ValueError) as exc:
            out.append(Outcome(source.path, 0, 0, str(exc).strip().splitlines()[0][:160]))
    return out


def main(argv: list[str] | None = None) -> int:
    from api.config import dsn, ledger_schema

    parser = argparse.ArgumentParser(description="Ingest the corpus into the ledger.")
    parser.add_argument("--commit", action="store_true", help="write; otherwise roll back")
    parser.add_argument(
        "--schema",
        default=None,
        help="schema to write into; defaults to LEDGER_SCHEMA, else public",
    )
    args = parser.parse_args(argv)

    url = dsn("MIGRATION_DATABASE_URL")
    if not url:
        print("MIGRATION_DATABASE_URL is not set", file=sys.stderr)
        return 1

    # psycopg's OUTERMOST `transaction()` block COMMITS on exit; only a nested
    # one is a savepoint. `ingest()` opens one per document, so without an outer
    # block around them each document committed itself and `--commit` was
    # decorative — the dry run had already written everything, and the real run
    # then reported nineteen duplicate-key failures against its own output.
    #
    # This is the same trap `tests/test_real_data_ledger.py` documents in as many
    # words, and it arrived here by moving code out of the fixture that used to
    # supply the outer transaction. The rollback is therefore explicit.
    # `is None`, not falsy: omitting the flag means "use the default", and
    # passing it empty is a caller stating a schema it cannot have meant.
    # Collapsing those let `--schema ""` run against the demo ledger.
    schema = ledger_schema() if args.schema is None else args.schema
    if not schema.replace("_", "").isalnum():
        print(f"{schema!r} is not a plain identifier", file=sys.stderr)
        return 1

    with psycopg.connect(url, connect_timeout=30) as conn:
        # An identifier, so it is formatted rather than parameterised —
        # `set search_path to %s` quotes it as a literal and selects nothing.
        conn.execute(f"set search_path to {schema}")
        try:
            with conn.transaction() as outer:
                results = ingest(conn)
                if not args.commit:
                    raise psycopg.Rollback(outer)
        except psycopg.Rollback:
            pass

    claims = sum(r.claims for r in results)
    facts = sum(r.facts for r in results)
    failed = [r for r in results if r.error]
    for r in results:
        mark = "  " if not r.error else "!!"
        detail = f"{r.claims} claim(s), {r.facts} cited fact(s)" if not r.error else r.error
        print(f"{mark} {r.path.name[:66]:68} {detail}")
    print(
        f"\n{len(results) - len(failed)}/{len(results)} documents · {claims} claims · {facts} facts"
    )
    print("committed" if args.commit else "rolled back — pass --commit to write")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
