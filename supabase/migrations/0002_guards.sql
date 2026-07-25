-- 0002_guards.sql — cross-row invariants that a column CHECK cannot express
--
-- Split from 0001 when it passed the 600-line file budget. 0001 declares the
-- shape; this file declares what the database must REFUSE. Keeping the refusals
-- together makes it obvious when a table has no guard at all.

begin;

-- ── Append-only enforcement ──────────────────────────────────────────────
-- INV-10 and INV-14 are only real if the database refuses the mutation.
-- Revoking privileges alone is insufficient: the owner role bypasses grants,
-- so these are triggers.
--
-- Every constituent of an approval fingerprint appears here. If any one of them
-- stayed mutable, the approval would still name a row whose contents had since
-- changed — which is the failure this whole section exists to prevent.

create or replace function reject_mutation() returns trigger
language plpgsql as $$
begin
    raise exception
        'INV-10/INV-14: % is append-only; create a new revision instead of %ing it',
        tg_table_name, lower(tg_op);
end;
$$;

do $$
declare t text;
begin
    foreach t in array array[
        'lot', 'lot_conversion', 'source_file', 'document_version', 'claim',
        'document_gap', 'document_gap_remediation',
        'mark', 'evidence_assessment', 'evidence_link',
        'extracted_fact', 'derived_figure', 'derived_figure_input',
        'valuation_policy_decision', 'review_decision', 'decision_evidence',
        'packet_manifest_entry', 'workflow_event'
    ] loop
        execute format(
            'create trigger %I_append_only before update or delete on %I'
            ' for each row execute function reject_mutation()', t, t);
    end loop;
end;
$$;

-- ── Cross-row invariants that a CHECK cannot express ─────────────────────

-- INV-10: an approved valuation or management assessment must name the evidence
-- set it approved. SPEC §6.3 / V12 binds both to an evidence set, not only the
-- valuation. Deferred, because the bridge rows are written after the decision.
create or replace function require_evidence_set() returns trigger
language plpgsql as $$
begin
    if new.decision_type in ('valuation', 'management_assessment')
       and new.status = 'approved'
       and not exists (select 1 from decision_evidence d where d.decision_id = new.id)
    then
        raise exception
            'INV-10: % approval % names no evidence set', new.decision_type, new.id;
    end if;
    return null;
end;
$$;

create constraint trigger valuation_approval_names_evidence
    after insert on review_decision
    deferrable initially deferred
    for each row execute function require_evidence_set();

-- INV-17: pricing one security class off another's evidence requires a cited
-- policy decision.
--
-- Cross-class is DERIVED from the evidence actually cited, never read from a
-- flag on the mark. A boolean the writer sets is a guard the writer can decline
-- to trip: leaving it false while pricing across classes would skip the check
-- entirely. Here the trigger compares the priced_class of every cited claim
-- against the classes the holding actually held at the measurement date.
create or replace function require_cross_class_policy() returns trigger
language plpgsql as $$
declare
    m        mark%rowtype;
    measured date;
    held     text[];
    priced   text;
begin
    if new.decision_type <> 'valuation' or new.status <> 'approved' then
        return null;
    end if;
    select * into m from mark where id = new.mark_id;
    select period_date into measured from reporting_period where id = m.period_id;

    -- Classes held at the measurement date, post-conversion (INV-7 / INV-17).
    select array_agg(distinct coalesce(lc.to_security_class, l.security_class))
      into held
      from lot l
      left join lot_conversion lc
             on lc.lot_id = l.id and lc.effective_date <= measured
     where l.holding_id = m.holding_id
       and l.acquired_date <= measured
       and (l.realized_date is null or l.realized_date > measured);

    -- Every claim that PRICES the mark, whether or not it states a class. The
    -- first version filtered `priced_class is not null`, so a cap-table extract
    -- carrying a price with the class left implicit skipped the gate entirely —
    -- the normal shape of that document, not an exotic one.
    for priced in
        select distinct c.priced_class
          from decision_evidence de
          join evidence_link el on el.assessment_id = de.assessment_id
          join claim c          on c.id = el.claim_id
         where de.decision_id = new.id
           and c.price_per_share is not null
    loop
        if priced is null then
            -- Unstated is not "same class". Whether this is cross-class pricing
            -- is unknowable from the evidence, and an unknowable answer must
            -- refuse rather than assume the convenient one.
            raise exception
                'INV-17: mark % is priced by a claim that states no priced_class, '
                'so cross-class pricing cannot be ruled out', m.id;
        end if;
        if held is null or not (priced = any (held)) then
            if not exists (
                select 1 from valuation_policy_decision p
                 where p.holding_id = m.holding_id
                   and p.period_id  = m.period_id
                   and p.from_class = priced
                   and p.to_class   = any (coalesce(held, array[]::text[])))
            then
                raise exception
                    'INV-17: mark % is priced from class %, which it does not hold, '
                    'with no cited cross-class policy decision', m.id, priced;
            end if;
        end if;
    end loop;
    return null;
