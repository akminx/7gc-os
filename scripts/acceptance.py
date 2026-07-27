#!/usr/bin/env python3
"""Check this system against Harwell & Kent's letter, request by request, by name.

Everything else here is measured against `evals/oracle/derived.json` — whether
the code agrees with an independent derivation of the same rules. Nothing asked
the other question: the client wrote four numbered requests and two asides, and
which of them does the system actually answer?

That absence has already cost something specific. ¶1 asks for existence and cost
"including share counts, price per share, **and settlement of funds**", and the
settlement limb went unanswered until two reviewers found it from opposite
directions on the same afternoon. Nothing was wrong with the code. The rule that
would have caught it is the one nobody had written down: measure a step against
the audit letter, not against itself.

    .venv/bin/python scripts/acceptance.py                # the full report
    .venv/bin/python scripts/acceptance.py --schema demo  # a named ledger schema

**Limbs, not requests.** A request is checked in the pieces the client wrote it
in. Treating ¶1 as one thing is exactly how its third limb disappeared: R1 was
answered, the row read `sufficient`, and "settlement of funds" was a clause
nobody had turned into anything that could be absent.

**The quotes are resolved, not typed.** Each limb declares a fragment of the
letter, and the fragment is looked up in the letter's own text at run time; one
that matches no line — or more than one — refuses the whole report. So a limb
cannot outlive the sentence it rests on, which is the rule
`ingest/policy_seed.py` already applies to declared gaps.

**Three outcomes, and only one of them is this system's fault.**

* A position with no evidence for a limb is a GAP IN THE CORPUS. Reported,
  never failed on: this corpus carries sixteen declared gaps and one holding
  with no documents at all, and that is the honest state of a fund's records.
* A limb NO position answers, in a vocabulary the ledger does have, is the
  fund's records saying no — management has written no basis memo and no
  representativeness assessment, and the packet's own next actions already ask
  for both. Printed loudly, exit 0, and `--strict` fails on it.
* A limb whose artefact the ledger has NO VOCABULARY FOR is a defect HERE.
  Nothing the fund could send would answer it, because there is nowhere to
  write it down. That is the settlement limb's shape, it is the one worth
  building this for, and it is what exits non-zero.

The split matters because the fixes are different — one is a request to make of
the fund, the other is a change to the schema — and because a signal that is
always red is one people learn to skip.

**What this is not.** It reads the ledger, so it reports what the fund would
hand the auditor, not what the oracle believes. It does not check that a
resolving citation is the RIGHT passage, and it does not decide sufficiency —
that is the policy layer's verdict, checked against the oracle elsewhere. The
closing section states these rather than leaving a reader to assume either way.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LETTER = ROOT / (
    "7GC Audit Case Study/00_Audit Request/"
    "Harwell & Kent LLP - 7GC Fund II FY2023-FY2025 Audit - Valuation Support Request.pdf"
)

Conn = psycopg.Connection[tuple[object, ...]]

#: Scopes. The letter asks for ¶1 and ¶4 about a POSITION and ¶2 and ¶3 about a
#: position AT a measurement date, so the denominators differ and are not a
#: detail: demanding support at a date a position was not held is a defect this
#: project has already shipped once, in the packet's own reasons list.
BY_POSITION = "position"
BY_POSITION_DATE = "position_date"
BY_REALISATION = "realisation"


class AcceptanceError(Exception):
    """The report cannot be produced, and producing part of one would mislead."""


@dataclass(frozen=True)
class Limb:
    """One clause of one request, and what in the ledger would answer it.

    Two dimensions, because the letter asks in two registers. "Executed
    transaction documents" is about WHAT KIND OF DOCUMENT the support is, and
    `source_class` is where the ledger records that. "Share counts, price per
    share, and settlement of funds" is about WHICH FIGURES the document states,
    and `extracted_fact.field_name` is where the ledger records those.

    Checking the second where the letter asked the first is how a limb reads as
    answered while nothing answers it: a purchase agreement states an
    `agreement_date`, and so does a term sheet that was never executed.

    Where both are declared they are a CONJUNCTION — ¶2's "pro forma
    capitalization table evidencing price per share" is a class and a figure,
    and the qualifier is load-bearing under the owner's ruling. Within one
    dimension the members are alternatives.

    This map is written from the letter's words and owes nothing to
    `ingest/documents/field_requirements.py`, which maps the same field
    vocabulary onto R1-R5. Two independent readings of one letter; where they
    disagree that is a finding rather than a merge conflict.
    """

    key: str
    text: str
    #: A fragment of the letter, matched at run time with whitespace flattened.
    #: Short on purpose: long enough to be unique, short enough that reflowing a
    #: paragraph does not silently drop the limb.
    fragment: str
    scope: str
    classes: frozenset[str] = frozenset()
    fields: frozenset[str] = frozenset()
    #: `review_decision.decision_type`. The letter's two requests for a document
    #: MANAGEMENT writes — ¶2's basis memo and ¶3(b)'s representativeness
    #: assessment — are not source documents at all: nobody sends them to the
    #: fund, the fund produces them, and the ledger records them as decisions
    #: bound to the mark they concern.
    #:
    #: The first version of this file declared them as source classes, found no
    #: such class, and reported that the system could not express them. It can.
    #: One `review_decision` row of type `management_assessment` is the artefact,
    #: and the corpus holds none — which is a request to make of the fund rather
    #: than a change to the schema, and the two must not be confused.
    decisions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.classes and not self.fields and not self.decisions:
            raise AcceptanceError(
                f"limb {self.key} declares no evidence at all. A limb that asks for"
                " nothing is answered by everything, which is the failure this file exists"
                " to find one level up."
            )


#: ¶1. The document, then the three figures the letter names inside it. The
#: third is the one that went missing, and it is separate here because the
#: client wrote it as separate.
PARA_1 = (
    Limb(
        "1a",
        "executed transaction documents supporting the acquisition",
        "Executed transaction documents supporting the Fund's acquisition",
        BY_POSITION,
        classes=frozenset({"executed_transaction_doc"}),
    ),
    Limb(
        "1b",
        "share counts",
        "including share counts",
        BY_POSITION,
        fields=frozenset(
            {
                "fund_shares",
                "schedule_a_total_shares",
                "shares_held",
                "fund_series_a_shares",
                "fund_series_a2_shares",
                "fund_a3_shares",
                "fund_prior_shares",
                "position_shares",
            }
        ),
    ),
    Limb(
        "1c",
        "price per share",
        "price per share, and settlement of funds",
        BY_POSITION,
        fields=frozenset(
            {
                "fund_price_per_share",
                "fund_entry_price_per_share",
                "fund_series_a_original_pps",
                "fund_series_a2_original_pps",
                "original_purchase_pps",
            }
        ),
    ),
    Limb(
        "1d",
        "settlement of funds",
        "and settlement of funds",
        BY_POSITION,
        fields=frozenset({"settlement_amount_received", "settlement_date", "settlement_reference"}),
    ),
)

#: ¶2. Branch A is a DISJUNCTION the letter writes as "or", so its two arms are
#: two rows: a holding supported by a pro-forma table rather than by executed
#: documents is a fact an auditor wants stated, not averaged away. Branch B is a
#: CONJUNCTION the letter writes as "and", and its second half is the one the
#: corpus has never held.
PARA_2 = (
    Limb(
        "2a",
        "round-based marks · the round's executed documents",
        "For marks based on a financing round: the round's executed documents",
        BY_POSITION_DATE,
        classes=frozenset({"executed_transaction_doc"}),
    ),
    Limb(
        "2b",
        "round-based marks · or a pro forma cap table evidencing price per share",
        "pro forma capitalization table evidencing price per share",
        BY_POSITION_DATE,
        classes=frozenset({"company_cap_table"}),
        fields=frozenset(
            {
                "round_price_per_share",
                "series_a2_price_per_share",
                "series_a3_price_per_share",
                "series_b_price_per_share",
            }
        ),
    ),
    Limb(
        "2c",
        "other-information marks · the underlying source",
        "For marks based on other information: the underlying source",
        BY_POSITION_DATE,
        classes=frozenset(
            {
                "third_party_valuation_memo",
                "administrator_statement",
                "public_market_quote",
                "press",
                "fund_internal_record",
                "company_communication",
            }
        ),
    ),
    Limb(
        "2d",
        "other-information marks · and management's memo describing the basis",
        "management's memo describing the basis of the mark",
        BY_POSITION_DATE,
        decisions=frozenset({"management_assessment"}),
    ),
)

#: ¶3. Limb (b) is a REQUEST owed at every subsequent measurement date; the
#: twelve-month calibration in the closing paragraph is a RECOMMENDATION. The
#: letter separates them by verb — "please provide" against "we recommend" — so
#: they are two rows and not one predicate serving both.
PARA_3 = (
    Limb(
        "3a",
        "the documentation of that most recent round",
        "the documentation of that most recent round",
        BY_POSITION_DATE,
        classes=frozenset({"executed_transaction_doc", "company_cap_table"}),
    ),
    Limb(
        "3b",
        "management's assessment at each subsequent measurement date",
        "management's assessment that the last round price remains representative",
        BY_POSITION_DATE,
        decisions=frozenset({"management_assessment"}),
    ),
)

#: ¶4.
PARA_4 = (
    Limb(
        "4a",
        "merger consideration statements, distribution notices, or other support",
        "Merger consideration statements, distribution notices",
        BY_REALISATION,
        classes=frozenset({"executed_transaction_doc", "administrator_statement"}),
    ),
    Limb(
        "4b",
        "per-share consideration",
        "including per-share consideration",
        BY_REALISATION,
        fields=frozenset({"consideration_per_share", "consideration_per_share_stated"}),
    ),
    Limb(
        "4c",
        "share counts of the realised position",
        "per-share consideration and share counts",
        BY_REALISATION,
        fields=frozenset({"shares_of_record"}),
    ),
)

#: The two asides, both requests in the client's own voice. The first is why a
#: pro-forma cap table does not have to be held at `partial` to get the
#: disclosure made — support and disclosure are two obligations, and R5 carries
#: the second.
ASIDES = (
    Limb(
        "5",
        "identify positions marked on a pro forma basis pending executed documentation",
        "identify any positions marked on a pro forma basis pending receipt of executed",
        BY_POSITION_DATE,
        fields=frozenset({"executed_docs_pending", "executed_docs_location", "closing_set_status"}),
    ),
    Limb(
        "6",
        "calibration assessment for unchanged marks over twelve months",
        "calibration assessment for positions held at an unchanged mark for more than twelve",
        BY_POSITION_DATE,
        decisions=frozenset({"management_assessment"}),
    ),
)

REQUESTS: tuple[tuple[str, str, tuple[Limb, ...]], ...] = (
    ("¶1", "Existence and cost", PARA_1),
    ("¶2", "Fair value support as of each measurement date", PARA_2),
    ("¶3", "Unchanged marks", PARA_3),
    ("¶4", "Realized investments", PARA_4),
    ("closing", "The two asides", ASIDES),
)

LIMBS: tuple[Limb, ...] = tuple(limb for _, _, limbs in REQUESTS for limb in limbs)


def letter_text() -> str:
    """The letter, read with the same extractor the corpus uses.

    Not a transcription. The fragments above are checked against this, so the
    report is anchored to the client's file rather than to someone's memory of
    it — and if the file is absent that is a refusal, not a report with the
    checking quietly switched off.
    """
    if not LETTER.exists():
        raise AcceptanceError(
            f"the audit letter is not in the tree:\n  {LETTER.relative_to(ROOT)}\n"
            "  It is a fund's private case-study material and is gitignored, so this\n"
            "  report cannot run in CI. That is deliberate: every quote below is\n"
            "  resolved against the letter, and a run without it would check nothing."
        )
    from ingest.documents.parse import parse

    return parse(LETTER).canonical_text


def resolve_fragments(text: str) -> None:
    """Every declared fragment appears in the letter exactly once, or nothing runs.

    The failure this prevents is a quotation that has drifted from its source: a
    limb still checked, still printed, and no longer describing anything the
    client wrote. `ingest/policy_seed.py` applies the same rule to the sentences
    its declared gaps rest on, for the same reason.

    Whitespace is flattened on both sides first. `pdftotext` wraps the letter at
    the page width, so "share counts, price per share, and settlement of funds"
    is split across two lines in the file and matches nothing as written.
    """
    flat = " ".join(text.split())
    problems = [
        f"{limb.key}: {flat.count(' '.join(limb.fragment.split()))} matches for {limb.fragment!r}"
        for limb in LIMBS
        if flat.count(" ".join(limb.fragment.split())) != 1
    ]
    if problems:
        raise AcceptanceError(
            "these quotations no longer resolve against the letter:\n  " + "\n  ".join(problems)
        )


@dataclass
class Evidence:
    """What the ledger holds, indexed the way the limbs ask about it."""

    holdings: dict[str, str] = field(default_factory=dict)
    dates: tuple[str, ...] = ()
    #: The vocabularies the ledger actually has. A limb asking for something
    #: absent from these cannot be answered by any corpus, which is a different
    #: and worse finding than a corpus that happens not to contain one.
    known_classes: frozenset[str] = frozenset()
    known_fields: frozenset[str] = frozenset()
    known_decisions: frozenset[str] = frozenset()
    classes_by_position: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    fields_by_position: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    classes_by_date: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    fields_by_date: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    decisions_by_position: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    decisions_by_date: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    held: set[tuple[str, str]] = field(default_factory=set)
    realised: set[str] = field(default_factory=set)


def read_ledger(conn: Conn) -> Evidence:
    """One pass over the ledger. Six queries, not six hundred."""
    ev = Evidence()
    ev.holdings = {
        str(h): str(c) for h, c in conn.execute("select id, company_id from holding").fetchall()
    }
    ev.dates = tuple(
        str(d)
        for (d,) in conn.execute(
            "select distinct period_date from reporting_period"
            " where audit_scope = 'packet' order by 1"
        ).fetchall()
    )
    # The ENUM, not the values in use. "No document in this corpus is a
    # management memo" and "this ledger has no way to record one" are different
    # answers to the client, and only the declared type can tell them apart.
    ev.known_classes = frozenset(
        str(c) for (c,) in conn.execute("select unnest(enum_range(null::source_class))::text")
    )
    ev.known_fields = frozenset(
        str(f) for (f,) in conn.execute("select distinct field_name from extracted_fact")
    )
    ev.known_decisions = frozenset(
        str(d) for (d,) in conn.execute("select unnest(enum_range(null::decision_type))::text")
    )

    for h, cls, fname in conn.execute(
        "select c.holding_id, c.source_class::text, x.field_name"
        " from claim c left join extracted_fact x on x.claim_id = c.id"
    ).fetchall():
        ev.classes_by_position[str(h)].add(str(cls))
        if fname is not None:
            ev.fields_by_position[str(h)].add(str(fname))
    # A claim's reliance window is what makes evidence available AT a date:
    # `applicable_from`/`applicable_to` are why a term sheet supports 24Q4 while
    # a closing notice issued later does not support the date before it existed.
    for h, d, cls, fname in conn.execute(
        "select c.holding_id, p.period_date, c.source_class::text, x.field_name"
        " from claim c"
        " join holding h on h.id = c.holding_id"
        " join reporting_period p on p.fund_id = h.fund_id and p.audit_scope = 'packet'"
        " left join extracted_fact x on x.claim_id = c.id"
        " where (c.applicable_from is null or c.applicable_from <= p.period_date)"
        "   and (c.applicable_to is null or c.applicable_to >= p.period_date)"
    ).fetchall():
        ev.classes_by_date[(str(h), str(d))].add(str(cls))
        if fname is not None:
            ev.fields_by_date[(str(h), str(d))].add(str(fname))
    # INV-7's rule, and it is `api/ledger.py`'s rather than a second one written
    # here: acquired on or before the measurement date and not realised by it.
    # `mark` carries no `held_at_date` column — it is derived from the lots, and
    # a report that invented its own definition could disagree with the packet
    # about which positions the letter even covers.
    for h, d in conn.execute(
        "select h.id, p.period_date from holding h"
        " join reporting_period p on p.fund_id = h.fund_id and p.audit_scope = 'packet'"
        " join lot l on l.holding_id = h.id"
        " where l.acquired_date <= p.period_date"
        "   and (l.realized_date is null or l.realized_date > p.period_date)"
        " group by 1, 2"
    ).fetchall():
        ev.held.add((str(h), str(d)))
    # A management assessment is not a source document: it is a decision the
    # fund records against the mark it concerns, approved or not. `status` is
    # deliberately not filtered — a drafted assessment still answers "has anyone
    # written one", and reporting only approved ones would make this report
    # about the approval workflow rather than about the client's request.
    for h, d, kind in conn.execute(
        "select m.holding_id, p.period_date, r.decision_type::text"
        " from review_decision r"
        " join mark m on m.id = r.mark_id"
        " join reporting_period p on p.id = m.period_id"
    ).fetchall():
        ev.decisions_by_position[str(h)].add(str(kind))
        ev.decisions_by_date[(str(h), str(d))].add(str(kind))
    ev.realised = {
        str(h)
        for (h,) in conn.execute(
            "select distinct holding_id from lot where realized_date is not null"
        ).fetchall()
    }
    return ev


def unspeakable(limb: Limb, ev: Evidence) -> list[str]:
    """What this limb asks for that the ledger has no vocabulary for.

    The check that would have caught the settlement limb a day earlier, and the
    one that stops a typo in the map above from reading as a corpus gap forever.
    A field name nothing writes and a source class the enum does not declare are
    the same finding: a clause of the letter with nowhere to land.
    """
    return sorted(
        [c for c in limb.classes if c not in ev.known_classes]
        + [f for f in limb.fields if f not in ev.known_fields]
        + [d for d in limb.decisions if d not in ev.known_decisions]
    )


def scope_of(limb: Limb, ev: Evidence) -> list[tuple[str, str | None]]:
    """Which positions, at which dates, this limb is owed for."""
    if limb.scope == BY_POSITION:
        return [(h, None) for h in sorted({h for h, _ in ev.held})]
    if limb.scope == BY_REALISATION:
        return [(h, None) for h in sorted(ev.realised)]
    return sorted(ev.held)


def answered(limb: Limb, ev: Evidence, holding: str, on: str | None) -> bool:
    """Every DECLARED dimension satisfied; alternatives within each."""
    if on is None:
        classes = ev.classes_by_position[holding]
        fields = ev.fields_by_position[holding]
        decisions = ev.decisions_by_position[holding]
    else:
        classes = ev.classes_by_date.get((holding, on), set())
        fields = ev.fields_by_date.get((holding, on), set())
        decisions = ev.decisions_by_date.get((holding, on), set())
    if limb.classes and not limb.classes & classes:
        return False
    if limb.fields and not limb.fields & fields:
        return False
    return not (limb.decisions and not limb.decisions & decisions)


@dataclass
class LimbResult:
    limb: Limb
    answered: list[tuple[str, str | None]]
    unanswered: list[tuple[str, str | None]]
    missing_vocabulary: list[str]

    @property
    def total(self) -> int:
        return len(self.answered) + len(self.unanswered)


def assess(ev: Evidence) -> dict[str, list[LimbResult]]:
    out: dict[str, list[LimbResult]] = {}
    for code, _, limbs in REQUESTS:
        results: list[LimbResult] = []
        for limb in limbs:
            yes: list[tuple[str, str | None]] = []
            no: list[tuple[str, str | None]] = []
            for holding, on in scope_of(limb, ev):
                (yes if answered(limb, ev, holding, on) else no).append((holding, on))
            results.append(LimbResult(limb, yes, no, unspeakable(limb, ev)))
        out[code] = results
    return out


def short(holding: str) -> str:
    return holding.removeprefix("fund_i_").removeprefix("fund_ii_")


def report(ev: Evidence, results: dict[str, list[LimbResult]]) -> list[str]:
    """The requests, in the client's order and the client's words."""
    lines = [
        "",
        "7GC OS · acceptance against the Harwell & Kent letter",
        f"  letter   {LETTER.name}",
        f"  ledger   {len(ev.holdings)} positions · {len(ev.dates)} measurement dates"
        f" ({', '.join(ev.dates)})",
        "",
        "Each request is checked in the limbs the client wrote it in. A position with no",
        "evidence for a limb is a gap in the CORPUS and is listed, never failed on.",
    ]
    for code, title, _ in REQUESTS:
        lines += ["", f"{code} · {title}", ""]
        for r in results[code]:
            if r.missing_vocabulary:
                mark = "!!"
            elif r.answered:
                mark = "  "
            else:
                mark = " ·"
            lines.append(f"  {mark} {r.limb.key:4} {r.limb.text}")
            if r.missing_vocabulary:
                lines.append(
                    f"          NOT EXPRESSIBLE — the ledger has no"
                    f" {', '.join(r.missing_vocabulary)}"
                )
                continue
            lines.append(f"          answered for {len(r.answered)}/{r.total}")
            if r.unanswered:
                names = sorted({short(h) for h, _ in r.unanswered})
                shown = ", ".join(names[:8]) + (" …" if len(names) > 8 else "")
                lines.append(f"          no evidence: {shown}")
    return lines


def by_company(ev: Evidence, results: dict[str, list[LimbResult]]) -> list[str]:
    """ "We would appreciate receiving the support organized by portfolio company."

    The letter's last request, and the only one about shape rather than content.
    It is answered by producing this table at all.
    """
    per: dict[str, set[str]] = defaultdict(set)
    for rs in results.values():
        for r in rs:
            for holding, _on in r.answered:
                per[holding].add(r.limb.key)
    lines = ["", "Support organised by portfolio company", ""]
    lines.append(f"  {'company':24} {'limbs':>5}   which")
    for holding in sorted(ev.holdings, key=short):
        keys = sorted(per.get(holding, set()))
        lines.append(f"  {short(holding):24} {len(keys):>5}   {', '.join(keys) or '—'}")
    return lines


NOT_MEASURED = """
What this report does NOT establish

  * That a resolving citation is the RIGHT passage. Every figure counted above
    resolves — the offsets and the quote agree — and nothing here proves the
    quote is the sentence stating the fact.
  * That a figure or document class declared to answer a limb is what an auditor
    would accept. The map from the letter's clauses to the ledger's vocabulary is
    a reviewed judgement, like `ingest/documents/reliance.py`, and it can be
    wrong in the ordinary way a judgement can.
  * Sufficiency. This counts whether a limb has evidence, not whether the
    evidence is enough. That is the policy layer's verdict and it is checked
    against the oracle, not here.
  * Anything about a position the ledger does not carry. A company with no
    documents reads as zero across every limb, which is the honest answer rather
    than a measurement failure.
