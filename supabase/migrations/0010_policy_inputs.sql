-- 0010_policy_inputs.sql — the two things the policy layer asks the ledger for
-- and the ledger could not answer.
--
-- Step 3 reproduces `evals/oracle/derived.json` from the ledger. Two of its
-- inputs had no representation at all, and both are JUDGEMENTS rather than
-- computations, so both are recorded and only their consequences are derived.
--
--   1. Which requirement a claim is relied upon for. Not derivable from
--      `source_class`: Jackpocket's merger notice is an executed transaction
--      document and evidences the EXIT (R4), not the entry, while Poolside's
--      SPA — the same source class — evidences both existence and fair value.
--      Fluidstack's Series A-2 reference is relied upon for nothing at all.
--      A rule keyed on the class alone gets all three wrong.
--
--   2. The material components of a mark, and the dated support each has.
--      SPEC §7.2 limb (b) asks whether AT LEAST ONE material component lacks
--      qualifying support within twelve months. Which parts of a mark are
--      material is a judgement — Moonfare's is an underlying EUR valuation and
--      an FX rate, The Mom Project's is an equity position and a convertible
--      note — and no rule over lots reproduces those names.
--
-- The load-bearing constraint is that support is an ARTEFACT IN THE LEDGER,
-- never a date somebody typed. "The last valuation was March 2023" with nothing
-- behind it is precisely the assertion R3 exists to stop a fund making about
-- its own marks, so a support row must point at a claim or at a lot, and its
-- date must be one that artefact actually carries.

begin;

-- ── Which requirement a claim answers ────────────────────────────────────
-- Declared by the extractor that read the document, because that is where the
-- judgement is made. A claim linked to nothing is legitimate and means "read,
-- classified, relied upon for no requirement" — which is a different statement
-- from "not read", and the document-load guard already refuses the latter.
create table claim_requirement (
    claim_id    text not null references claim (id),
    requirement requirement_code not null,
    primary key (claim_id, requirement),
    -- R3 is closed by a management assessment and R5 is a label derived from
    -- R2's own inputs (INV-4). Neither is answered by pointing at a document,
    -- and allowing the link would create a second, quieter way to satisfy them.
    constraint claim_requirement_is_evidence_bearing
        check (requirement in ('R1', 'R2', 'R4'))
);

create index claim_requirement_by_requirement_idx on claim_requirement (requirement, claim_id);

-- ── Material components of a mark ────────────────────────────────────────
create table valuation_component (
    id          bigserial primary key,
    holding_id  text not null references holding (id),
    component   text not null,
    -- Why this decomposition, in the words of whoever made the call. A
    -- component is a claim about what the number is made of, and an unexplained
    -- one cannot be reviewed.
    rationale   text not null,
    recorded_at timestamptz not null default now(),
    unique (holding_id, component),
    unique (id, holding_id),
    constraint valuation_component_named check (length(trim(component)) > 0)
);

-- Zero support rows is MEANINGFUL: SPEC §7.2 says absent dated support counts
-- as stale. Because Market has no evidence of any kind and must read as stale
-- rather than as satisfied. That is why the absence lives here, as a component
-- with no support, instead of as a missing component — an absent component
-- would make R3 answer "nothing is stale", which is the opposite finding.
create table valuation_component_support (
    id           bigserial primary key,
    component_id bigint not null references valuation_component (id),
    holding_id   text not null,
    claim_id     text references claim (id),
    lot_id       text references lot (id),
    supported_on date not null,
    -- Support is an artefact, never a bare date.
    constraint support_names_exactly_one_artefact
        check (num_nonnulls(claim_id, lot_id) = 1),
    -- The component and its support must concern the same holding. Without
    -- this, a fresh claim about one position could reset the support age of
    -- another and R3 would quietly stop firing for it.
    foreign key (component_id, holding_id) references valuation_component (id, holding_id)
);

create index valuation_component_support_by_component_idx
    on valuation_component_support (component_id, supported_on);

-- The date must be one the artefact carries. Storing `supported_on` separately
-- rather than joining to it at read time is deliberate — a claim's own dates
-- are several (issued, as-of, applicable-from) and which one constitutes
-- support differs by evidence: an administrator statement supports its NAV
-- as-of date, a purchase agreement supports its execution date. So the choice
-- is recorded, and this refuses a choice the artefact cannot justify.
create or replace function support_date_is_the_artefacts_own() returns trigger
language plpgsql as $$
declare
    c record;
    l record;
begin
    if new.claim_id is not null then
        select issued_date, as_of_date, applicable_from, received_date
          into c from claim where id = new.claim_id;
        if new.supported_on not in (
            c.issued_date, coalesce(c.as_of_date, c.issued_date),
            c.applicable_from, coalesce(c.received_date, c.issued_date))
        then
            raise exception
                'R3 support % claims date % which claim % does not carry '
                '(issued %, as-of %, applicable-from %, received %)',
                new.id, new.supported_on, new.claim_id,
                c.issued_date, c.as_of_date, c.applicable_from, c.received_date;
        end if;
    else
        select acquired_date, holding_id into l from lot where id = new.lot_id;
        if new.supported_on <> l.acquired_date then
            raise exception
                'R3 support % claims date % but lot % was acquired %',
                new.id, new.supported_on, new.lot_id, l.acquired_date;
        end if;
        if l.holding_id <> new.holding_id then
            raise exception
                'R3 support % binds lot % of holding % to a component of holding %',
                new.id, new.lot_id, l.holding_id, new.holding_id;
        end if;
    end if;

    if new.claim_id is not null
       and (select holding_id from claim where id = new.claim_id) <> new.holding_id
    then
        raise exception
            'R3 support % binds a claim about % to a component of %',
            new.id, (select holding_id from claim where id = new.claim_id), new.holding_id;
    end if;

    return null;
end;
$$;

create constraint trigger support_date_is_the_artefacts_own
    after insert on valuation_component_support
    deferrable initially deferred
    for each row execute function support_date_is_the_artefacts_own();

commit;