end;
$$;

create constraint trigger valuation_approval_needs_class_policy
    after insert on review_decision
    deferrable initially deferred
    for each row execute function require_cross_class_policy();

-- INV-10: an approval's evidence set is SEALED at the decision.
--
-- Both deferred triggers fire `after insert on review_decision`, so evidence
-- attached afterwards was never re-checked: an approval could pass the
-- cross-class and evidence-set gates and then grow new evidence that would have
-- failed them. `decision_evidence` was append-only against UPDATE and DELETE,
-- which made that growth look principled.
--
-- Evidence may therefore only be attached in the same transaction that created
-- the decision. Adding evidence later is a new assertion about value, and a new
-- assertion needs a new decision — the same rule marks already follow.
create or replace function seal_evidence_set() returns trigger
language plpgsql as $$
declare created_here boolean;
begin
    select r.xmin = pg_current_xact_id()::xid into created_here
      from review_decision r where r.id = new.decision_id;
    if created_here is distinct from true then
        raise exception
            'INV-10: decision % is sealed; attaching evidence requires a new decision',
            new.decision_id;
    end if;
    return new;
end;
$$;

create trigger decision_evidence_sealed
    before insert on decision_evidence
    for each row execute function seal_evidence_set();

-- SPEC 7.1 · the same rule for the assessment's verdict. `not_applicable` on an
-- always-applicable requirement is the database form of the contradiction the
-- contract layer now cannot express.
create or replace function reject_na_on_always_applicable() returns trigger
language plpgsql as $$
declare code requirement_code;
begin
    select requirement into code from pbc_requirement where id = new.requirement_id;
    if code in ('R1', 'R2') and new.verdict = 'not_applicable' then
        raise exception
            'SPEC 7.1: % is always applicable and cannot be assessed not_applicable', code;
    end if;
    return new;
end;
$$;

create trigger assessment_always_applicable
    before insert on evidence_assessment
    for each row execute function reject_na_on_always_applicable();

-- INV-16 / INV-3: a claim may only be linked where it is applicable, and
-- is_subsequent must agree with the dates rather than being asserted.
create or replace function check_link_applicability() returns trigger
language plpgsql as $$
declare
    measured date;
    c        claim%rowtype;
begin
    select rp.period_date into measured
      from evidence_assessment ea
      join mark m           on m.id  = ea.mark_id
      join reporting_period rp on rp.id = m.period_id
     where ea.id = new.assessment_id;

    select * into c from claim where id = new.claim_id;

    if measured < c.applicable_from
       or (c.applicable_to is not null and measured > c.applicable_to) then
        raise exception
            'INV-16: claim % is not applicable at % (window % .. %)',
            c.id, measured, c.applicable_from, coalesce(c.applicable_to::text, 'open');
    end if;

    if new.is_subsequent <> (c.issued_date > measured) then
        raise exception
            'INV-3: is_subsequent must equal (issued_date > measurement date) for claim % at %',
            c.id, measured;
    end if;
    return new;
end;
$$;

create trigger evidence_link_applicability
    before insert on evidence_link
    for each row execute function check_link_applicability();

commit;