"""


def closing(results: dict[str, list[LimbResult]], strict: bool) -> tuple[list[str], int]:
    """The two failing states, printed apart because the fix differs — and only
    one of them is this system's fault.

    UNANSWERABLE is a defect here: a clause of the letter with nowhere in the
    ledger to land, which nothing the fund sends could ever satisfy. It fails.

    UNANSWERED is the fund's records saying no. Management has written no basis
    memo and no representativeness assessment, and that is the true state of the
    engagement rather than a bug — the packet's own next actions already ask for
    both. Failing on it would make this command permanently red, and a signal
    that is always red is one people learn to skip, which is how the gate got
    into trouble once already. It is printed loudly and `--strict` fails on it,
    for anyone who wants the stricter contract.
    """
    every = [r for rs in results.values() for r in rs]
    unspoken = [r for r in every if r.missing_vocabulary]
    unanswered = [r for r in every if not r.missing_vocabulary and not r.answered]
    lines: list[str] = []
    if unspoken:
        lines += [
            "UNANSWERABLE — the letter asks for these and the ledger cannot record them.",
            "This is a defect in the system, not in the fund's records:",
            "",
        ]
        for r in unspoken:
            lines.append(f"  {r.limb.key:4} {r.limb.text}")
            lines.append(f'         "{" ".join(r.limb.fragment.split())}"')
            lines.append(
                f"         no {', '.join(r.missing_vocabulary)} in the ledger's vocabulary"
            )
        lines.append("")
    if unanswered:
        lines += [
            "UNANSWERED — the ledger can record these and no position in the corpus has one.",
            "This is the fund's records, and it is what the auditor is owed an answer about:",
            "",
        ]
        lines += [f"  {r.limb.key:4} {r.limb.text}  (0/{r.total})" for r in unanswered]
        lines.append("")
    if not unspoken and not unanswered:
        return (["Every limb of every request is answered for at least one portfolio company."], 0)
    lines.append(
        f"{len(unspoken) + len(unanswered)} of {len(every)} limbs go unanswered"
        f" — {len(unspoken)} unanswerable, {len(unanswered)} unanswered."
    )
    if unspoken or (strict and unanswered):
        return (lines, 1)
    lines.append("Exit 0: nothing above is a defect in this system. Use --strict to fail on them.")
    return (lines, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the system against the audit letter, request by request."
    )
    parser.add_argument("--schema", default=None, help="ledger schema; defaults to LEDGER_SCHEMA")
    parser.add_argument("--url", default=None, help="DSN; defaults to DATABASE_URL")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail when a limb the ledger CAN record has no evidence anywhere",
    )
    args = parser.parse_args(argv)

    from api.config import SchemaNameError, dsn, resolve_schema

    try:
        resolve_fragments(letter_text())
        schema = resolve_schema(args.schema)
        url = args.url or dsn("DATABASE_URL") or dsn("MIGRATION_DATABASE_URL")
        if not url:
            raise AcceptanceError("no DATABASE_URL — this reads the ledger and cannot infer one")
        with psycopg.connect(
            url, options=f"-c search_path={schema}", connect_timeout=10, prepare_threshold=None
        ) as conn:
            ev = read_ledger(conn)
    except (AcceptanceError, SchemaNameError) as exc:
        print(f"\nacceptance: {exc}", file=sys.stderr)
        return 1

    if not ev.held:
        print(f"\nacceptance: {schema} holds no positions — nothing to check", file=sys.stderr)
        return 1

    results = assess(ev)
    print("\n".join(report(ev, results)))
    print("\n".join(by_company(ev, results)))
    print(NOT_MEASURED)
    lines, code = closing(results, args.strict)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
