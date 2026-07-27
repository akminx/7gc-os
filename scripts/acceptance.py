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
  building this for, and it is what exits non-zero. A limb the ledger cannot
  tell APART from another one is the same finding wearing a different face, and
  it is the harder one to see: ¶2's basis memo, ¶3(b)'s representativeness
  assessment and the closing paragraph's calibration are three different
  documents management would write, and `review_decision.decision_type` has one
  value for all three. Three rows reading `0/34` looked like three findings. It
  is one signal reported three times, and until the schema separates them a
  memo answering any one of them answers all three.

The split matters because the fixes are different — one is a request to make of
the fund, the other is a change to the schema — and because a signal that is
always red is one people learn to skip.

**The letter is one fund's, and this ledger carries two.** `docs/SPEC.md`
applies the same categories to Fund I deliberately, so those five positions
stay. But the client wrote "our audits of 7GC Fund II, L.P.", and a report that
prints `capsule` where the ledger says `fund_i_capsule` hands the auditor a
denominator counting a fund the letter never asked about. Every count below is
split by fund and every name carries its own.

**¶2's two branches are conditional, and the ledger records no basis.** "For
marks based on a financing round: … For marks based on other information: …" —
`mark.basis` is NULL for every mark, so neither branch can be narrowed to the
marks it governs and both are scored against every held position-date. The
report says that where the numbers are. Inferring each mark's basis from the
evidence on file and then using it to decide which evidence is required would be
circular, and a true sentence beats a tidy number.

**What this is not.** It reads the ledger, so it reports what the fund would
hand the auditor, not what the oracle believes. It does not check that a
resolving citation is the RIGHT passage, and it does not decide sufficiency —
that is the policy layer's verdict, checked against the oracle elsewhere. The
closing section states these rather than leaving a reader to assume either way.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
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

#: The fund the letter is about — "In connection with our audits of 7GC Fund II,
#: L.P." — as the ledger's `holding.fund_id` spells it. The mapping from the
#: client's legal name to that id is the one judgement here that cannot be
#: resolved against either document: `fund.legal_name` in this ledger is the id
#: repeated, not "7GC Fund II, L.P.", so there is nothing to match on. It is
#: guarded instead of assumed — `check_fund_scope` refuses a report whose ledger
#: holds no position for it, which is what an id rename would look like.
LETTER_FUND = "fund_ii"

#: How the letter's fragment is checked, so the fund above is not a name typed
#: from memory any more than a limb's quotation is.
LETTER_FUND_FRAGMENT = "our audits of 7GC Fund II, L.P."

#: `holding.fund_id` -> what to call it in front of an auditor. An id absent
#: here prints as itself: a fund this report has never heard of must be visible,
#: not silently folded into the two it knows.
FUND_LABEL = {"fund_ii": "Fund II", "fund_i": "Fund I"}


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
    #:
    #: One value for three artefacts, though, and `unspeakable` reports that.
    decisions: frozenset[str] = frozenset()
    #: `claim.execution_status`. The closing paragraph's "marked on a pro forma
    #: basis" is a property of the ARTEFACT the mark rests on, and the schema has
    #: carried `pro_forma` as a status since 0001. Asking it of narrative fields
    #: instead is how a non-binding term sheet that names where the executed
    #: agreement lives — `executed_docs_location`, which
    #: `ingest/documents/extract_term_sheet.py` emits for a document that is not
    #: pro forma at all — reported a position as marked pro forma.
    statuses: frozenset[str] = frozenset()
    #: ¶3(b)'s parenthetical: "(including consideration of company performance,
    #: market conditions, and any indicators of impairment)". Three things the
    #: assessment must CONTAIN, not merely that one exists.
    #:
    #: Unbuildable until `0012`, and not for want of trying: while ¶2's basis
    #: memo, ¶3(b)'s assessment and the closing calibration were one enum value,
    #: the contents of a document could not be checked because the document
    #: could not be told from two others. `assessment_consideration_record`
    #: carries one row per consideration with the note that says what was
    #: considered, so an auditor reads the consideration rather than a checkbox.
    considerations: frozenset[str] = frozenset()
    #: This limb asks WHICH positions, not whether each position is supported.
    #:
    #: The closing paragraph's second aside is the only one: "please also
    #: identify any positions marked on a pro forma basis". Rendered like the
    #: others it reads `6/34` under "what the auditor is owed an answer about",
    #: and a fund with no pro-forma marks at all would read `0/34` — a clean
    #: record printed as a deficiency, which is backwards. A census is answered
    #: by naming its members, including when there are none.
    census: bool = False

    def __post_init__(self) -> None:
        if not (
            self.classes or self.fields or self.decisions or self.statuses or self.considerations
        ):
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
        # THE VOCABULARY OF THE DOCUMENT CLASS, not of the stock purchase
        # agreement alone. Named `settlement_amount_received` only, this limb
        # reported Jio as having no settlement evidence while its capital
        # account statement states `contributed_capital` against an unfunded
        # commitment of zero — the money having moved, said the way a fund
        # interest says it.
        #
        # Worse than a wrong count: `policy/requirements.py::_SETTLEMENT_EVIDENCE`
        # already accepted the wider set, so this report and the verdict layer
        # gave DIFFERENT answers to the same question about the same holding,
        # and both looked right. Two parts of one system disagreeing quietly is
        # the defect this whole project is built to make impossible; it is not
        # allowed to live in the file that measures the letter.
        fields=frozenset(
            {
                "settlement_amount_received",
                "settlement_date",
                "settlement_reference",
                "contributed_capital",
                "acquisition_consideration_usd",
            }
        ),
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
        decisions=frozenset({"basis_memo"}),
    ),
)

