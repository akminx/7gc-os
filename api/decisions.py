"""The one write surface, and why it is not on the read router.

SPEC §3.1 says the public deployment is read-only, and `api/routes.py` said
every route it carried was a GET with "no write path to disable later". §6.3
requires four typed approvable resources, and until now nothing in this system
could record a human approval at all — so the read-only sentence was a promise
the product could not keep. This module is the contract change, made in the open
rather than by quietly adding a POST beside the GETs.

Four things make the separation structural instead of stated:

* **Every write lives under `/decisions`, in this file, on its own router.**
  `tests/test_decisions.py` asserts that the only non-GET route the application
  serves is this one, so a POST added anywhere else turns the gate red rather
  than merely reading oddly. The sentence in `routes.py` stays true of
  `routes.py`.
* **The surface is off unless the deployment names its actors.** §3.1
  distinguishes the public deployment from the private one by exactly that — "a
  private demo deployment uses named actors" — so `DECISION_ACTORS` is both the
  actor list and the switch. It is empty by default, and empty means 403 rather
  than an anonymous write. One variable that fails closed is harder to leave
  half-set than a boolean beside an identity scheme.
* **It is not RBAC and does not pretend to be.** Production identity is out of
  scope (SPEC §2) and a named actor here is an attribution, not an
  authentication. What it does buy is that an approval log on a publicly
  reachable deployment cannot be written by someone the configuration never
  named.
* **A decision type names what it binds** (`SUBJECT_OF` below). One request
  records one row about one subject, so no UI action can advance two decision
  machines at once — INV-18, which is the whole reason §6.3 splits transcription
  from valuation.

What this module deliberately does **not** do is decide whether a decision is
allowed. `supabase/migrations/0003_approval_prerequisites.sql` already refuses
an approval whose evidence set was never assembled, whose assessments are
insufficient, whose policy version disagrees, or whose realisation is
unassessed — and it does so on the side that decides what commits. Re-checking
any of that in Python would produce a second opinion free to drift from the one
the database holds, and the two would disagree exactly when it mattered. So the
write is attempted, `set constraints all immediate` makes the deferred triggers
fire inside the request instead of at commit, and the refusal is translated into
a 409 carrying the database's own sentence.

One honest gap, stated because a reader will look for it: a `transcription`
decision is recorded here, but nothing in this module promotes the source fact
it names. `extracted_fact` is append-only, so promotion is a new row citing this
decision (INV-14), and that is a separate write this endpoint does not make.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from api.config import load_env
from api.ledger import POLICY_VERSION
from packages.contracts.enums import DecisionStatus, DecisionType
from packages.contracts.models import Approval

Conn = psycopg.Connection[tuple[object, ...]]

#: Every write path in the application begins with this.
PREFIX = "/decisions"

decisions_router = APIRouter(tags=["decisions"])

#: SPEC §6.3 · what each of the four decisions binds. Read as a table it is the
#: statement that none of them implies another: a transcription approval is
#: about a source fact, a valuation approval about a mark revision, and no
#: request can name one and be recorded as the other.
SUBJECT_OF: dict[DecisionType, str] = {
    DecisionType.TRANSCRIPTION: "source_fact",
    DecisionType.VALUATION: "mark",
    DecisionType.MANAGEMENT_ASSESSMENT: "mark",
    DecisionType.PACKET: "packet_version",
}

#: The two decisions the schema binds to a mark revision, and therefore the two
#: whose evidence set is a set of `evidence_assessment` rows.
MARK_BOUND = frozenset({DecisionType.VALUATION, DecisionType.MANAGEMENT_ASSESSMENT})

#: `draft` and `superseded` are states a decision arrives at, not verdicts a
#: human hands down. A review records one of these two.
RECORDABLE = frozenset({DecisionStatus.APPROVED, DecisionStatus.REJECTED})


class DecisionRequest(BaseModel):
    """One decision, about one subject, by one actor.

    `subject_id` is a single field rather than one column per decision type on
    purpose: the type decides what the subject is (`SUBJECT_OF`), so a caller
    cannot name a mark and a packet in the same breath and leave the endpoint to
    guess which machine it meant.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_type: DecisionType
    status: DecisionStatus
    subject_id: str
    #: The policy version the caller's verdicts were computed under. Optional,
    #: and checked rather than trusted — see `record`.
    policy_version: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _a_decision_names_its_subject_and_a_rejection_states_why(self) -> DecisionRequest:
        if self.status not in RECORDABLE:
            allowed = ", ".join(sorted(s.value for s in RECORDABLE))
            raise ValueError(f"a review records {allowed}, never {self.status.value}")
        if not self.subject_id.strip():
            raise ValueError("a decision must name the subject it binds")
        if self.decision_type in MARK_BOUND and not self.subject_id.isdigit():
            raise ValueError(
                f"a {self.decision_type.value} decision binds a mark revision, so its subject "
                f"is a mark id; {self.subject_id!r} is not one"
            )
        # A rejection with no stated reason is an audit record that says a human
        # said no and nothing about what would change the answer.
        if self.status is DecisionStatus.REJECTED and not (self.reason or "").strip():
            raise ValueError("a rejection must state its reason")
        return self

    @property
    def subject_kind(self) -> str:
        return SUBJECT_OF[self.decision_type]

    @property
    def mark_id(self) -> int | None:
        return int(self.subject_id) if self.decision_type in MARK_BOUND else None

    @property
    def packet_id(self) -> str | None:
        return self.subject_id if self.decision_type is DecisionType.PACKET else None

    @property
    def stated_reason(self) -> str | None:
        """The reason as stored: blank and absent are the same absence."""
        return (self.reason or "").strip() or None


