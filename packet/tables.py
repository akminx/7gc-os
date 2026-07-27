"""The packet's tabular content, built once and rendered twice.

Every sheet of the workbook and every CSV beside it comes from the same `Table`
values. Two builders — one for the workbook, one for the flat files — is two
places for a column to be added, and the failure mode is a spreadsheet and an
index that disagree about the same position while both look complete.

Nothing here reaches for a database or a filesystem: a table is a pure function
of the `Packet`, the `Evidence` and the `Layout`. That is what lets the honest
cases (nothing approved, a realised position with no mark, a company with no
documents at all) be exercised without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from packages.contracts.enums import RequirementCode, RequirementVerdict
from packages.contracts.models import (
    HoldingRow,
    Money,
    Packet,
    PacketTotals,
    TotalKind,
)
from packet.evidence import Evidence
from packet.layout import Layout
from packet.recompute import Recomputation
from policy.validators import Outcome

Cell = str | int | Decimal | None


@dataclass(frozen=True)
class Table:
    """One sheet, and one CSV. `footer` is prose and never becomes a data row.

    A total appended as a row is a row a reader will sum, so the qualified
    totals live on the cover and in the footer text — never inside the data.
    """

    key: str
    title: str
    note: str
    headers: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    footer: tuple[str, ...] = ()


#: SPEC §7.1 keyed to the paragraph of the audit letter that asks for it. The
#: packet is measured against the letter, not against itself, so the mapping is
#: stated in the deliverable rather than left in a design document.
REQUIREMENTS: dict[RequirementCode, tuple[str, str]] = {
    RequirementCode.R1: (
        "existence_and_cost",
        "Letter ¶1 — executed transaction documents supporting acquisition, "
        "share counts, price per share and settlement of funds",
    ),
    RequirementCode.R2: (
        "fair_value_support",
        "Letter ¶2 — fair value support as of this measurement date",
    ),
    RequirementCode.R3: (
        "unchanged_mark_calibration",
        "Letter ¶3 — management's assessment that the last round price remains "
        "representative at this date",
    ),
    RequirementCode.R4: (
        "realization_support",
        "Letter ¶4 — merger consideration, distribution notices or other support "
        "for proceeds received",
    ),
    RequirementCode.R5: (
        "pro_forma_identification",
        "Letter, closing paragraph — identify any positions marked on a pro forma "
        "basis pending executed documentation",
    ),
}

_ORDER = tuple(sorted(REQUIREMENTS))


def money_text(amount: Money) -> str:
    """A figure with its currency attached. INV-11 · money is never a bare number."""
    return f"{amount.amount:,.2f} {amount.currency}"


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def stated_figure(value: Decimal | None) -> Decimal | None:
    """A cited figure at the scale it was stated, not at the column's width.

    Facts are stored in `numeric(26,12)`, so a cap table's `100,000,000` arrives
    as `100000000.000000000000` and sits beside the passage it was read from
    looking like a different, more precise number. Trailing zeros after the point
    carry no information — `api/ledger.py` says the same of money on the way in —
    and they are dropped here rather than rounded, so no significant digit can be
    lost by this.
    """
    if value is None:
        return None
    if value == value.to_integral_value():
        return value.to_integral_value()
    return value.normalize()


def approved_fair_value(packet: Packet) -> PacketTotals:
    """The total of positions carrying a recorded valuation approval.

    Almost always zero on this corpus, and that is the point: `HoldingRow.approved`
    requires an approval row that binds the mark revision and an evidence set
    (INV-10), so "nothing is unsupported" cannot stand in for "somebody approved
    this". The contract refuses an approved total containing unsupported inputs,
    which makes an approved-but-unsupported row an export failure rather than a
    line in a deliverable.
    """
    currency = next(
        (r.mark.reported.currency for r in packet.rows if r.mark is not None),
        "USD",
    )
    total = Money(amount=Decimal(0), currency=currency)
    unsupported = Money(amount=Decimal(0), currency=currency)
    approved = [r for r in packet.rows if r.approved and r.held_at_date and r.mark is not None]
    for row in approved:
        assert row.mark is not None
        total = total + row.mark.reported
        if not row.supported:
            unsupported = unsupported + row.mark.reported
    return PacketTotals(
        kind=TotalKind.APPROVED_FAIR_VALUE,
        label="Positions carrying a recorded valuation approval bound to this mark revision",
        amount=total,
        unsupported_amount=unsupported,
        unsupported_positions=sum(1 for r in approved if not r.supported),
    )


def _mark_state(row: HoldingRow, on: date) -> str:
    """What the ledger holds for this position at this date, in words.

    A realised position has no mark, and the absence is rendered rather than
    filled: no stale figure carried forward, and no zero, which would be a
    statement that the position was worth nothing.
    """
    if row.mark is not None:
        return f"revision {row.mark.revision} (mark #{row.mark.id})"
    if not row.held_at_date:
        return f"no mark — not held at {on.isoformat()}"
    return f"no mark recorded at {on.isoformat()}"


def not_applicable_because_unheld(row: HoldingRow, code: RequirementCode) -> bool:
    """Is this open reason merely a requirement that does not arise at this date?

    `HoldingRow.unsupported_reasons` requires R1 and R2 to be `sufficient` on
    every row, including a position that was not held at the measurement date —
    where the validator immediately above it in the contract explicitly permits
    both to be `not_applicable`. So a position realised during the period reads
    as unsupported for missing existence-and-cost evidence it cannot have.

    `evals/oracle/derived.json` disagrees with the contract here: Jackpocket at
    2024-12-31 is `fully_supported: true` there and `supported == False` on the
    contract, which is the whole of the one-row difference between the oracle's
    `packet_gap_row_count` of 5 and `packet_gap_positions` of 6.

    The contract is frozen, so this does not overrule it — `supported` is still
    what the packet reports. What this decides is how the finding is *typed* in
    the gap report: an auditor told to chase the acquisition paperwork for a
    position sold in May has been sent after a document that does not exist, and
    the letter separates those cases itself (¶1 for positions held, ¶4 for
    realisations).
    """
    if row.held_at_date:
        return False
    found = next((a for a in row.assessments if a.requirement is code), None)
    return found is not None and found.verdict is RequirementVerdict.NOT_APPLICABLE


def _support_text(row: HoldingRow) -> str:
    reasons = row.unsupported_reasons
    if not reasons:
        return "supported"
    detail = "; ".join(f"{code.value} {reason}" for code, reason in sorted(reasons.items()))
    if all(not_applicable_because_unheld(row, code) for code in reasons):
        return (
            f"not held at this date: {detail} — the requirement does not arise; "
            "see letter ¶4 (realised investments)"
        )
    return f"not supported: {detail}"


def _approval_text(row: HoldingRow) -> str:
    if row.approval is None:
        return "none recorded"
    if row.approved:
        return f"approved by {row.approval.actor_id} on {row.approval.decided_at.isoformat()}"
    return f"{row.approval.decision_type.value} {row.approval.status.value} — not an approval"


def holdings(packet: Packet) -> Table:
    on = packet.period.period_date
    totals = packet.totals()
    rows: list[tuple[Cell, ...]] = []
    for row in sorted(packet.rows, key=lambda r: (r.company_name, r.holding_id)):
        verdicts = {a.requirement: a.verdict.value for a in row.assessments}
        rows.append(
            (
                row.company_name,
                row.holding_id,
                row.position_type.value,
                yes_no(row.held_at_date),
                _mark_state(row, on),
                None if row.mark is None else row.mark.reported.amount,
                None if row.mark is None else row.mark.reported.currency,
                None if row.mark is None else row.mark.derivation_status.value,
                None if row.mark is None else row.mark.derivation_reason,
                _support_text(row),
                *(verdicts.get(code, RequirementVerdict.NOT_ASSESSED.value) for code in _ORDER),
                len(row.gaps),
                _approval_text(row),
            )
        )
    return Table(
        key="holdings",
        title="Holdings",
        note=(
            f"One row per portfolio investment in the {packet.period.label} packet. "
            "Amounts are tracker-reported and unaudited; a blank amount is a position "
            "the ledger holds no mark for at this date, not a position worth nothing."
        ),
        headers=(
            "Portfolio company",
            "Holding id",
            "Position type",
            f"Held at {on.isoformat()}",
            "Mark at this date",
            "Tracker-reported amount (unaudited)",
            "Currency",
            "Derivation status",
            "Derivation reason",
            "Evidence support",
            *(f"{code.value} {REQUIREMENTS[code][0]}" for code in _ORDER),
            "Open gap observations",
            "Valuation approval",
        ),
        rows=tuple(rows),
        footer=(
            f"{totals.kind.value}: {totals.label}",
            f"  {money_text(totals.amount)}",
            f"of which unsupported: {money_text(totals.unsupported_amount)} across "
            f"{totals.unsupported_positions} position(s) held at {on.isoformat()}",
            f"further unsupported positions not held at this date: "
            f"{totals.packet_gap_positions - totals.unsupported_positions}",
        ),
    )


def recomputation(packet: Packet, recomputed: dict[str, Recomputation]) -> Table:
    """SPEC §8's V2, in the packet the auditor takes away.

    The screen shows this; so must the deliverable. An auditor who is told on a
    web page that the fund's Fluidstack mark is 3,500,000 above what its own
    documents derive, and then receives a packet that says only 6,000,000, has
    been shown a finding they cannot cite.

    Every column is labelled as a RECOMPUTATION. `Derived amount` is not
    `Validated amount` — nothing here has been approved, the figure is computed
    from the cited evidence each time the packet is generated, and the ledger's
    `mark.validated_amount` is untouched and still empty. `Outcome` is SPEC §8's
    six-value vocabulary rather than a pass/fail column, because
    `not_comparable` (the fund is the author of both figures) and
    `unconfirmable` (the evidence is silent) send different letters.

    Sorted with the disagreements first. A table an auditor reads top to bottom
    should open on what is wrong with it, and alphabetical order buries the two
    rows the whole check exists to surface behind six that agree.
    """
    on = packet.period.period_date
    ordered = sorted(packet.rows, key=lambda r: _reading_order(recomputed, r))
    rows: list[tuple[Cell, ...]] = []
    for row in ordered:
        got = recomputed.get(row.holding_id)
        if got is None:
            continue
        rows.append(
            (
                row.company_name,
                row.holding_id,
                got.outcome.value,
                got.reason,
                None if got.derived is None else got.derived.amount,
                None if got.reported is None else got.reported.amount,
                None if got.difference is None else got.difference.amount,
                None if got.derived is None else got.derived.currency,
                " + ".join(
                    f"{part.shares} {part.security_class} x {part.price_per_share}"
                    for part in got.per_class
                )
                or None,
                ", ".join(got.evidence_claim_ids) or None,
                got.policy_version,
            )
        )
    disagreements = [r for r in rows if r[2] == Outcome.FAIL.value]
    return Table(
        key="recomputation",
        title="Independent recomputation",
        note=(
            "What the CITED EVIDENCE derives for each mark at "
            f"{on.isoformat()}, computed when this packet was generated and stored "
            "nowhere. It is not a validated amount and not an approved value: no "
            "figure here has been confirmed by a human, and the ledger's own "
            "validated amount is empty for every position in this fund. Where the "
            "derived and reported figures differ, neither is asserted to be the "
            "correct one — the difference is the finding."
        ),
        headers=(
            "Portfolio company",
            "Holding id",
            "Recomputation outcome",
            "How the figure was reached",
            "Derived amount (not validated, not approved)",
            "Tracker-reported amount (unaudited)",
            "Reported minus derived",
            "Currency",
            "Per class, priced by its own class",
            "Evidence relied on",
            "Policy version",
        ),
        rows=tuple(rows),
        footer=(
            f"{len(disagreements)} of {len(rows)} position(s) derive a figure that differs "
            "from the one reported.",
            *(f"  {r[0]}: derived {r[4]} against a reported {r[5]}" for r in disagreements),
            "An outcome of `unconfirmable` means the evidence states no figure this "
            "check could derive; `not_comparable` means it states one and the fund "
            "wrote the document it came from, so comparing the two is circular; "
            "`blocked_incomplete` means the document states the figure and this "
            "system has no field for its shape. None of the three is a pass.",
        ),
    )


def _reading_order(recomputed: dict[str, Recomputation], row: HoldingRow) -> tuple[int, str, str]:
    """Where this row sits in the table, and then alphabetically.

    A row with no recomputation sorts after every outcome rather than into one
    of them: "the check did not run for this row" is not a seventh outcome, and
    filing it under the last one would put it beside findings it says nothing
    about.
    """
    got = recomputed.get(row.holding_id)
    rank = len(_RECOMPUTATION_ORDER) if got is None else _RECOMPUTATION_ORDER[got.outcome]
    return (rank, row.company_name, row.holding_id)


#: Disagreements first, then the checks that could not run, then the agreements.
#: Not a ranking of severity — SPEC §8's outcomes are unordered — but a reading
#: order, so a table opens on what is wrong with it.
_RECOMPUTATION_ORDER = {
    Outcome.FAIL: 0,
    Outcome.NOT_COMPARABLE: 1,
    Outcome.BLOCKED_INCOMPLETE: 2,
    Outcome.UNCONFIRMABLE: 3,
    Outcome.PASS: 4,
    Outcome.NOT_APPLICABLE: 5,
}


def requirements(packet: Packet) -> Table:
    rows: list[tuple[Cell, ...]] = []
    for row in sorted(packet.rows, key=lambda r: (r.company_name, r.holding_id)):
        assessed = {a.requirement: a for a in row.assessments}
        for code in _ORDER:
            found = assessed.get(code)
            category, asked_for = REQUIREMENTS[code]
            if found is None:
                rows.append(
                    (
                        row.company_name,
                        row.holding_id,
                        code.value,
                        category,
                        asked_for,
                        RequirementVerdict.NOT_ASSESSED.value,
                        yes_no(True),
                        "no",
                        "NOT_ASSESSED",
                        "assess this requirement",
                        None,
                        "no",
                        None,
                    )
                )
                continue
            rows.append(
                (
                    row.company_name,
                    row.holding_id,
                    code.value,
                    category,
                    asked_for,
                    found.verdict.value,
                    yes_no(found.applicable),
                    yes_no(found.pro_forma),
                    "; ".join(found.reason_codes) or None,
                    "; ".join(found.next_actions) or None,
                    "; ".join(e.claim.id for e in found.evidence) or None,
                    yes_no(any(e.is_subsequent for e in found.evidence)),
                    found.policy_version,
                )
            )
    return Table(
        key="requirements",
        title="Requirements",
        note=(
            "The five PBC requirements per position, each with its own verdict. "
            "`not_applicable` means the requirement does not arise; `missing` means "
            "it does and the evidence is absent. They are different findings."
        ),
        headers=(
            "Portfolio company",
            "Holding id",
            "Requirement",
            "Category",
            "What the letter asks for",
            "Verdict",
            "Applicable",
            "Pro forma",
            "Reason codes",
            "Next actions",
            "Evidence relied on",
            "Includes subsequent evidence",
            "Policy version",
        ),
        rows=tuple(rows),
    )


def evidence_index(packet: Packet, evidence: Evidence, layout: Layout) -> Table:
    """Every cited figure, and the passage it resolves to.

    This is the artefact that makes the packet audit support rather than a
    spreadsheet: a reader takes the two offsets, opens the exported canonical
    text beside the source document, and reads the sentence the figure came from.
    """
    rows: list[tuple[Cell, ...]] = []
    for row in sorted(packet.rows, key=lambda r: (r.company_name, r.holding_id)):
        holding = evidence.by_holding.get(row.holding_id)
        if holding is None:
            continue
        relied: dict[str, list[str]] = {}
        for assessment in row.assessments:
            for cited in assessment.evidence:
                relied.setdefault(cited.claim.id, []).append(assessment.requirement.value)
        documents = {d.document_version_id: d for d in holding.documents}
        for claim in holding.claims:
            document = documents.get(claim.document_version_id)
            for fact in holding.facts.get(claim.id, ()):
                rows.append(
                    (
                        row.company_name,
                        row.holding_id,
                        "; ".join(sorted(relied.get(claim.id, []))) or "not relied on",
                        claim.id,
                        claim.claim_key,
                        claim.source_class.value,
                        claim.execution_status.value,
                        claim.issued_date.isoformat(),
                        claim.applicable_from.isoformat(),
                        None if claim.applicable_to is None else claim.applicable_to.isoformat(),
                        fact.field_name,
                        fact.value_text,
                        stated_figure(fact.value_numeric),
                        fact.state.value,
                        None if document is None else document.filename,
                        layout.source_path.get(claim.document_version_id),
                        layout.text_path.get(claim.document_version_id),
                        fact.citation.document_version_id,
                        fact.citation.span_start,
                        fact.citation.span_end,
                        fact.citation.quote,
                    )
                )
    return Table(
        key="evidence_index",
        title="Evidence index",
        note=(
            "One row per cited source fact. The offsets are code-point positions into "
            "the exported canonical text file named beside them: text[start:end] is the "
            "quoted passage, verbatim."
        ),
        headers=(
            "Portfolio company",
            "Holding id",
            "Requirements relied on",
            "Claim id",
            "Claim key",
            "Source class",
            "Execution status",
            "Issued date",
            "Applicable from",
            "Applicable to",
            "Field",
            "Value as stated",
            "Value as a number",
            "Fact state",
            "Source document",
            "Exported source file",
            "Exported canonical text",
            "Document version id",
            "Passage offset start",
            "Passage offset end",
            "Cited passage",
        ),
        rows=tuple(rows),
    )


def approval_log(packet: Packet, evidence: Evidence) -> Table:
    """One row per position, plus every decision recorded against the period.

    A position with no decision reads "none recorded" rather than being omitted:
    an empty log and an ungenerated log look identical, and the whole claim this
    packet makes is that its gaps are stated.
    """
    by_mark: dict[int, list[str]] = {}
    for decision in evidence.decisions:
        if decision.mark_id is not None:
            by_mark.setdefault(decision.mark_id, []).append(
                f"{decision.decision_type} {decision.status} by {decision.actor_id} "
                f"on {decision.decided_at.isoformat()} "
                f"({decision.bound_assessments} assessment(s) bound)"
            )
    rows: list[tuple[Cell, ...]] = []
    for row in sorted(packet.rows, key=lambda r: (r.company_name, r.holding_id)):
        found = by_mark.get(row.mark.id, []) if row.mark is not None else []
        rows.append(
            (
                row.company_name,
                row.holding_id,
                None if row.mark is None else row.mark.id,
                None if row.mark is None else row.mark.revision,
                None if row.mark is None else row.mark.reported.amount,
                None if row.mark is None else row.mark.reported.currency,
                "; ".join(found) or "none recorded",
                yes_no(row.approved),
                _support_text(row),
            )
        )
    packet_level = [d for d in evidence.decisions if d.decision_type == "packet"]
    stated = (
        "; ".join(f"{d.status} by {d.actor_id} on {d.decided_at.isoformat()}" for d in packet_level)
        if packet_level
        else "none. This packet is NOT approved."
    )
    footer = (f"Packet-level decisions recorded for this fund-period: {stated}",)
    return Table(
        key="approval_log",
        title="Approval log",
        note=(
            "INV-10 · an approval is a record that binds a mark revision and the "
            "evidence set it rested on. Nothing being wrong with a position is not the "
            "same fact as somebody having approved it."
        ),
        headers=(
            "Portfolio company",
            "Holding id",
            "Mark id",
            "Mark revision",
            "Tracker-reported amount (unaudited)",
            "Currency",
            "Decisions recorded against this mark",
            "Carries an approved valuation",
            "Evidence support",
        ),
        rows=tuple(rows),
        footer=footer,
    )


def gap_report(packet: Packet, evidence: Evidence) -> Table:
    """What this packet does not contain, and why.

    Five kinds of finding, deliberately not merged: a document the fund knows is
    absent, a requirement the evidence does not satisfy, a requirement that does
    not arise at this date, a position with no mark, and a position nobody has
    approved. Collapsing them into one "incomplete" flag is how a packet stops
    being able to say what is wrong — and sending an auditor after a document
    that cannot exist is not a smaller error than omitting a real one.
    """
    on = packet.period.period_date
    rows: list[tuple[Cell, ...]] = []
    for row in sorted(packet.rows, key=lambda r: (r.company_name, r.holding_id)):
        holding = evidence.by_holding.get(row.holding_id)
        for gap in row.gaps:
            rows.append(
                (
                    row.company_name,
                    row.holding_id,
                    "missing_document",
                    gap.requirement.value,
                    gap.security_class,
                    gap.missing_document,
                    gap.kind.value,
                    gap.remediation.value,
                    gap.source_quote,
                    _next_action_for(row, gap.requirement),
                )
            )
        for code, reason in sorted(row.unsupported_reasons.items()):
            inapplicable = not_applicable_because_unheld(row, code)
            rows.append(
                (
                    row.company_name,
                    row.holding_id,
                    "requirement_not_applicable" if inapplicable else "unsupported_requirement",
                    code.value,
                    None,
                    REQUIREMENTS[code][1],
                    reason,
                    "not_applicable" if inapplicable else "open",
                    f"the position was not held at {on.isoformat()}"
                    if inapplicable
                    else _reason_codes_for(row, code),
                    "none — the requirement does not arise for a position not held at "
                    "this date; letter ¶4 (realised investments) applies instead"
                    if inapplicable
                    else _next_action_for(row, code),
                )
            )
        if row.mark is None:
            rows.append(
                (
                    row.company_name,
                    row.holding_id,
                    "no_mark_at_this_date",
                    None,
                    None,
                    f"no valuation mark at {on.isoformat()}",
                    "not_held" if not row.held_at_date else "held_without_a_mark",
                    "open",
                    _mark_state(row, on),
                    "confirm the realisation support at letter ¶4"
                    if not row.held_at_date
                    else "record a mark for this position at this date",
                )
            )
        if not row.approved:
            rows.append(
                (
                    row.company_name,
                    row.holding_id,
                    "no_valuation_approval",
                    None,
                    None,
                    "no approved valuation decision binds this mark revision",
                    "open",
                    "open",
                    _approval_text(row),
                    "record a valuation approval bound to the mark revision and its evidence set",
                )
            )
        if holding is not None and not holding.documents:
            rows.append(
                (
                    row.company_name,
                    row.holding_id,
                    "no_source_documents",
                    None,
                    None,
                    "no source document is held for this position",
                    "not_located",
                    "open",
                    "the company folder for this position is empty",
                    "obtain the executed transaction documents at letter ¶1",
                )
            )
    return Table(
        key="gap_report",
        title="Gap report",
        note=(
            "Everything this packet does not evidence. A packet that omitted these rows "
            "would look complete; it would not be more complete."
        ),
        headers=(
            "Portfolio company",
            "Holding id",
            "Finding",
            "Requirement",
            "Security class",
            "What is missing",
            "Kind",
            "Remediation",
            "Basis",
            "Next action",
        ),
        rows=tuple(rows),
    )


def _reason_codes_for(row: HoldingRow, code: RequirementCode) -> str | None:
    found = next((a for a in row.assessments if a.requirement is code), None)
    return "; ".join(found.reason_codes) if found and found.reason_codes else None


def _next_action_for(row: HoldingRow, code: RequirementCode) -> str | None:
    found = next((a for a in row.assessments if a.requirement is code), None)
    return "; ".join(found.next_actions) if found and found.next_actions else None