#: ¶3. Limb (b) is a REQUEST owed at every subsequent measurement date; the
#: twelve-month calibration in the closing paragraph is a RECOMMENDATION. The
#: letter separates them by verb — "please provide" against "we recommend" — so
#: they are two rows and not one predicate serving both.
#:
#: ¶3(b) NAMES ITS OWN CONTENTS AND NOTHING HERE CHECKS THEM. The letter asks
#: for management's assessment "(including consideration of company
#: performance, market conditions, and any indicators of impairment)" — three
#: things the assessment must contain, not merely that one exists.
#:
#: Not a limb, and deliberately not, because it cannot be one yet: 3b is already
#: UNANSWERABLE — the ledger records `management_assessment` and no more, so it
#: cannot tell this artefact from ¶2's basis memo or the closing calibration.
#: The contents of a document cannot be checked while the document itself is
#: indistinguishable from two others. Written down here so the clause is not
#: mistaken for covered when the schema gains a `decision_type` per artefact and
#: 3b becomes answerable — at which point this is the next thing to build, and
#: it needs somewhere to record what an assessment considered.
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
        decisions=frozenset({"representativeness"}),
    ),
    # ¶3(b)'S PARENTHETICAL, and three limbs rather than one for the reason ¶1's
    # figures are three: an assessment that considered market conditions and not
    # impairment has answered part of the request, and one limb would report
    # that as answering none of it.
    #
    # Separate from 3b, not folded into it, because "no assessment" and "an
    # assessment that considered nothing" are different findings with different
    # next actions — one asks the fund to write something, the other asks them to
    # widen what they already wrote.
    Limb(
        "3c",
        "the assessment considers company performance",
        "including consideration of company performance",
        BY_POSITION_DATE,
        considerations=frozenset({"company_performance"}),
    ),
    Limb(
        "3d",
        "the assessment considers market conditions",
        "market conditions",
        BY_POSITION_DATE,
        considerations=frozenset({"market_conditions"}),
    ),
    Limb(
        "3e",
        "the assessment considers any indicators of impairment",
        "any indicators of impairment",
        BY_POSITION_DATE,
        considerations=frozenset({"impairment_indicators"}),
    ),
)

