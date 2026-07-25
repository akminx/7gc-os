-- 0003_approval_prerequisites.sql — what an approval must REST ON
--
-- 0002 established that an approval must name *an* evidence set. A wide audit
-- then proved on the live database that "an evidence set" is satisfied by a
-- single row, so all of the following committed:
--
--   * a valuation approval citing one R2 assessment and no R1 at all;
--   * a valuation approval citing an assessment whose verdict is `insufficient`;
--   * a v1 approval citing an assessment made under v0;
--   * a packet approved with an empty manifest and nothing approved beneath it;
--   * manifest entries INSERTed after that approval — the append-only trigger
--     covers UPDATE and DELETE, and `packet_version` was not covered at all, so
--     an approved packet's `state` and `policy_version` could be rewritten;
--   * a Fund I packet pointing at a Fund II period.
--
-- A second, cross-family audit then proved four more against this file's own
-- first draft — again by execution, not by reading:
--
--   * a realised lot approved with sufficient R1/R2 and no R4 anywhere, because
--     completeness was measured only against the requirement rows that happened
--     to exist;
--   * a packet approved over a single manifest entry at ordinal 99;
--   * a policy-v2 packet approved on the strength of policy-v1 valuations;
--   * a valid `workflow_run` UPDATEd onto another fund's period — the identity
--     triggers fired on INSERT only.
--
-- Each was proven by execution, not by reading. This file makes each one be
-- refused. 0001 and 0002 are already applied and are not edited.

begin;

-- ── INV-10 / SPEC 7.1 · the evidence set must be COMPLETE ────────────────
-- "Every applicable requirement is sufficient, at this policy version" is the
-- rule the packet's `supported` property already applies in the contract layer.
-- Enforced on one side only it is not enforced: the database was the side that
-- decided what commits.
--
-- Completeness is measured against `pbc_requirement`, so a holding whose R1 row
-- was never created cannot pass vacuously — R1 and R2 apply to every holding at
-- every date (SPEC 7.1, `always_applicable_requirements_are_applicable`), and
-- an absent requirement row is an evidence set that was never assembled rather
-- than one that came back clean.
--
-- The assessment must also be CITED by this decision. An assessment sitting in
-- the table that the approval does not name is not part of what was approved.
--
-- Deferred, because `decision_evidence` is written after the decision row.
create or replace function require_complete_assessment_set() returns trigger
language plpgsql as $$
declare
    m        mark%rowtype;
    code     requirement_code;
    missing  requirement_code;
    unlinked requirement_code;
    fund_ref text;
    measured date;
    prev     date;
begin
    if new.decision_type <> 'valuation' or new.status <> 'approved' then
        return null;
    end if;
    select * into m from mark where id = new.mark_id;

    foreach code in array array['R1', 'R2']::requirement_code[] loop
        if not exists (select 1 from pbc_requirement r
                        where r.holding_id = m.holding_id
                          and r.period_id  = m.period_id
                          and r.requirement = code)
        then
            raise exception
                'SPEC 7.1 (%): mark % carries no % requirement row, so its approval '
                'covers an evidence set that was never assembled', tg_name, m.id, code;
        end if;
    end loop;

    -- SPEC 7.1 · R4 applies to realised lots, and that applicability is a FACT
    -- about the lots rather than a row someone remembered to create. Measuring
    -- completeness against `pbc_requirement` alone made R4 optional in exactly
    -- the case it exists for: a realised lot approved with no realisation
    -- support at all committed against the live database.
    --
    -- `applicable` is required too, not merely the row: an R4 marked
    -- inapplicable is skipped by the completeness query below, so the row-exists
    -- form of this rule could be satisfied by the assertion it is meant to
    -- refuse.
    --
    -- The window is the oracle's (`Corpus._prev_packet_date`): every lot
    -- realised after the fund's previous packet date and on or before this
    -- measurement date. A wider window would demand R4 for a realisation an
    -- earlier packet already covered, which is the over-strict direction — a
    -- legitimate approval refused is as damaging as a false one admitted, and
    -- harder to notice.
    select h.fund_id into fund_ref from holding h where h.id = m.holding_id;
    select p.period_date into measured from reporting_period p where p.id = m.period_id;
    select max(p.period_date) into prev
      from reporting_period p
     where p.fund_id     = fund_ref
       and p.audit_scope = 'packet'
       and p.period_date < measured;

    if exists (select 1 from lot l
                where l.holding_id    = m.holding_id
                  and l.realized_date is not null
                  and l.realized_date <= measured
                  and (prev is null or l.realized_date > prev))
       and not exists (select 1 from pbc_requirement r
                        where r.holding_id  = m.holding_id
                          and r.period_id   = m.period_id
                          and r.requirement = 'R4'
                          and r.applicable)
    then
        raise exception
            'SPEC 7.1 (%): mark % realises a lot in this measurement window, so R4 '
            'is applicable, but the holding carries no applicable R4 requirement row',
            tg_name, m.id;
    end if;

    select r.requirement into missing
      from pbc_requirement r
     where r.holding_id = m.holding_id
       and r.period_id  = m.period_id
       and r.applicable
       and not exists (
           select 1
             from decision_evidence de
             join evidence_assessment ea on ea.id = de.assessment_id
            where de.decision_id    = new.id
              and ea.requirement_id = r.id
              and ea.mark_id        = new.mark_id
              and ea.verdict        = 'sufficient'
              and ea.policy_version = new.policy_version)
     order by r.requirement
     limit 1;

    if missing is not null then
        raise exception
            'INV-10 (%): valuation approval of mark % cites no sufficient % assessment '
            'at policy version %', tg_name, new.mark_id, missing, new.policy_version;
    end if;

    -- A `sufficient` R1 or R2 with nothing linked is support asserted against no
    -- document. R3-R5 are excluded deliberately: a disclosure or management
    -- requirement can be met by an act of the fund rather than by a claim, and a
    -- rule that is wrong for those would be relaxed until it meant nothing.
    select r.requirement into unlinked
      from pbc_requirement r
      join decision_evidence de     on de.decision_id = new.id
      join evidence_assessment ea   on ea.id = de.assessment_id and ea.requirement_id = r.id
     where r.holding_id = m.holding_id
       and r.period_id  = m.period_id
       and r.requirement in ('R1', 'R2')
       and ea.verdict = 'sufficient'
       and not exists (select 1 from evidence_link el where el.assessment_id = ea.id)
     order by r.requirement
     limit 1;

    if unlinked is not null then
        raise exception
            'INV-10 (%): the % assessment cited by the approval of mark % is sufficient '
            'but links no claim', tg_name, unlinked, new.mark_id;
    end if;
    return null;