def named_actors() -> list[str]:
    """SPEC §3.1 · who may record a decision on this deployment.

    Empty on the public deployment, which is what makes it read-only. Resolved
    per call rather than at import, for the same reason `api/config.py` resolves
    the DSN per call: a missing variable must surface as a refused request, not
    as a crash at startup or a value frozen before the environment was read.
    """
    declared = load_env().get("DECISION_ACTORS", "").split(",")
    return [name.strip() for name in declared if name.strip()]


def acting_actor(x_actor_id: Annotated[str | None, Header()] = None) -> str:
    """The named actor making this decision, or a refusal saying why there is none."""
    actors = named_actors()
    if not actors:
        raise HTTPException(
            status_code=403,
            detail=(
                "SPEC §3.1 · this deployment records no decisions. It names no actors, and an "
                "approval nobody is named for is a forged audit record. Decisions are recorded "
                "on the private demo deployment, where DECISION_ACTORS names who may make one."
            ),
        )
    if x_actor_id is None or x_actor_id not in actors:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{x_actor_id!r} is not a named actor on this deployment. Send X-Actor-Id as one "
                "of the actors this deployment names."
            ),
        )
    return x_actor_id


def ledger_connection() -> Iterator[Conn]:
    """The ledger, committed only when the whole decision was accepted.

    The commit sits after the `yield` so that any refusal — the database's, or
    this module's own — leaves nothing behind. There is no fixture fallback
    here, deliberately: the read routes may honestly answer from the bundled
    Dream stub when no database is configured, but a decision recorded against a
    fixture is an approval that exists nowhere, which is worse than no approval.
    """
    # Deferred because `api/routes.py` imports this module to mount the router,
    # and `_connect` is the single sanctioned connection factory — it carries the
    # `prepare_threshold=None` that a transaction-mode pooler requires.
    from api.routes import _connect

    conn = _connect()
    if conn is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "no ledger is configured, so no decision can be recorded. The read routes fall "
                "back to a fixture; a decision has nothing honest to fall back to."
            ),
        )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _refusal(exc: psycopg.Error) -> str:
    """The database's own sentence, without the plpgsql context stack.

    `message_primary` is what the trigger raised — it names the invariant, the
    trigger and the requirement — and that is what a human needs to read. The
    fallback matters for errors that carry no diagnostic at all, where saying
    nothing would be the one unacceptable answer.
    """
    return (exc.diag.message_primary or "").strip() or str(exc).strip()


