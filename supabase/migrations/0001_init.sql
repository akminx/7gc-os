-- 0001_init.sql — 7GC OS Valuation Evidence Ledger
--
-- This schema is where INVARIANTS.md stops being prose. Every constraint below
-- names the invariant it enforces. A distinction that lives only in application
-- code can be collapsed by an agent making a red test go green; a distinction
-- enforced here cannot.
--
-- Reference: docs/SPEC.md §6 (data model), §6.1 (attribute ownership),
-- §6.2 (state machines), §6.3 (approvable resources).

begin;

-- ── Typed vocabularies ───────────────────────────────────────────────────
-- Enums, not free text. INV-2: a verdict must never be comparable with `>`,
-- and an unenumerated value must fail rather than default.

create type audit_scope        as enum ('packet', 'lineage_only');
create type position_type      as enum ('direct_equity', 'indirect_feeder',
                                        'public_listed', 'fx_denominated_interest');
create type source_class       as enum ('executed_transaction_doc', 'company_cap_table',
                                        'company_communication', 'administrator_statement',
                                        'public_market_quote', 'third_party_valuation_memo',
                                        'press', 'rumor');
create type execution_status   as enum ('executed', 'pro_forma', 'non_binding',
                                        'unexecuted_referenced', 'not_applicable');
create type requirement_code   as enum ('R1', 'R2', 'R3', 'R4', 'R5');
create type requirement_verdict as enum ('not_assessed', 'not_applicable', 'missing',
                                         'insufficient', 'partial', 'conflicting', 'sufficient');
create type derivation_status  as enum ('derivable', 'not_derivable');
create type valuation_basis    as enum ('cost', 'last_round', 'third_party_memo',
                                        'quoted_price', 'administrator_nav', 'realization');
create type gap_kind           as enum ('with_counsel', 'referenced_location_unspecified',
                                        'not_located');
create type decision_type      as enum ('transcription', 'valuation',
                                        'management_assessment', 'packet');
create type decision_status    as enum ('draft', 'approved', 'rejected', 'superseded');
create type fact_state         as enum ('candidate', 'canonical', 'approved');

-- ── Funds, companies, holdings, lots ─────────────────────────────────────

create table fund (
    id          text primary key,
    legal_name  text not null
);

create table company (
    id          text primary key,
    display_name text not null
);

create table company_alias (
    company_id  text not null references company (id),
    alias       text not null,
    primary key (company_id, alias)
);

create table holding (
    id             text primary key,
    fund_id        text not null references fund (id),
    company_id     text not null references company (id),
    position_type  position_type not null,
    -- INV-11: a currency-bearing position must say which currency.
    currency       char(3) not null default 'USD',
    unique (fund_id, company_id)
);

-- INV-7 · held-at-date ≠ active-today.
-- Lots are IMMUTABLE and carry their own acquisition and realisation dates, so
-- "was this held at date D" is computable rather than a mutable flag. A
-- holding-level `active` boolean cannot represent a second tranche acquired
-- later, or a partial realisation — both of which occur in the corpus.
--
-- INV-17 · security class A ≠ security class B for valuation.
-- security_class is required so cross-class pricing is detectable rather than
-- silently propagated.
create table lot (
    id              text primary key,
    holding_id      text not null references holding (id),
    security_class  text not null,
    -- INV-11 · shares are integers — and a fractional count must be REJECTED,
    -- not coerced. `bigint` silently rounds 100.5 to 101, which is the exact
    -- silent-rounding behaviour SPEC V13 forbids. `numeric` preserves the
    -- fractional value long enough for the check to refuse it.
    shares          numeric(24, 6),
    entry_pps       numeric(20, 6),
    cost_amount     numeric(20, 4) not null,
    cost_currency   char(3) not null,
    acquired_date   date not null,
    realized_date   date,
    -- A lot either has both share inputs or neither. Fund and feeder interests
    -- legitimately have neither; a half-populated lot is a data error.
    constraint lot_shares_and_pps_together
        check ((shares is null) = (entry_pps is null)),
    constraint lot_realized_after_acquired
        check (realized_date is null or realized_date >= acquired_date),
    constraint lot_shares_non_negative
        check (shares is null or shares >= 0),
    constraint lot_shares_whole
        check (shares is null or shares = trunc(shares))
);