end;
$$;

-- Named to sort AFTER `valuation_approval_names_evidence` and
-- `valuation_approval_needs_class_policy`. Deferred constraint triggers fire in
-- trigger-name order, so a name sorting earlier would pre-empt those two and
-- silently change which error their tests observe.
create constraint trigger valuation_approval_needs_complete_evidence
    after insert on review_decision
    deferrable initially deferred
    for each row execute function require_complete_assessment_set();

-- ── INV-10 · a packet approval must rest on something ────────────────────
-- An empty manifest with no approved valuations beneath it is a packet-shaped
-- object, not a packet. Approving one produces an auditor deliverable whose only
-- true statement is its own existence.
create or replace function require_packet_prerequisites() returns trigger
language plpgsql as $$
declare
    pv         packet_version%rowtype;
    marks      int;
    entries    int;
    lo         int;
    hi         int;
    unapproved text;
begin
    if new.decision_type <> 'packet' or new.status <> 'approved' then
        return null;
    end if;
    select * into pv from packet_version where id = new.packet_id;

    -- INV-10 · the approval binds a POLICY SNAPSHOT, not only a packet. A v2
    -- decision over a v1 packet version names two policies and reports one.
    if pv.policy_version is distinct from new.policy_version then
        raise exception
            'INV-10 (%): packet % is recorded at policy version %, but its approval '
            'is at policy version %', tg_name, pv.id, pv.policy_version, new.policy_version;
    end if;

    select count(*), min(e.ordinal), max(e.ordinal) into entries, lo, hi
      from packet_manifest_entry e where e.packet_id = pv.id;

    if entries = 0 then
        raise exception
            'INV-10 (%): packet % is approved with an empty manifest', tg_name, pv.id;
    end if;

    -- A manifest is an ORDERED list of what the packet contains. Numbering that
    -- is not a permutation of 1..n is a partially-filled array: a lone entry at
    -- ordinal 99 says ninety-eight documents belong here and are absent, and the
    -- append-only rule means they can never be added. Requiring a non-empty
    -- manifest is not the same as requiring a complete one.
    --
    -- What is deliberately NOT checked here is the shape of `content_hash`.
    -- Nothing in this repository writes a manifest entry yet, so any format rule
    -- would be a format this project invented at the constraint rather than at
    -- the producer, and the first real generator would have to relax it. The
    -- binding of a manifest entry to a real artefact is a gap, not a guard.
    if lo <> 1 or hi <> entries then
        raise exception
            'INV-10 (%): packet % is approved over % manifest entries numbered % to %, '
            'so the manifest is not the ordered list a generator produced',
            tg_name, pv.id, entries, lo, hi;
    end if;

    select count(*) into marks
      from mark m
      join holding h on h.id = m.holding_id
     where h.fund_id   = pv.fund_id
       and m.period_id = pv.period_id;

    if marks = 0 then
        raise exception
            'INV-10 (%): packet % is approved over no mark at all for fund % at period %',
            tg_name, pv.id, pv.fund_id, pv.period_id;
    end if;

    -- Only the latest revision needs an approval: an earlier revision is
    -- superseded, and requiring every revision would make a correction
    -- unapprovable (INV-5 — a correction is a new revision, never an edit).
    --
    -- The lower approval must also be at THIS policy version (SPEC 6.3/§12). A
    -- v2 packet resting on v1 valuation approvals exports judgements made under
    -- a policy the packet does not claim, and a policy change that alters
    -- sufficiency would be invisible in the deliverable.
    select m.holding_id into unapproved
      from mark m
      join holding h on h.id = m.holding_id
     where h.fund_id   = pv.fund_id
       and m.period_id = pv.period_id
       and m.revision = (select max(m2.revision) from mark m2
                          where m2.holding_id = m.holding_id
                            and m2.period_id  = m.period_id)
       and not exists (select 1 from review_decision d
                        where d.decision_type  = 'valuation'
                          and d.status         = 'approved'
                          and d.mark_id        = m.id
                          and d.policy_version = new.policy_version)
     order by m.holding_id
     limit 1;

    if unapproved is not null then
        raise exception
            'INV-10 (%): packet % is approved while holding % carries no approved '
            'valuation for that period at policy version %',
            tg_name, pv.id, unapproved, new.policy_version;
    end if;
    return null;
