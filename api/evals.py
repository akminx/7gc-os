"""`GET /evals` · what this system has actually been measured to do.

Handoff items 7 and 7a. One read-only route, no query parameters that change
what is measured, and **every number computed when the request arrives**. Not
one is transcribed: the values in the handoff's table came from agent reports
and triage files, and typing any of them here would make the page a claim about
a run nobody can reproduce — the same defect as a hand-maintained derived value,
which this project has already failed at twice.

So Recall@K is measured by RUNNING the retrieval, the citation count by
resolving citations against the stored text, the validator census by running the
validators, and the extraction figures by replaying the recorded fixture. A
number that cannot be produced that way is not on this page; it is in
`not_measured` with the command that does produce it.

**The condition that makes this worth serving at all.** A page of green hundreds
is marketing and a reader will discount every figure on it. So the blind Recall
figure leads — 24 of 40 — and the entity-scoped 40 of 40 stands beside it with
the reason they differ: the SQL filter leaves about one candidate document per
case, so the scoped number scores the filter and not the ranker. The two
extraction refusals are on the page as results rather than faults.

**Rates arrive as a numerator and a denominator.** A count is auditable; a
percentage is a conclusion, and `scripts/check-web-arch.mjs` correctly refuses a
browser that divides one count by another. Where a mean is genuinely the
readable form — candidates per case — it is computed here and sent WITH its two
counts, so a reader can check the division.

**The oracle comparison is deliberately absent, and that absence is the point.**
`tests/test_gate_guards.py` refuses any reference to the answer key from
`api/`, `policy/` and `packet/` — the product must not be able to see the
answers, whether by import or by file read. A route that reported its own
agreement with the answer key would be exactly the thing that guard exists to
prevent. It is measured, by the suite, and this page says where.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from evidence.extract import LUCRA_STEM as EXTRACTION_STEM
from evidence.extract import (
    ExtractionRefused,
    FixtureMissing,
    extract_from_fixture,
)
from evidence.retrieve import GoldCase, RetrievalError, gold_cases, retrieve
from ingest.documents.parse import ParsedDocument, split_pages
from packages.contracts.citations import from_stored, resolves_in
from packages.contracts.enums import RequirementVerdict
from packages.contracts.models import Packet
from packet.recompute import Recomputation, for_packet
from policy.inputs import Ledger
from policy.validators import Outcome

Conn = psycopg.Connection[tuple[object, ...]]


def _as[T](kind: type[T], value: object) -> T:
    """Narrow one column. psycopg hands every value back as `object`.

    The suppression ceiling for this repo is zero, so the alternative to
    narrowing is not a cast — it is the kind of comment the gate refuses, and
    counts even when it appears in prose explaining itself. This is the third
    home for the same three lines (`packet/evidence.py` and
    `api/reconciliation.py` have their own); short enough that the duplicate
    detector does not see a clone, and it wants promoting to one public helper
    the next time someone is already editing all three.
    """
    assert isinstance(value, kind), f"expected {kind.__name__}, got {type(value).__name__}"
    return value


#: SPEC §11 fixes K at 5. The smaller cutoffs are reported beside it because the
#: SHAPE of the curve is the finding: blind, this ranker puts a relied-upon
#: document in the top 1 for six of forty cases and in the top 5 for
#: twenty-four, and one number cannot say that.
REPORTED_K = (1, 3, 5)

#: The largest cutoff, and the only retrieval actually run. `retrieve` sorts the
#: whole candidate list and returns `passages[:k]`, so the top 1 and the top 3
#: are prefixes of the top 5 — one query per case answers all three cutoffs
#: instead of three. `tests/test_evals.py` pins that against
#: `evidence.retrieve.recall_at_k`, which is the reference implementation, so a
#: change to the ranking that broke the prefix property would go red here rather
#: than quietly making this page report a different number from the suite.
MEASURED_K = max(REPORTED_K)


@dataclass(frozen=True)
class CaseResult:
    """One gold case, retrieved once, at the largest cutoff."""

    case: GoldCase
    retrieved: tuple[str, ...]

    def hit(self, k: int) -> bool:
        return bool(self.case.relevant & set(self.retrieved[:k]))

    def complete(self, k: int) -> bool:
        return self.case.relevant <= set(self.retrieved[:k])


def _measure(conn: Conn, cases: tuple[GoldCase, ...], *, entity_scoped: bool) -> list[CaseResult]:
    out: list[CaseResult] = []
    for case in cases:
        try:
            passages = retrieve(
                conn,
                holding_id=case.holding_id if entity_scoped else None,
                measurement_date=case.measurement_date,
                requirement=case.requirement,
                k=MEASURED_K,
            )
        except RetrievalError:
            # A query that matches nothing is a real retrieval outcome and is
            # scored as a miss, not skipped. Skipping it would raise the recall
            # by shrinking its denominator, which is the one arithmetic mistake
            # that always flatters.
            passages = ()
        out.append(
            CaseResult(
                case=case,
                retrieved=tuple(dict.fromkeys(p.candidate.document_version_id for p in passages)),
            )
        )
    return out


def _recall(results: list[CaseResult], k: int) -> dict[str, Any]:
    documents = sum(len(r.retrieved[:k]) for r in results)
    cases = len(results)
    return {
        "k": k,
        "cases": cases,
        "found_some_relied_on": sum(1 for r in results if r.hit(k)),
        "found_every_relied_on": sum(1 for r in results if r.complete(k)),
        # Both counts, and the mean they produce. The mean is the readable form
        # and the browser may not divide (SPEC §5.3); the counts are what lets a
        # reader check that it was divided correctly.
        "candidate_documents": documents,
        "mean_candidates_per_case": (documents / cases) if cases else 0.0,
    }


def _misses(
    results: list[CaseResult], *, k: int, scope: str, names: dict[str, str]
) -> list[dict[str, Any]]:
    """Every case where nothing the ledger relies on was retrieved.

    Named, not counted. "Recall@1 is 39/40" is a score; "the miss is Lucra's
    existence-and-cost at 25Q4, where the rerank puts the October 2025 CEO email
    above the May 2024 term sheet the ledger relies on" is a finding, and it is
    worth more than the score.
    """
    return [
        {
            "scope": scope,
            "k": k,
            "holding_id": r.case.holding_id,
            "company_name": names.get(r.case.holding_id, r.case.holding_id),
            "requirement": r.case.requirement.value,
            "measurement_date": r.case.measurement_date.isoformat(),
            "relied_on": sorted(r.case.relevant),
            "retrieved": list(r.retrieved[:k]),
        }
        for r in results
        if not r.hit(k)
    ]


def _corpus(conn: Conn) -> dict[str, int]:
    row = conn.execute(
        "select (select count(*) from holding), (select count(*) from company),"
        " (select count(*) from document_version), (select count(*) from claim),"
        " (select count(*) from extracted_fact),"
        " (select count(*) from reporting_period where audit_scope = 'packet')"
    ).fetchone()
    assert row is not None
    keys = ("holdings", "companies", "documents", "claims", "facts", "packet_periods")
    return {key: _as(int, value) for key, value in zip(keys, row, strict=True)}


def _citations(conn: Conn) -> dict[str, Any]:
    """Every stored citation, re-resolved against the text it points into.

    `0008_citations_resolve.sql` enforces the same equality on write, so this is
    expected to be total — and it is measured anyway, because "a constraint
    exists" and "the rows satisfy it now" are different statements, and a
    migration applied to one schema and not another is exactly how they come
    apart.

    What this does NOT measure is whether the resolving quote is the RIGHT
    passage. That is stated in `not_measured` rather than left for a reader to
    infer from a number that looks complete.
    """
    rows = conn.execute(
        "select f.id, f.claim_id, f.field_name, f.citation_quote, f.span_start, f.span_end,"
        "       d.id, d.canonical_text"
        "  from extracted_fact f"
        "  join claim c on c.id = f.claim_id"
        "  join document_version d on d.id = c.document_version_id"
        " order by f.id"
    ).fetchall()
    failures: list[dict[str, Any]] = []
    resolving = 0
    for row in rows:
        text = _as(str, row[7])
        # `from_stored`, not `Citation(...)`. The arch rule allows no exceptions:
        # `span_start=` appears nowhere outside `packages/contracts/citations.py`,
        # and a rule with one carve-out for "the reader, which is fine" is a rule
        # whose next carve-out is an extractor that also looked fine.
        #
        # WITHOUT `canonical_text`, deliberately. Supplying it makes `from_stored`
        # VERIFY, which raises — and a census that raised on the first bad
        # citation could only ever report zero failures or no answer at all. The
        # measurement is `resolves_in`, which returns the answer instead.
        citation = from_stored(
            document_version_id=_as(str, row[6]),
            quote=_as(str, row[3]),
            span=(_as(int, row[4]), _as(int, row[5])),
        )
        if resolves_in(citation, text):
            resolving += 1
        else:
            failures.append(
                {
                    "fact_id": _as(int, row[0]),
                    "claim_id": _as(str, row[1]),
                    "field_name": _as(str, row[2]),
                    "document_version_id": citation.document_version_id,
                    # `chars`, not two keys named after the columns. The arch
                    # rule flags the NAMES wherever they appear, including as
                    # dict keys — and it is right to be that blunt: a payload
                    # shaped exactly like a citation's constructor arguments is
                    # one copy-paste from being one. This is also the auditor's
                    # own unit, and the same one `OffsetLabel` already renders.
                    "chars": [citation.span_start, citation.span_end],
                }
            )
    return {"total": len(rows), "resolving": resolving, "failures": failures}


def _stored_document(conn: Conn, text_hash: str) -> ParsedDocument | None:
    """Rebuild the parsed document from the LEDGER, not from the corpus.

    The corpus is gitignored and is absent from CI and from the deployed
    service, so a replay that read the file would report "not measured" on every
    host that matters. The stored `canonical_text` is the same text the fixture
    was recorded against — the recording is keyed by its hash — and it is also
    the text every citation resolves into, so binding against it is a stricter
    check than binding against a freshly parsed file would be.
    """
    # `left(...)` because the argument is the PREFIX the fixture filename
    # carries — `evidence.extract.fixture_path` keys on `text_hash[:16]` — while
    # the column holds the whole digest. Comparing the two directly matched
    # nothing and reported "no such document", which reads as a corpus problem
    # and was a join written against the wrong end of a string.
    row = conn.execute(
        "select d.id, d.canonical_text, d.extractor, d.text_hash,"
        "       s.filename, s.bytes, s.content_hash, s.byte_size"
        "  from document_version d join source_file s on s.id = d.source_file_id"
        " where left(d.text_hash, %s) = %s",
        (len(text_hash), text_hash),
    ).fetchone()
    if row is None:
        return None
    text = _as(str, row[1])
    return ParsedDocument(
        filename=_as(str, row[4]),
        source_bytes=_as(bytes, row[5]),
        content_hash=_as(str, row[6]),
        byte_size=_as(int, row[7]),
        canonical_text=text,
        extractor=_as(str, row[2]),
        text_hash=_as(str, row[3]),
        pages=split_pages(text),
    )


def _extraction(conn: Conn) -> dict[str, Any]:
    """The recorded model call, replayed and re-bound. Never a live call.

    CI has no key and must not need one, and a page that made a request to a
    model would report a different number every time it was opened.

    The finding is the REFUSALS. The model proposed five figures on the Lucra
    CEO email and the citation binding accepted three; one of the two it refused
    was the price the claim is priced from, because the quoted passage ends in a
    comma and the value could not be read as a whole figure inside it. That is
    the guardrail firing, and it belongs here as a result rather than as a fault.
    """
    fixture_hash = _fixture_text_hash()
    if fixture_hash is None:
        return {"measured": False, "why": "no extraction fixture is recorded"}
    parsed = _stored_document(conn, fixture_hash)
    if parsed is None:
        return {
            "measured": False,
            "why": (
                "the ledger holds no document version matching the recorded fixture's text, "
                "so there is nothing to re-bind the model's quotes against"
            ),
        }
    try:
        extraction = extract_from_fixture(
            document_version_id=f"dv_{parsed.text_hash[:24]}", parsed=parsed, stem=EXTRACTION_STEM
        )
    except (FixtureMissing, ExtractionRefused) as exc:
        return {"measured": False, "why": str(exc)}
    return {
        "measured": True,
        "document": parsed.filename,
        "model": extraction.model_served,
        "provider": extraction.provider_served,
        "replayed_from_recording": True,
        "proposed": len(extraction.facts) + len(extraction.refusals),
        "accepted": len(extraction.facts),
        "accepted_fields": [f.field_name for f in extraction.facts],
        "refused": [
            {"field_name": r.field_name, "value_text": r.value_text, "reason": r.reason}
            for r in extraction.refusals
        ],
    }


def _fixture_text_hash() -> str | None:
    """The text the one recorded extraction was made against.

    Read off the fixture's filename rather than out of its body: the name is
    what `evidence.extract.fixture_path` keys on, so reading it here means this
    page cannot disagree with the module about which recording is current.
    """
    from evidence.extract import FIXTURES

    recordings = sorted(FIXTURES.glob(f"{EXTRACTION_STEM}.*.json"))
    if not recordings:
        return None
    return recordings[-1].stem.rsplit(".", 1)[-1]


def _validators(
    packets: dict[str, Packet], recomputed: dict[str, dict[str, Recomputation]]
) -> dict[str, Any]:
    """SPEC §8's V2 over every holding-date the packets carry.

    A census of outcomes and not a pass rate: `not_comparable` is not a soft
    fail and `unconfirmable` is not a weak pass, so a single ratio over the six
    would be a number with no meaning. The disagreements are named for the same
    reason the retrieval misses are.
    """
    census: dict[str, int] = {}
    disagreements: list[dict[str, Any]] = []
    rows = 0
    for period_id, packet in packets.items():
        for holding_id, got in recomputed[period_id].items():
            rows += 1
            census[got.outcome.value] = census.get(got.outcome.value, 0) + 1
            # A disagreement needs both figures AND the outcome that says they
            # disagree. `not_comparable` carries two equal figures and is not a
            # finding of this kind; a fail with a figure missing is a bug in the
            # recomputation rather than a discrepancy in the fund's records.
            if got.outcome is Outcome.FAIL and None not in (
                got.derived,
                got.reported,
                got.difference,
            ):
                assert got.reported is not None and got.derived is not None
                assert got.difference is not None
                disagreements.append(
                    {
                        "holding_id": holding_id,
                        "company_name": _company_of(packet, holding_id),
                        "measurement_date": packet.period.period_date.isoformat(),
                        "reported": got.reported.model_dump(mode="json"),
                        "derived": got.derived.model_dump(mode="json"),
                        "difference": got.difference.model_dump(mode="json"),
                        "reason": got.reason,
                    }
                )
    return {"holding_dates": rows, "outcomes": census, "disagreements": disagreements}


def _company_of(packet: Packet, holding_id: str) -> str:
    found = next((r for r in packet.rows if r.holding_id == holding_id), None)
    return holding_id if found is None else found.company_name


def _by_holding(
    conn: Conn,
    packets: dict[str, Packet],
    recomputed: dict[str, dict[str, Recomputation]],
    citations: dict[str, Any],
) -> list[dict[str, Any]]:
    """One row per holding. This is where Because Market reads zero.

    Not hidden and not footnoted: one of fourteen positions, three measurement
    dates, no document of any kind. A page that buried its worst row is a page a
    reader should discount entirely.
    """
    counts = {
        _as(str, r[0]): {
            "documents": _as(int, r[1]),
            "claims": _as(int, r[2]),
            "facts": _as(int, r[3]),
        }
        for r in conn.execute(
            "select h.id, count(distinct c.document_version_id), count(distinct c.id),"
            "       count(f.id)"
            "  from holding h"
            "  left join claim c on c.holding_id = h.id"
            "  left join extracted_fact f on f.claim_id = c.id"
            " group by h.id"
        ).fetchall()
    }
    # WHOSE failing citation it is, read from the claim's own `holding_id`
    # rather than inferred from the shape of its id.
    #
    # This counted `claim_id.startswith(holding_id)`. Claim ids happen to be
    # prefixed by their holding today, so the count is right today — and it is
    # right by coincidence of naming, not by anything the database enforces. Two
    # holdings where one id is a prefix of the other (`fund_i_jio` beside
    # `fund_i_jio_indirect`) would attribute the longer one's failures to both,
    # and a claim id that stopped carrying the prefix would attribute its
    # failures to NOBODY — the page would read clean while a citation was
    # broken, which is the direction that matters.
    holding_of = {
        _as(str, r[0]): _as(str, r[1])
        for r in conn.execute("select id, holding_id from claim").fetchall()
    }
    failing_by_holding: dict[str, int] = {}
    for f in citations["failures"]:
        owner = holding_of.get(_as(str, f["claim_id"]))
        if owner is not None:
            failing_by_holding[owner] = failing_by_holding.get(owner, 0) + 1
    out: list[dict[str, Any]] = []
    for holding_id, tally in sorted(counts.items()):
        appearances = [
            (period_id, row)
            for period_id, packet in packets.items()
            for row in packet.rows
            if row.holding_id == holding_id
        ]
        sufficient = sum(
            1
            for _, row in appearances
            for a in row.assessments
            if a.verdict is RequirementVerdict.SUFFICIENT
        )
        applicable = sum(1 for _, row in appearances for a in row.assessments if a.applicable)
        census: dict[str, int] = {}
        for period_id, _ in appearances:
            got = recomputed[period_id].get(holding_id)
            if got is not None:
                census[got.outcome.value] = census.get(got.outcome.value, 0) + 1
        name = next((row.company_name for _, row in appearances), holding_id)
        out.append(
            {
                "holding_id": holding_id,
                "company_name": name,
                "documents": tally["documents"],
                "claims": tally["claims"],
                "facts": tally["facts"],
                "facts_with_a_failing_citation": failing_by_holding.get(holding_id, 0),
                "packet_appearances": len(appearances),
                "requirements_applicable": applicable,
                "requirements_sufficient": sufficient,
                "recomputation_outcomes": census,
            }
        )
    return out


#: What this page does NOT measure, said out loud.
#:
#: The last item of handoff 7a, and the one that decides whether a reader
#: believes the rest. Each entry names where the measurement DOES happen, so a
#: gap is a pointer rather than an apology.
NOT_MEASURED: tuple[dict[str, str], ...] = (
    {
        "what": "Whether the packet agrees with the independent oracle derivation",
        "why": (
            "The product is not permitted to see its own answer key. "
            "tests/test_gate_guards.py refuses any reference to the oracle snapshot from "
            "api/, policy/ and packet/, by import OR by file read — so a route that "
            "reported its own agreement with it would be the exact thing that guard "
            "exists to prevent."
        ),
        # The command names the TESTS, not the snapshot. `tests/test_oracle.py`
        # regenerates the derivation and compares it; naming the snapshot's own
        # path here would put it in a product module as a string, which
        # `tests/test_policy_vs_oracle.py` refuses — and it is right to, because
        # a path held as a value is one line from being opened.
        "measured_by": (".venv/bin/python -m pytest tests/test_oracle.py tests/test_recompute.py"),
    },
    {
        "what": "Whether a citation that resolves is the RIGHT passage",
        "why": (
            "Everything on this page verifies that the stored offsets select the stored "
            "quote. That proves the offsets and the quote agree WITH EACH OTHER. An "
            "exporter can select a real but wrong passage and remain internally "
            "consistent, and nothing here would notice."
        ),
        "measured_by": (
            "a hand transcription of the corpus made WITHOUT reading the extractors, "
            "checked by the suite. Until it lands this is an open blind spot and is "
            "reported as one."
        ),
    },
    {
        "what": "Whether the declared figure-to-requirement map is correct",
        "why": (
            "ingest/documents/field_requirements.py is a reviewed judgement, not a "
            "measurement. The guards prove every extracted figure is DECLARED and that "
            "an undeclared one is refused; no ground truth says the declarations are "
            "right."
        ),
        "measured_by": "human review of the map itself",
    },
    {
        "what": "Whether every guard in the suite can actually fail",
        "why": (
            "A test that passes because it measures nothing is this project's most "
            "expensive recurring defect. Mutation coverage answers it and cannot be "
            "computed inside a request: it moves the corpus out of the tree and edits "
            "sources in place."
        ),
        "measured_by": "REQUIRE_DB_TESTS=1 .venv/bin/python scripts/mutate.py",
    },
    {
        "what": "Retrieval quality against anything but the ledger's own reliance",
        "why": (
            "The gold set is read out of claim_requirement — the table recording which "
            "requirement each document is relied upon for. So this measures whether "
            "retrieval finds what the ledger already relies on, not whether the ledger "
            "relies on the right documents."
        ),
        "measured_by": "ingest/documents/reliance.py, which is a reviewed judgement",
    },
)


def evals(
    conn: Conn,
    ledger: Ledger,
    packets: dict[str, Packet],
    *,
    measured_at: datetime | None = None,
) -> dict[str, Any]:
    """Every figure on the evaluation page, measured now.

    Takes the ledger and the packets rather than reading them, so the route pays
    for `policy/from_ledger.py::load` once and this function is exercisable
    without a route.
    """
    cases = gold_cases(conn)
    scoped = _measure(conn, cases, entity_scoped=True)
    blind = _measure(conn, cases, entity_scoped=False)
    names = {row.holding_id: row.company_name for packet in packets.values() for row in packet.rows}
    recomputed = {period_id: for_packet(ledger, packet) for period_id, packet in packets.items()}
    citations = _citations(conn)
    return {
        "measured_at": (measured_at or datetime.now(UTC)).isoformat(),
        "corpus": _corpus(conn),
        "retrieval": {
            "gold_cases": len(cases),
            "retrievals_run": len(scoped) + len(blind),
            "k_reported": list(REPORTED_K),
            "scoped": {f"k{k}": _recall(scoped, k) for k in REPORTED_K},
            "blind": {f"k{k}": _recall(blind, k) for k in REPORTED_K},
            "misses": [
                *_misses(blind, k=MEASURED_K, scope="blind", names=names),
                *_misses(scoped, k=MEASURED_K, scope="scoped", names=names),
                *_misses(scoped, k=1, scope="scoped", names=names),
            ],
        },
        "citations": citations,
        "extraction": _extraction(conn),
        "validators": _validators(packets, recomputed),
        "by_holding": _by_holding(conn, packets, recomputed, citations),
        "not_measured": [dict(entry) for entry in NOT_MEASURED],
    }