#: ¶4. Four limbs, in the letter's order, and the second one is the sentence's
#: HEAD NOUN: the documents are support "for **proceeds received**", and
#: per-share consideration and share counts are what that support must include.
#: The first version of this tuple checked the document and the two included
#: figures and never the thing they are included in — ¶1's settlement limb
#: exactly, one paragraph along. `ingest/documents/field_requirements.py`
#: already declares `gross_consideration` and `net_payment` under R4, so the
#: ledger answers it; nothing was asking.
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
        "proceeds received",
        "other support for proceeds received",
        BY_REALISATION,
        fields=frozenset({"gross_consideration", "net_payment"}),
    ),
    Limb(
        "4c",
        "per-share consideration",
        "including per-share consideration",
        BY_REALISATION,
        fields=frozenset({"consideration_per_share", "consideration_per_share_stated"}),
    ),
    Limb(
        "4d",
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
#:
#: ¶5 is asked of `claim.execution_status` because that is where the fact lives.
#: Asked of the three narrative fields instead it counted The Mom Project, whose
#: only relevant figure is `executed_docs_location` on a summary of terms the
#: extractor records as `non_binding` — the executed agreement is with company
#: counsel, and a document that is not pro forma cannot make a mark pro forma.
#: `policy/requirements.py::r5` already derives the label from the relied-upon
#: statuses; this reads the same column rather than a second definition of it.
ASIDES = (
    Limb(
        "5",
        "identify positions marked on a pro forma basis pending executed documentation",
        "identify any positions marked on a pro forma basis pending receipt of executed",
        BY_POSITION_DATE,
        statuses=frozenset({"pro_forma"}),
        census=True,
    ),
    Limb(
        "6",
        "calibration assessment for unchanged marks over twelve months",
        "calibration assessment for positions held at an unchanged mark for more than twelve",
        BY_POSITION_DATE,
        decisions=frozenset({"calibration"}),
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
    # The fund is resolved on the same terms as a limb. Which positions the
    # letter covers is a claim about the letter, and a claim about the letter
    # that nothing checks is the failure this function exists for.
    declared = [(limb.key, limb.fragment) for limb in LIMBS]
    declared.append(("fund", LETTER_FUND_FRAGMENT))
    problems = [
        f"{key}: {flat.count(' '.join(fragment.split()))} matches for {fragment!r}"
        for key, fragment in declared
        if flat.count(" ".join(fragment.split())) != 1
    ]
    if problems:
        raise AcceptanceError(
            "these quotations no longer resolve against the letter:\n  " + "\n  ".join(problems)
        )


@dataclass
class Evidence:
    """What the ledger holds, indexed the way the limbs ask about it."""

    holdings: dict[str, str] = field(default_factory=dict)
    #: `holding.fund_id`, from the ledger rather than from the shape of the id.
    #: The two agree today; only one of them is a column, and a report that read
    #: the prefix would go on saying `Fund I` after a rename that moved the
    #: position.
    funds: dict[str, str] = field(default_factory=dict)
    dates: tuple[str, ...] = ()
    #: The vocabularies the ledger actually has. A limb asking for something
    #: absent from these cannot be answered by any corpus, which is a different
    #: and worse finding than a corpus that happens not to contain one.
    known_classes: frozenset[str] = frozenset()
    known_fields: frozenset[str] = frozenset()
    known_decisions: frozenset[str] = frozenset()
    known_statuses: frozenset[str] = frozenset()
    #: `mark.basis` — how many marks say what the mark is based on, of how many.
    #: ¶2 asks two different things of round-based and other-information marks,
    #: and with nothing recorded neither branch can be scoped to the marks it
    #: governs. Counted rather than inferred, and reported rather than fixed.
    marks_total: int = 0
    marks_with_basis: int = 0
    holdings_stating_basis: int = 0
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
    statuses_by_position: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    statuses_by_date: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    considerations_by_position: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    considerations_by_date: dict[tuple[str, str], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    known_considerations: frozenset[str] = frozenset()
    held: set[tuple[str, str]] = field(default_factory=set)
    realised: set[str] = field(default_factory=set)


def read_ledger(conn: Conn) -> Evidence:
    """One pass over the ledger. Six queries, not six hundred."""
    ev = Evidence()
    for h, company, fund in conn.execute("select id, company_id, fund_id from holding").fetchall():
        ev.holdings[str(h)] = str(company)
        ev.funds[str(h)] = str(fund)
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
    # The decision vocabulary is `decision_type` PLUS the kinds a management
    # assessment can declare itself to be. `0012` split that one value into
    # three because the letter asks for three different documents and this
    # ledger had one place to put them — so a fund writing only a basis memo
    # answered ¶2, ¶3(b) and the closing calibration at once, and no query could
    # say which it had actually written.
    ev.known_decisions = frozenset(
        str(d) for (d,) in conn.execute("select unnest(enum_range(null::decision_type))::text")
    ) | frozenset(
        str(k) for (k,) in conn.execute("select unnest(enum_range(null::assessment_kind))::text")
    )
    ev.known_considerations = frozenset(
        str(k)
        for (k,) in conn.execute("select unnest(enum_range(null::assessment_consideration))::text")
    )
    ev.known_statuses = frozenset(
        str(s) for (s,) in conn.execute("select unnest(enum_range(null::execution_status))::text")
    )
    # `basis` is counted, never read for a value. What ¶2 needs is the count:
    # whether the letter's two branches can be scoped at all. Through `str`
    # first for the reason every other value here is — the connection is typed
    # as rows of `object`.
    for total, with_basis in conn.execute("select count(*), count(basis) from mark").fetchall():
        ev.marks_total, ev.marks_with_basis = int(str(total)), int(str(with_basis))
    # And what the DOCUMENTS say, which is a different question from what the
    # ledger column holds. `valuation_basis_stated` is a cited fact: a sentence
    # in a source that says what the mark rests on, with a resolving span.
    stated = conn.execute(
        "select count(distinct c.holding_id) from extracted_fact f"
        " join claim c on c.id = f.claim_id"
        " where f.field_name = 'valuation_basis_stated'"
    ).fetchone()
    if stated is not None:
        ev.holdings_stating_basis = int(str(stated[0]))

    for h, cls, status, fname in conn.execute(
        "select c.holding_id, c.source_class::text, c.execution_status::text, x.field_name"
        " from claim c left join extracted_fact x on x.claim_id = c.id"
    ).fetchall():
        ev.classes_by_position[str(h)].add(str(cls))
        ev.statuses_by_position[str(h)].add(str(status))
        if fname is not None:
            ev.fields_by_position[str(h)].add(str(fname))
    # A claim's reliance window is what makes evidence available AT a date:
    # `applicable_from`/`applicable_to` are why a term sheet supports 24Q4 while
    # a closing notice issued later does not support the date before it existed.
    for h, d, cls, status, fname in conn.execute(
        "select c.holding_id, p.period_date, c.source_class::text, c.execution_status::text,"
        " x.field_name"
        " from claim c"
        " join holding h on h.id = c.holding_id"
        " join reporting_period p on p.fund_id = h.fund_id and p.audit_scope = 'packet'"
        " left join extracted_fact x on x.claim_id = c.id"
        " where (c.applicable_from is null or c.applicable_from <= p.period_date)"
        "   and (c.applicable_to is null or c.applicable_to >= p.period_date)"
    ).fetchall():
        ev.classes_by_date[(str(h), str(d))].add(str(cls))
        ev.statuses_by_date[(str(h), str(d))].add(str(status))
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
    #
    # A management assessment answers under its KIND, not under
    # `management_assessment` — that is the whole point of `0012`. The bare type
    # is still recorded for every other decision, so `valuation` and
    # `transcription` are unaffected.
    for h, d, kind in conn.execute(
        "select m.holding_id, p.period_date,"
        " coalesce(r.assessment_kind::text, r.decision_type::text)"
        " from review_decision r"
        " join mark m on m.id = r.mark_id"
        " join reporting_period p on p.id = m.period_id"
    ).fetchall():
        ev.decisions_by_position[str(h)].add(str(kind))
        ev.decisions_by_date[(str(h), str(d))].add(str(kind))
    # What a representativeness assessment says it considered. `0012` refuses a
    # consideration on any other kind of decision, so this needs no filter — the
    # database will not let one exist.
    for h, d, what in conn.execute(
        "select m.holding_id, p.period_date, a.consideration::text"
        " from assessment_consideration_record a"
        " join review_decision r on r.id = a.decision_id"
        " join mark m on m.id = r.mark_id"
        " join reporting_period p on p.id = m.period_id"
    ).fetchall():
        ev.considerations_by_position[str(h)].add(str(what))
        ev.considerations_by_date[(str(h), str(d))].add(str(what))
    ev.realised = {
        str(h)
        for (h,) in conn.execute(
            "select distinct holding_id from lot where realized_date is not null"
        ).fetchall()
    }
    check_fund_scope(ev)
    return ev


def check_fund_scope(ev: Evidence) -> None:
    """The letter's fund is one the ledger actually holds positions for.

    `LETTER_FUND` is the one name here matched against neither the letter nor a
    column — `fund.legal_name` is the id repeated, so there is nothing to
    resolve against. This is what catches it going stale: an id rename, or a
    schema loaded with Fund I alone, would otherwise print `Fund II 0/0` beside
    every limb and read as a fund with no support rather than as a report
    pointed at nothing.
    """
    if LETTER_FUND not in set(ev.funds.values()):
        raise AcceptanceError(
            f"no holding in this ledger belongs to {LETTER_FUND!r}, which is the fund the"
            f' letter names — "{LETTER_FUND_FRAGMENT}". Either the report is pointed at the'
            " wrong schema or `holding.fund_id` no longer spells it that way; both make"
            " every count below a count of the wrong thing."
        )


def predicate(
    limb: Limb,
) -> tuple[str, frozenset[str], frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    """Everything `answered` is allowed to read off a limb.

    Two limbs with equal predicates return equal results for every position at
    every date, on every corpus, forever. That is not a heuristic — it is the
    whole input to the function — which is what lets `indistinguishable` state
    it as a fact rather than a suspicion.

    `answered` destructures this and touches no other attribute, so a dimension
    added to one and not the other is a `zip(strict=True)` error rather than a
    limb that quietly stops being told apart from its neighbour.
    """
    return (
        limb.scope,
        limb.classes,
        limb.fields,
        limb.decisions,
        limb.statuses,
        limb.considerations,
    )


def missing_vocabulary(limb: Limb, ev: Evidence) -> list[str]:
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
        + [c for c in limb.considerations if c not in ev.known_considerations]
        + [s for s in limb.statuses if s not in ev.known_statuses]
    )


def indistinguishable(limb: Limb, limbs: tuple[Limb, ...]) -> list[str]:
    """The other limbs whose predicate is this one's, so one signal serves both.

    The second shape of unanswerable, and the one a vocabulary check cannot see:
    every name ¶2(d), ¶3(b) and the closing calibration ask for IS in the enum,
    and they ask for the same one. `review_decision.decision_type` has a single
    `management_assessment` value, so the memo describing the basis of a mark,
    the assessment that a last round price is still representative, and the
    twelve-month calibration are one row in three costumes. Three `0/34`s read
    as three findings; there is one.

    Reported as unanswerable rather than unanswered because nothing the fund
    sends can separate them — a memo written for any one of the three answers
    all three, and no query could say which was asked for. The fix is a
    `decision_type` per artefact, which is a schema change and not this file's
    to make.
    """
    return sorted(o.key for o in limbs if o.key != limb.key and predicate(o) == predicate(limb))


def unspeakable(limb: Limb, ev: Evidence, limbs: tuple[Limb, ...] | None = None) -> list[str]:
    """Why the letter's clause has nowhere in this ledger to land, if it has not.

    Complete sentences rather than bare names, because the two findings below do
    not share a sentence: one is a word the ledger does not have and the other
    is two clauses sharing the word it does.
    """
    absent = missing_vocabulary(limb, ev)
    reasons = []
    if absent:
        reasons.append(f"the ledger's vocabulary has no {', '.join(absent)}")
    twins = indistinguishable(limb, LIMBS if limbs is None else limbs)
    if twins:
        asked = ", ".join(sorted(limb.classes | limb.fields | limb.decisions | limb.statuses))
        reasons.append(
            f"the ledger cannot tell this apart from {' and '.join(twins)}: all"
            f" {len(twins) + 1} are answered by {asked} and by nothing else, so one record"
            " in the corpus would answer every one of them and no query could say which"
            " artefact the fund actually wrote"
        )
    return reasons


def scope_of(limb: Limb, ev: Evidence) -> list[tuple[str, str | None]]:
    """Which positions, at which dates, this limb is owed for."""
    if limb.scope == BY_POSITION:
        return [(h, None) for h in sorted({h for h, _ in ev.held})]
    if limb.scope == BY_REALISATION:
        return [(h, None) for h in sorted(ev.realised)]
    return sorted(ev.held)


def answered(limb: Limb, ev: Evidence, holding: str, on: str | None) -> bool:
    """Every DECLARED dimension satisfied; alternatives within each.

    Reads `predicate(limb)` and nothing else off the limb — see there for why.
    """
    _scope, *asked = predicate(limb)
    if on is None:
        held = (
            ev.classes_by_position[holding],
            ev.fields_by_position[holding],
            ev.decisions_by_position[holding],
            ev.statuses_by_position[holding],
            ev.considerations_by_position[holding],
        )
    else:
        held = (
            ev.classes_by_date.get((holding, on), set()),
            ev.fields_by_date.get((holding, on), set()),
            ev.decisions_by_date.get((holding, on), set()),
            ev.statuses_by_date.get((holding, on), set()),
            ev.considerations_by_date.get((holding, on), set()),
        )
    return all(not want or bool(want & have) for want, have in zip(asked, held, strict=True))


@dataclass
class LimbResult:
    limb: Limb
    answered: list[tuple[str, str | None]]
    unanswered: list[tuple[str, str | None]]
    not_expressible: list[str]

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
            results.append(LimbResult(limb, yes, no, unspeakable(limb, ev, LIMBS)))
        out[code] = results
    return out


def company_of(holding: str, fund: str | None) -> str:
    """The holding id with the fund it belongs to lifted off, never dropped."""
    return holding if fund is None else holding.removeprefix(f"{fund}_")


def short(holding: str, fund: str | None) -> str:
    """The company, with the fund still attached.

    This used to be `removeprefix("fund_i_").removeprefix("fund_ii_")`, which
    printed `capsule` and `anthropic` in one column of a Fund II letter — five
    of the fourteen names below are Fund I's and nothing said so. The fund comes
    from `holding.fund_id`; a holding whose fund is unknown prints its whole id,
    because a name this report cannot place is exactly the one worth seeing.
    """
    if fund is None:
        return holding
    return f"{FUND_LABEL.get(fund, fund)} · {company_of(holding, fund)}"


def fund_order(ev: Evidence) -> list[str]:
    """The letter's fund first, then whatever else the ledger carries."""
    others = sorted(set(ev.funds.values()) - {LETTER_FUND})
    return [LETTER_FUND, *others] if LETTER_FUND in set(ev.funds.values()) else others


def fund_split(r: LimbResult, ev: Evidence) -> str:
    """The limb's count, said again per fund.

    `4/14` is a denominator over two funds, and the client asked about one. The
    split is not a nicety: 5 of the 14 positions are outside the engagement, so
    a reader taking `4/14` as coverage of the letter is reading a number that
    was never about the letter.
    """
    parts = []
    for fund in fund_order(ev):
        total = sum(1 for h, _ in r.answered + r.unanswered if ev.funds.get(h) == fund)
        if not total:
            continue
        yes = sum(1 for h, _ in r.answered if ev.funds.get(h) == fund)
        parts.append(f"{FUND_LABEL.get(fund, fund)} {yes}/{total}")
    return " · ".join(parts)


def named(entries: list[tuple[str, str | None]], ev: Evidence) -> list[str]:
    """The companies in `entries`, grouped under the fund each belongs to."""
    lines = []
    for fund in fund_order(ev):
        names = sorted({company_of(h, fund) for h, _ in entries if ev.funds.get(h) == fund})
        if names:
            shown = ", ".join(names[:8]) + (" …" if len(names) > 8 else "")
            lines.append(f"{FUND_LABEL.get(fund, fund)}: {shown}")
    unplaced = sorted({h for h, _ in entries if h not in ev.funds})
    if unplaced:
        lines.append(f"no fund recorded: {', '.join(unplaced)}")
    return lines


def basis_caveat(ev: Evidence) -> list[str]:
    """Why ¶2's four limbs are scored against every position and not a subset.

    ¶2 is written in two branches — "For marks based on a financing round: …
    For marks based on other information: …" — and which branch governs a mark
    is `mark.basis`, which is NULL for every mark in this ledger. So 2a and 2b
    are asked of positions whose mark may rest on other information, and 2c and
    2d of positions marked off a round, and every one of the four denominators
    is larger than the letter's.

    The tempting fix is to infer each mark's basis from the evidence on file.
    That is circular — it would decide what evidence is required from the
    evidence present, and every mark would be judged against whatever it happens
    to have. Saying the denominator is wrong is worth more than quietly making
    it look right.
    """
    if ev.marks_with_basis >= ev.marks_total:
        return []
    return [
        *wrapped(
            "The letter's two branches are CONDITIONAL and this ledger cannot yet scope"
            f" them: `mark.basis` is recorded for {ev.marks_with_basis} of {ev.marks_total}"
            " marks. All four limbs below are therefore scored against every held"
            " position-date rather than against the subset its branch governs, and every"
            " denominator is larger than the letter's.",
            "  ",
        ),
        *wrapped(
            f"What the SOURCES say is now read: {ev.holdings_stating_basis} of"
            f" {len(ev.holdings)} positions carry a `valuation_basis_stated` fact — a sentence in a"
            " document, cited to its span, saying what the mark rests on. The remainder"
            " state none, and that silence is a finding about the corpus rather than a gap"
            " in this reader.",
            "  ",
        ),
        *wrapped(
            "Turning a stated basis into a BRANCH is a judgement nobody has made, and it is"
            " left undone deliberately. Moonfare's is a March 2023 round AND a third-party"
            " memorandum; Jio's is a round price adjusted for fees and expenses, which no"
            " branch describes; Banzai states a quoted price for three years and a purchase"
            " cost for two others. Each mapping is one word, with no error anywhere, and the"
            " denominator it produced would look right. The basis is never inferred from the"
            " evidence on file — deciding what evidence is required from the evidence present"
            " is circular.",
            "  ",
        ),
        "",
    ]


def wrapped(text: str, indent: str) -> list[str]:
    """One sentence, at a width that can be read beside the numbers."""
    return textwrap.wrap(text, width=94, initial_indent=indent, subsequent_indent=indent)


def report(ev: Evidence, results: dict[str, list[LimbResult]]) -> list[str]:
    """The requests, in the client's order and the client's words."""
    counted = ", ".join(
        f"{FUND_LABEL.get(f, f)} {sum(1 for x in ev.funds.values() if x == f)}"
        for f in fund_order(ev)
    )
    lines = [
        "",
        "7GC OS · acceptance against the Harwell & Kent letter",
        f"  letter   {LETTER.name}",
        f'  scope    "{LETTER_FUND_FRAGMENT}"',
        f"  ledger   {len(ev.holdings)} positions ({counted}) · {len(ev.dates)} measurement dates"
        f" ({', '.join(ev.dates)})",
        "",
        "Each request is checked in the limbs the client wrote it in. A position with no",
        "evidence for a limb is a gap in the CORPUS and is listed, never failed on.",
        "",
        "Every count is split by fund. The letter is Fund II's; `docs/SPEC.md` applies the",
        "same categories to Fund I deliberately, so those positions are measured too — but",
        "they are not what the client asked about, and a combined denominator would hide it.",
    ]
    for code, title, _ in REQUESTS:
        lines += ["", f"{code} · {title}", ""]
        if code == "¶2":
            lines += basis_caveat(ev)
        for r in results[code]:
            if r.not_expressible:
                mark = "!!"
            elif r.limb.census or r.answered:
                mark = "  "
            else:
                mark = " ·"
            lines.append(f"  {mark} {r.limb.key:4} {r.limb.text}")
            if r.not_expressible:
                for reason in r.not_expressible:
                    lines += wrapped(f"NOT EXPRESSIBLE — {reason}", "          ")
                continue
            if r.limb.census:
                # A census reports its members, not a coverage fraction. The
                # positions NOT in it owe nothing, and listing them as "no
                # evidence" would ask the fund to produce documents for marks
                # that are not pro forma.
                lines.append(
                    f"          identifies {len(r.answered)} of {r.total} held position-dates"
                )
                lines += [f"          {line}" for line in named(r.answered, ev)] or [
                    "          none — no position is marked on a pro forma basis at any"
                    " measurement date"
                ]
                continue
            lines.append(
                f"          answered for {len(r.answered)}/{r.total} · {fund_split(r, ev)}"
            )
            lines += [f"          no evidence · {line}" for line in named(r.unanswered, ev)]
    return lines


def by_company(ev: Evidence, results: dict[str, list[LimbResult]]) -> list[str]:
    """ "We would appreciate receiving the support organized by portfolio company."

    The letter's last request, and the only one about shape rather than content.
    It is answered by producing this table at all.
    """
    per: dict[str, set[str]] = defaultdict(set)
    for rs in results.values():
        for r in rs:
            # A census limb is not support. Listing `5` beside a company here
            # would read as "this company answers the fifth request" when what
            # it means is "this company's mark is pro forma" — the opposite
            # direction, in a column headed by how much it has answered.
            if r.limb.census:
                continue
            for holding, _on in r.answered:
                per[holding].add(r.limb.key)
    order = {fund: n for n, fund in enumerate(fund_order(ev))}
    lines = ["", "Support organised by portfolio company", ""]
    lines.append("  The letter's fund first. ¶5 is an identification and not support, so it is")
    lines.append("  counted above and not here.")
    lines.append("")
    lines.append(f"  {'company':26} {'limbs':>5}   which")
    for holding in sorted(
        ev.holdings,
        key=lambda h: (order.get(ev.funds.get(h, ""), len(order)), company_of(h, ev.funds.get(h))),
    ):
        keys = sorted(per.get(holding, set()))
        name = short(holding, ev.funds.get(holding))
        lines.append(f"  {name:26} {len(keys):>5}   {', '.join(keys) or '—'}")
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


def collapse_groups(unspoken: list[LimbResult]) -> list[frozenset[str]]:
    """The sets of limbs that share one predicate, each set named once."""
    return sorted(
        {
            frozenset([r.limb.key, *indistinguishable(r.limb, LIMBS)])
            for r in unspoken
            if indistinguishable(r.limb, LIMBS)
        },
        key=sorted,
    )


def collapses(unspoken: list[LimbResult]) -> list[str]:
    """The indistinguishable limbs, counted ONCE each way they collapse.

    Three rows above and one defect, and saying "3 unanswerable" without this
    repeats the mistake the rows are reporting. The count that matters to
    whoever fixes it is the number of distinctions the schema is missing.
    """
    lines: list[str] = []
    for group in collapse_groups(unspoken):
        keys = ", ".join(sorted(group))
        lines += wrapped(
            f"{keys} are ONE finding and not {len(group)}: the letter asks for"
            f" {len(group)} different documents and the ledger has one way to record them."
            " Separating them is a schema change — a `decision_type` per artefact — and"
            " until it is made, a memo answering any one of them answers all of them.",
            "  ",
        )
        lines.append("")
    return lines


def closing(results: dict[str, list[LimbResult]], strict: bool) -> tuple[list[str], int]:
    """The two failing states, printed apart because the fix differs — and only
    one of them is this system's fault.

    UNANSWERABLE is a defect here: a clause of the letter with nowhere in the
    ledger to land, which nothing the fund sends could ever satisfy. It fails.
    Two shapes — a word the ledger does not have, and two clauses sharing the
    word it does — and the second is why ¶2(d), ¶3(b) and the calibration are
    one row here rather than three below.

    UNANSWERED is the fund's records saying no. Management has written no basis
    memo and no representativeness assessment, and that is the true state of the
    engagement rather than a bug — the packet's own next actions already ask for
    both. Failing on it would make this command permanently red, and a signal
    that is always red is one people learn to skip, which is how the gate got
    into trouble once already. It is printed loudly and `--strict` fails on it,
    for anyone who wants the stricter contract.

    A CENSUS limb appears in neither. "Identify any positions marked on a pro
    forma basis" is answered by the answer `none`, and a fund whose marks all
    rest on executed documents is not owing the auditor anything for it.
    """
    every = [r for rs in results.values() for r in rs]
    unspoken = [r for r in every if r.not_expressible]
    unanswered = [
        r for r in every if not r.not_expressible and not r.answered and not r.limb.census
    ]
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
            for reason in r.not_expressible:
                lines += wrapped(reason, "         ")
        lines.append("")
        lines += collapses(unspoken)
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
    # The unanswerable limbs are counted twice on purpose: once as rows, which
    # is what a reader of the report above sees, and once as DEFECTS, which is
    # what someone fixing them has to make. Collapsed limbs are many of the
    # first and one of the second, and printing only the row count would state
    # the collapse in the same voice that caused it.
    defects = len(unspoken) - sum(len(g) - 1 for g in collapse_groups(unspoken))
    counted = f"{len(unspoken)} unanswerable"
    if defects != len(unspoken):
        counted += f" ({defects} distinct, the rest collapsed onto them)"
    lines.append(
        f"{len(unspoken) + len(unanswered)} of {len(every)} limbs go unanswered"
        f" — {counted}, {len(unanswered)} unanswered."
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