end;
$$;

create constraint trigger packet_approval_needs_lower_approvals
    after insert on review_decision
    deferrable initially deferred
    for each row execute function require_packet_prerequisites();

-- INV-10 · the manifest is SEALED at approval, the same rule `decision_evidence`
-- already follows. Append-only blocks UPDATE and DELETE; INSERT is how a blessed
-- packet grows contents nobody approved.
create or replace function seal_packet_manifest() returns trigger
language plpgsql as $$
begin
    if exists (select 1 from review_decision d
                where d.packet_id     = new.packet_id
                  and d.decision_type = 'packet'
                  and d.status        = 'approved')
    then
        raise exception
            'INV-10 (%): packet % is approved; a further entry requires a new packet version',
            tg_name, new.packet_id;
    end if;
    return new;
end;
$$;

create trigger packet_manifest_sealed
    before insert on packet_manifest_entry
    for each row execute function seal_packet_manifest();

-- The manifest's primary key is (packet_id, path), so two documents could sit at
-- the same ordinal and the contiguity rule above would still see 1..n. Position
-- is part of what the manifest asserts; two files at position 3 is not an order.
alter table packet_manifest_entry
    add constraint packet_manifest_ordinal_unique unique (packet_id, ordinal);

-- INV-10 · `packet_version` was missing from 0002's append-only list, so `state`
-- and `policy_version` could be rewritten under an approval that named them.
-- Every other constituent of an approval fingerprint is append-only; this one
-- was the hole.
create trigger packet_version_append_only
    before update or delete on packet_version
    for each row execute function reject_mutation();

-- ── Identity agreement across fund, period, holding and packet ───────────
-- A Fund I packet could reference a Fund II period: `packet_version` carried
-- fund_id and period_id as independent foreign keys, and nothing required them
-- to describe the same fund. The same hole exists wherever a row names a holding
-- and a period side by side.
alter table reporting_period
    add constraint reporting_period_id_fund_unique unique (id, fund_id);

alter table packet_version
    add constraint packet_period_same_fund
    foreign key (period_id, fund_id) references reporting_period (id, fund_id);

-- `mark`, `pbc_requirement`, `valuation_policy_decision` and `workflow_run` reach
-- the fund through the holding rather than carrying fund_id, so the agreement is
-- checked rather than declared. Adding a fund_id column to append-only tables
-- would denormalise the very identity being verified.
create or replace function require_same_fund() returns trigger
language plpgsql as $$
declare
    h  text := to_jsonb(new) ->> 'holding_id';
    p  text := to_jsonb(new) ->> 'period_id';
    hf text;
    pf text;
begin
    if h is null or p is null then
        return new;
    end if;
    select fund_id into hf from holding where id = h;
    select fund_id into pf from reporting_period where id = p;
    if hf is distinct from pf then
        raise exception
            'INV-20 (%): holding % belongs to fund %, but period % belongs to fund %',
            tg_name, h, hf, p, pf;
    end if;
    return new;
end;
$$;

-- INSERT is not the only way to introduce the disagreement. `mark`,
-- `pbc_requirement` and `valuation_policy_decision` are append-only, so an
-- UPDATE on those is already refused — but `workflow_run` is not on that list,
-- because a run legitimately changes `state`. A valid run was therefore UPDATEd
-- onto another fund's period, proven on the live database. Firing on UPDATE too
-- costs nothing on the three append-only tables and closes the one real hole.
do $$
declare t text;
begin
    foreach t in array array[
        'mark', 'pbc_requirement', 'valuation_policy_decision', 'workflow_run'
    ] loop
        execute format(
            'create trigger %I_same_fund before insert or update on %I'
            ' for each row execute function require_same_fund()', t, t);
    end loop;
end;
$$;

commit;