def _cite_the_evidence(
    conn: Conn, decision_id: int, mark_id: int | None, policy_version: str
) -> list[int]:
    """Attach the assessments this decision rests on, in the same transaction.

    Every assessment bound to the mark at this policy version, not the ones that
    happen to be sufficient: choosing which to cite would be this module picking
    the evidence set that passes, and INV-10 exists so that the set is what was
    actually assessed. `0002`'s seal means the set can only be written here, in
    the decision's own transaction, so there is no later opportunity to improve
    it either.

    A rejection cites its evidence too. The record of what was refused is only
    meaningful beside what it was refused on.
    """
    if mark_id is None:
        return []
    rows = conn.execute(
        "select id from evidence_assessment where mark_id = %s and policy_version = %s order by id",
        (mark_id, policy_version),
    ).fetchall()
    cited: list[int] = []
    for row in rows:
        assessment_id = row[0]
        assert isinstance(assessment_id, int)
        cited.append(assessment_id)
    for assessment_id in cited:
        conn.execute(
            "insert into decision_evidence (decision_id, assessment_id, mark_id)"
            " values (%s, %s, %s)",
            (decision_id, assessment_id, mark_id),
        )
    return cited


def record(conn: Conn, request: DecisionRequest, actor_id: str) -> Approval:
    """Write the decision, make the guards fire now, and report what happened.

    `set constraints all immediate` is the load-bearing line. Both prerequisite
    triggers are deferred, because `decision_evidence` is written after the
    decision row; without this the refusal would arrive at commit time, outside
    the request, and the caller would be told the write succeeded.
    """
    policy_version = request.policy_version or POLICY_VERSION
    if policy_version != POLICY_VERSION:
        # INV-10 · a decision binds the policy it was made under. A caller whose
        # screen was computed at another version is deciding about verdicts this
        # service no longer produces, and recording it at either version would
        # name one policy and mean the other.
        raise HTTPException(
            status_code=409,
            detail=(
                f"this decision names policy version {policy_version}, and this service computes "
                f"verdicts at {POLICY_VERSION}. INV-10 binds a decision to the policy it was made "
                "under, so it cannot be recorded against a different one — reload the packet and "
                "decide again."
            ),
        )
    try:
        row = conn.execute(
            "insert into review_decision (decision_type, status, subject_kind, subject_id,"
            " mark_id, packet_id, policy_version, actor_id, notes)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id, decided_at",
            (
                request.decision_type.value,
                request.status.value,
                request.subject_kind,
                request.subject_id,
                request.mark_id,
                request.packet_id,
                policy_version,
                actor_id,
                request.stated_reason,
            ),
        ).fetchone()
        assert row is not None
        decision_id, decided_at = row[0], row[1]
        assert isinstance(decision_id, int)
        assert isinstance(decided_at, datetime)
        cited = _cite_the_evidence(conn, decision_id, request.mark_id, policy_version)
        conn.execute("set constraints all immediate")
        # And back, because SET CONSTRAINTS lasts for the TRANSACTION, not for
        # the statement. Left immediate, the next decision written in the same
        # transaction has its deferred triggers fire on the INSERT — before its
        # evidence set is attached — and a perfectly complete approval is
        # refused for "names no evidence set". A test recording two decisions
        # about one mark found this; the route commits per request, so it would
        # have waited for the first caller who did not.
        #
        # Every deferrable constraint in `supabase/migrations/` is declared
        # `initially deferred`, so this restores the declared default rather
        # than choosing one.
        conn.execute("set constraints all deferred")
    except psycopg.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail=_refusal(exc)) from None

    return Approval(
        id=decision_id,
        decision_type=request.decision_type,
        status=request.status,
        mark_id=request.mark_id,
        packet_id=request.packet_id,
        policy_version=policy_version,
        evidence_assessment_ids=cited,
        actor_id=actor_id,
        decided_at=decided_at,
    )


@decisions_router.post(PREFIX, status_code=201)
def post_decision(
    request: DecisionRequest,
    actor_id: Annotated[str, Depends(acting_actor)],
    conn: Annotated[Conn, Depends(ledger_connection)],
) -> dict[str, Any]:
    """Record one typed decision. SPEC §6.3 · the type is named by the caller.

    Append-only: this route only ever INSERTs. Changing one's mind is a new
    decision naming the same subject, which is why there is no PUT here and
    `review_decision` refuses UPDATE and DELETE outright.
    """
    return record(conn, request, actor_id).model_dump(mode="json")