create index lot_holding_dates_idx on lot (holding_id, acquired_date, realized_date);

-- A security class conversion (Sway's recapitalisation). Recorded as an event
-- rather than by mutating the lot, so class-at-date stays derivable and the
-- original acquisition lineage survives — the r6 bug where conversion erased a
-- with_counsel gap came from resolving gaps against the current class.
create table lot_conversion (
    lot_id             text primary key references lot (id),
    effective_date     date not null,
    to_security_class  text not null,
    to_shares          numeric(24, 6) not null,
    exchange_ratio     numeric(20, 8) not null,
    constraint conversion_shares_positive check (to_shares > 0),
    -- Sway's 800,000 x 1.09375 = 875,000 exactly. A ratio producing a
    -- fractional result fails rather than rounding into a plausible number.
    constraint conversion_shares_whole check (to_shares = trunc(to_shares))
);

-- ── Periods ──────────────────────────────────────────────────────────────
-- INV-20 · audit measurement date ≠ lineage-only tracker period.
-- audit_scope is explicit and never inferred from cadence or column name. A
-- lineage-only period may serve as the R3 predecessor observation but never
-- generates a requirement or enters packet completeness.
create table reporting_period (
    id            text primary key,
    fund_id       text not null references fund (id),
    period_date   date not null,
    audit_scope   audit_scope not null,
    label         text not null,
    unique (fund_id, period_date)
);

-- ── Source artifacts and claims ──────────────────────────────────────────
-- INV-15 · transport ≠ authority, and authority lives on the CLAIM.
-- One physical artifact may carry several claims of differing authority: an
-- administrator statement arriving by email is an administrator statement, not
-- a company communication. Storing source_class on the file would let a whole
-- PDF lend its strongest class to every fact extracted from it.
create table source_file (
    id            text primary key,
    filename      text not null,
    content_hash  text not null unique,
    byte_size     bigint not null,
    bytes         bytea not null,
    ingested_at   timestamptz not null default now()
);

create table document_version (
    id              text primary key,
    source_file_id  text not null references source_file (id),
    canonical_text  text not null,
    extractor       text not null,          -- pinned tool + version (SPEC §8)
    text_hash       text not null,
    page_count      int not null,
    unique (source_file_id, text_hash)
);

create table claim (
    id                   text primary key,
    document_version_id  text not null references document_version (id),
    holding_id           text not null references holding (id),
    claim_key            text not null,     -- e.g. dream/series_b_price
    source_class         source_class not null,
    execution_status     execution_status not null,
    -- INV-3: three distinct instants, never one `date` column.
    issued_date          date not null,
    as_of_date           date,
    received_date        date,
    -- INV-16: the source-stated reliance window. Capsule's memo forbids later
    -- reliance; without this the memo can be re-linked to a later date with
    -- every date field correct and still be invalid.
    applicable_from      date not null,
    applicable_to        date,
    priced_class         text,
    price_per_share      numeric(20, 6),
    stated_amount        numeric(20, 4),
    stated_currency      char(3),
    supersedes_claim_id  text references claim (id),
    constraint claim_window_ordered
        check (applicable_to is null or applicable_to >= applicable_from),
    constraint claim_amount_currency_together
        check ((stated_amount is null) = (stated_currency is null))
);

create index claim_lookup_idx on claim (holding_id, claim_key, applicable_from);

-- Document gaps are OBSERVATIONS, not permanent properties (INV-12).
-- A with_counsel document can later be retrieved, so current remediation state
-- is tracked separately from the immutable observation.
create table document_gap (
    id               bigserial primary key,
    holding_id       text not null references holding (id),
    requirement      requirement_code not null,
    security_class   text,
    missing_document text not null,
    kind             gap_kind not null,
    source_quote     text not null,
    observed_at      timestamptz not null default now()
);

-- ── Marks ────────────────────────────────────────────────────────────────
-- INV-5 · a mark at a new date is a NEW assertion.
-- Keyed (holding, period) with no carry-forward write path. Re-using a source
-- document across dates is legitimate; re-using an assessment is not.
--
-- INV-13 · reported ≠ validated ≠ supported.
-- Three orthogonal facts that must never share a field. Because Market's
-- arithmetic reproduces perfectly from the tracker and is still not derivable:
-- reproducible arithmetic is not evidentiary support.
create table mark (
    id                  bigserial primary key,
    holding_id          text not null references holding (id),
    period_id           text not null references reporting_period (id),
    revision            int not null default 1,
    reported_amount     numeric(20, 4) not null,
    reported_currency   char(3) not null,
    validated_amount    numeric(20, 4),
    validated_currency  char(3),
    derivation_status   derivation_status not null,
    derivation_reason   text not null,
    basis               valuation_basis,
    created_at          timestamptz not null default now(),
    unique (holding_id, period_id, revision),
    constraint mark_validated_currency_together
        check ((validated_amount is null) = (validated_currency is null)),
    -- A derivable mark must actually carry the derived amount.
    constraint mark_derivable_has_amount
        check (derivation_status <> 'derivable' or validated_amount is not null)
);

-- ── Evidence and requirements ────────────────────────────────────────────

create table pbc_requirement (
    id           bigserial primary key,
    holding_id   text not null references holding (id),
    period_id    text not null references reporting_period (id),
    requirement  requirement_code not null,
    applicable   boolean not null,
    unique (holding_id, period_id, requirement)
);

-- INV-5: every mark revision requires its OWN dated assessment. An assessment
-- is never inherited from a prior period.
create table evidence_assessment (
    id              bigserial primary key,
    requirement_id  bigint not null references pbc_requirement (id),
    mark_id         bigint not null references mark (id),
    revision        int not null default 1,
    verdict         requirement_verdict not null,
    reason_codes    text[] not null default '{}',
    next_actions    text[] not null default '{}',
    policy_version  text not null,
    assessed_at     timestamptz not null default now(),
    unique (requirement_id, mark_id, revision)
);

create table evidence_link (
    assessment_id  bigint not null references evidence_assessment (id),
    claim_id       text not null references claim (id),
    -- INV-3: set when the evidence post-dates the measurement date. Legitimate,
    -- but it must be labelled rather than presented as contemporaneous.
    is_subsequent  boolean not null default false,
    primary key (assessment_id, claim_id)
);

-- ── Facts: candidate → canonical → approved ──────────────────────────────
-- INV-14 · candidate extraction ≠ canonical fact ≠ approved assertion.
-- The product promise is "AI proposes, human disposes". Enforced by FK
-- direction and a state column, not by application convention: a schema-valid,
-- perfectly cited candidate still cannot reach a packet before promotion.
create table extracted_fact (
    id              bigserial primary key,
    claim_id        text not null references claim (id),
    state           fact_state not null default 'candidate',
    field_name      text not null,
    value_text      text not null,
    value_numeric   numeric(20, 6),
    -- INV-8: a source fact resolves VERBATIM to an immutable version.
    citation_quote  text not null,
    span_start      int not null,
    span_end        int not null,
    promoted_by     bigint,                 -- FK added after decision table
    constraint fact_span_ordered check (span_end > span_start),
    constraint fact_promoted_requires_decision
        check (state = 'candidate' or promoted_by is not null)
);

-- INV-8 · source fact ≠ derived figure.
-- A computed total appears verbatim in no document. Derived figures resolve
-- through a typed computation whose complete leaf set is cited source facts.
create table derived_figure (
    id           bigserial primary key,
    label        text not null,
    operator     text not null,
    amount       numeric(20, 4) not null,
    currency     char(3) not null,
    unit         text not null
);

create table derived_figure_input (
    figure_id   bigint not null references derived_figure (id),
    fact_id     bigint references extracted_fact (id),
    child_id    bigint references derived_figure (id),
    ordinal     int not null,
    primary key (figure_id, ordinal),
    -- Every leaf is either a cited fact or another derived figure. Never neither.
    constraint input_exactly_one_source
        check ((fact_id is null) <> (child_id is null))
);

-- ── Decisions ────────────────────────────────────────────────────────────
-- INV-18 · independent state machines never share authorization semantics.
-- SPEC §6.3: four typed decisions, none implying another. Approving a faithful
-- transcription is not approving a fair value — without that split the packet
-- must either hide an unsupported figure or bless it.
--
-- INV-10 · approval binds an immutable input AND policy snapshot.
-- The fingerprint covers mark revision, evidence set and policy version, so an
-- approval cannot survive a change to any constituent.
create table review_decision (
    id                bigint generated always as identity primary key,
    decision_type     decision_type not null,
    status            decision_status not null,
    subject_kind      text not null,
    subject_id        text not null,
    mark_revision     text,
    evidence_set_hash text,
    policy_version    text,
    actor_id          text not null,
    decided_at        timestamptz not null default now(),
    notes             text,
    -- A valuation approval is meaningless without its full identity.
    constraint valuation_approval_fully_fingerprinted
        check (
            decision_type <> 'valuation'
            or status <> 'approved'
            or (mark_revision is not null
                and evidence_set_hash is not null
                and policy_version is not null)
        )
);

alter table extracted_fact
    add constraint fact_promoted_by_fk
    foreign key (promoted_by) references review_decision (id);

-- ── Packets ──────────────────────────────────────────────────────────────
create table packet_version (
    id             text primary key,
    fund_id        text not null references fund (id),
    period_id      text not null references reporting_period (id),
    state          text not null,
    schema_version text not null,
    policy_version text not null,
    generator_ref  text not null,
    created_at     timestamptz not null default now()
);

create table packet_manifest_entry (
    packet_id    text not null references packet_version (id),
    path         text not null,
    content_hash text not null,
    ordinal      int not null,
    primary key (packet_id, path)
);

-- ── Workflow trace ───────────────────────────────────────────────────────
create table workflow_run (
    id          text primary key,
    holding_id  text references holding (id),
    period_id   text references reporting_period (id),
    started_at  timestamptz not null default now(),
    state       text not null
);

create table workflow_event (
    id              bigserial primary key,
    run_id          text not null references workflow_run (id),
    step            text not null,
    detail          jsonb not null default '{}',
    idempotency_key text not null,
    occurred_at     timestamptz not null default now(),
    unique (run_id, idempotency_key)
);

-- ── Append-only enforcement ──────────────────────────────────────────────
-- INV-10 and INV-14 are only real if the database refuses the mutation.
-- Revoking privileges alone is insufficient: the owner role bypasses grants,
-- so these are triggers.

create or replace function reject_mutation() returns trigger
language plpgsql as $$
begin
    raise exception
        'INV-10/INV-14: % is append-only; create a new revision instead of %ing it',
        tg_table_name, lower(tg_op);
end;
$$;

create trigger review_decision_append_only
    before update or delete on review_decision
    for each row execute function reject_mutation();

create trigger workflow_event_append_only
    before update or delete on workflow_event
    for each row execute function reject_mutation();

-- INV-7: lots are immutable, so held-at-date can never be rewritten under a
-- previously approved mark.
create trigger lot_immutable
    before update or delete on lot
    for each row execute function reject_mutation();

create trigger packet_manifest_immutable
    before update or delete on packet_manifest_entry
    for each row execute function reject_mutation();

commit;
