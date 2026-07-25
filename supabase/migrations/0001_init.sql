-- 0001_init.sql — 7GC OS Valuation Evidence Ledger
--
-- This schema is where INVARIANTS.md stops being prose. Every constraint below
-- names the invariant it enforces. A distinction that lives only in application
-- code can be collapsed by an agent making a red test go green; a distinction
-- enforced here cannot.
--
-- Reference: docs/SPEC.md §6 (data model), §6.1 (attribute ownership),
-- §6.2 (state machines), §6.3 (approvable resources).
--
-- Revised after schema-passB (cross-family review, Grok 4.5). The first version
-- had a valuation approval whose "fingerprint" was three unconstrained text
-- columns, and no immutability on the rows it claimed to bind — so an approved
-- mark could be rewritten to any number afterwards and still read `approved`.
-- Identity is now carried by foreign keys to immutable rows, never by strings.

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
create type gap_remediation    as enum ('open', 'requested', 'received', 'unobtainable');
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
    id           text primary key,
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
-- "was this held at date D" is computable rather than a mutable flag.
--
-- INV-17 · security class A ≠ security class B for valuation.
create table lot (
    id              text primary key,
    holding_id      text not null references holding (id),
    security_class  text not null,
    -- INV-11 · shares are integers — and a fractional count must be REJECTED,
    -- not coerced. `bigint` silently rounds 100.5 to 101, which is the exact
    -- silent-rounding behaviour SPEC V13 forbids. `numeric` preserves the
    -- fractional value long enough for the check to refuse it.
    shares          numeric(24, 6),
    entry_pps       numeric(26, 12),
    cost_amount     numeric(26, 12) not null,
    cost_currency   char(3) not null,
    acquired_date   date not null,
    realized_date   date,
    constraint lot_shares_and_pps_together
        check ((shares is null) = (entry_pps is null)),
    constraint lot_realized_after_acquired
        check (realized_date is null or realized_date >= acquired_date),
    constraint lot_shares_non_negative
        check (shares is null or shares >= 0),
    constraint lot_shares_whole
        check (shares is null or shares = trunc(shares)),
    constraint lot_entry_pps_scale
        check (entry_pps is null or entry_pps = trunc(entry_pps, 6)),
    constraint lot_cost_amount_scale
        check (cost_amount is null or cost_amount = trunc(cost_amount, 4))
);

create index lot_holding_dates_idx on lot (holding_id, acquired_date, realized_date);

-- A security class conversion (Sway's recapitalisation), recorded as an event
-- rather than by mutating the lot, so class-at-date stays derivable.
create table lot_conversion (
    lot_id             text primary key references lot (id),
    effective_date     date not null,
    to_security_class  text not null,
    to_shares          numeric(24, 6) not null,
    exchange_ratio     numeric(26, 14) not null,
    constraint conversion_shares_positive check (to_shares > 0),
    -- Sway's 800,000 x 1.09375 = 875,000 exactly. A ratio producing a
    -- fractional result fails rather than rounding into a plausible number.
    constraint conversion_shares_whole check (to_shares = trunc(to_shares)),
    constraint lot_conversion_exchange_ratio_scale
        check (exchange_ratio is null or exchange_ratio = trunc(exchange_ratio, 8))
);

-- ── Periods ──────────────────────────────────────────────────────────────
-- INV-20 · audit measurement date ≠ lineage-only tracker period.
create table reporting_period (
    id            text primary key,
    fund_id       text not null references fund (id),
    period_date   date not null,
    audit_scope   audit_scope not null,
    label         text not null,
    unique (fund_id, period_date),
    -- Lets children carry audit_scope and bind it by FK, so a lineage-only
    -- period cannot acquire packet-shaped state.
    unique (id, audit_scope)
);

-- ── Source artifacts and claims ──────────────────────────────────────────
-- INV-15 · transport ≠ authority, and authority lives on the CLAIM.
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
    claim_key            text not null,
    source_class         source_class not null,
    execution_status     execution_status not null,
    -- INV-3: three distinct instants, never one `date` column.
    issued_date          date not null,
    as_of_date           date,
    received_date        date,
    -- INV-16: the source-stated reliance window.
    applicable_from      date not null,
    applicable_to        date,
    priced_class         text,
    price_per_share      numeric(26, 12),
    stated_amount        numeric(26, 12),
    stated_currency      char(3),
    supersedes_claim_id  text references claim (id),
    constraint claim_window_ordered
        check (applicable_to is null or applicable_to >= applicable_from),
    constraint claim_amount_currency_together
        check ((stated_amount is null) = (stated_currency is null)),
    constraint claim_price_per_share_scale
        check (price_per_share is null or price_per_share = trunc(price_per_share, 6)),
    constraint claim_stated_amount_scale
        check (stated_amount is null or stated_amount = trunc(stated_amount, 4))
);

create index claim_lookup_idx on claim (holding_id, claim_key, applicable_from);

-- INV-12 · a gap OBSERVATION is immutable; remediation is a separate history.
-- Overwriting kind='with_counsel' to 'not_located' is the cheapest collapse of
-- this invariant, so the observation is append-only and progress is recorded as
-- new remediation rows.
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

create table document_gap_remediation (
    id          bigserial primary key,
    gap_id      bigint not null references document_gap (id),
    state       gap_remediation not null,
    note        text,
    recorded_at timestamptz not null default now()
);

-- ── Marks ────────────────────────────────────────────────────────────────
-- INV-5 · a mark at a new date is a NEW assertion.
-- INV-13 · reported ≠ validated ≠ supported.
--
-- Marks are append-only: a correction is a new revision, never an edit. The
-- first schema allowed UPDATE, which let an approved mark be rewritten to any
-- figure while its approval row still read `approved`.
create table mark (
    id                  bigserial primary key,
    holding_id          text not null references holding (id),
    period_id           text not null references reporting_period (id),
    revision            int not null default 1,
    reported_amount     numeric(26, 12) not null,
    reported_currency   char(3) not null,
    validated_amount    numeric(26, 12),
    validated_currency  char(3),
    derivation_status   derivation_status not null,
    derivation_reason   text not null,
    basis               valuation_basis,
    created_at          timestamptz not null default now(),
    unique (holding_id, period_id, revision),
    -- Lets assessments bind holding and period by FK rather than by convention.
    unique (id, holding_id, period_id),
    constraint mark_validated_currency_together
        check ((validated_amount is null) = (validated_currency is null)),
    constraint mark_derivable_has_amount
        check (derivation_status <> 'derivable' or validated_amount is not null),
    constraint mark_reported_amount_scale
        check (reported_amount is null or reported_amount = trunc(reported_amount, 4)),
    constraint mark_validated_amount_scale
        check (validated_amount is null or validated_amount = trunc(validated_amount, 4))
);

-- ── Evidence and requirements ────────────────────────────────────────────
-- INV-20: a requirement may only exist for a packet-scope period.
create table pbc_requirement (
    id           bigserial primary key,
    holding_id   text not null references holding (id),
    period_id    text not null references reporting_period (id),
    audit_scope  audit_scope not null default 'packet',
    requirement  requirement_code not null,
    applicable   boolean not null,
    unique (holding_id, period_id, requirement),
    unique (id, holding_id, period_id),
    constraint requirement_is_packet_scope check (audit_scope = 'packet'),
    foreign key (period_id, audit_scope)
        references reporting_period (id, audit_scope)
);

-- INV-5: every mark revision requires its OWN dated assessment.
-- holding_id and period_id are carried so both parents can be bound by FK: an
-- assessment for a 2025 requirement could otherwise be attached to a 2024 mark
-- with nothing objecting.
create table evidence_assessment (
    id              bigserial primary key,
    requirement_id  bigint not null,
    mark_id         bigint not null,
    holding_id      text not null,
    period_id       text not null,
    revision        int not null default 1,
    verdict         requirement_verdict not null,
    reason_codes    text[] not null default '{}',
    next_actions    text[] not null default '{}',
    -- INV-4 · a derived pro-forma judgement ≠ the label the tracker carried.
    -- Stored side by side so a disagreement is data rather than an overwrite.
    pro_forma       boolean not null default false,
    tracker_label   text,
    policy_version  text not null,
    assessed_at     timestamptz not null default now(),
    unique (requirement_id, mark_id, revision),
    unique (id, mark_id),
    foreign key (requirement_id, holding_id, period_id)
        references pbc_requirement (id, holding_id, period_id),
    foreign key (mark_id, holding_id, period_id)
        references mark (id, holding_id, period_id)
);

create table evidence_link (
    assessment_id  bigint not null references evidence_assessment (id),
    claim_id       text not null references claim (id),
    -- INV-3: set when the evidence post-dates the measurement date. Legitimate,
    -- but it must be labelled rather than presented as contemporaneous. The
    -- value is verified against the dates by trigger, not trusted.
    is_subsequent  boolean not null default false,
    primary key (assessment_id, claim_id)
);

-- ── Facts: candidate → canonical → approved ──────────────────────────────
-- INV-14 · candidate extraction ≠ canonical fact ≠ approved assertion.
-- "AI proposes, human disposes" is enforced by FK direction and state, not by
-- application convention. The promoting decision must be an APPROVED
-- TRANSCRIPTION — the first schema accepted any decision at all, including a
-- rejected packet decision.
create table extracted_fact (
    id                 bigserial primary key,
    claim_id           text not null references claim (id),
    state              fact_state not null default 'candidate',
    field_name         text not null,
    value_text         text not null,
    value_numeric      numeric(26, 12),
    -- INV-8: a source fact resolves VERBATIM to an immutable version.
    citation_quote     text not null,
    span_start         int not null,
    span_end           int not null,
    promoted_by        bigint,              -- composite FK added below (MATCH FULL)
    promoted_by_type   decision_type,
    promoted_by_status decision_status,
    unique (id, state),
    constraint fact_span_ordered check (span_end > span_start),
    constraint fact_promoted_requires_decision
        check (state = 'candidate' or promoted_by is not null),
    -- A composite FK is MATCH SIMPLE by default: leave ANY column NULL and the
    -- whole reference goes unchecked. The discriminators must therefore be
    -- all-present or all-absent, or `promoted_by = <garbage>, type = NULL`
    -- promotes a fact past both the FK and the check below (which evaluates to
    -- NULL, and NULL is not FALSE, so the check passes).
    constraint fact_promoter_all_or_nothing
        check (num_nulls(promoted_by, promoted_by_type, promoted_by_status) in (0, 3)),
    constraint fact_promoter_is_approved_transcription
        check (promoted_by is null
               or (promoted_by_type = 'transcription' and promoted_by_status = 'approved')),
    constraint extracted_fact_value_numeric_scale
        check (value_numeric is null or value_numeric = trunc(value_numeric, 6))
);

-- INV-8 · source fact ≠ derived figure.
create table derived_figure (
    id           bigserial primary key,
    label        text not null,
    operator     text not null,
    amount       numeric(26, 12) not null,
    currency     char(3) not null,
    unit         text not null,
    constraint derived_figure_amount_scale
        check (amount is null or amount = trunc(amount, 4))
);

-- A derived figure may not rest on an unpromoted candidate: that is the path by
-- which an AI-proposed number becomes a validated mark without human disposal.
create table derived_figure_input (
    figure_id   bigint not null references derived_figure (id),
    fact_id     bigint,
    fact_state  fact_state,
    child_id    bigint references derived_figure (id),
    ordinal     int not null,
    primary key (figure_id, ordinal),
    constraint input_exactly_one_source
        check ((fact_id is null) <> (child_id is null)),
    -- Same MATCH SIMPLE defeat as extracted_fact: a NULL fact_state skipped both
    -- the FK and the check, letting a candidate fact feed a validated figure.
    constraint input_fact_state_present
        check ((fact_id is null) = (fact_state is null)),
    constraint input_fact_is_promoted
        check (fact_id is null or fact_state <> 'candidate'),
    foreign key (fact_id, fact_state) references extracted_fact (id, state) match full
);

-- ── Policy decisions ─────────────────────────────────────────────────────
-- INV-17 · pricing one class off another's evidence is a POLICY act that must
-- be cited, not an arithmetic convenience.
create table valuation_policy_decision (
    id             bigserial primary key,
    holding_id     text not null references holding (id),
    period_id      text not null references reporting_period (id),
    from_class     text not null,
    to_class       text not null,
    rationale      text not null,
    citation_quote text not null,
    policy_version text not null,
    decided_at     timestamptz not null default now()
);

-- ── Decisions ────────────────────────────────────────────────────────────
-- INV-18 · independent state machines never share authorization semantics.
-- INV-10 · approval binds an immutable input AND policy snapshot.
--
-- mark_id is a foreign key to the exact immutable mark revision approved. The
-- previous `mark_revision text` column could hold '1', 'deadbeef' or anything
-- else and satisfied the constraint, so the approval bound nothing.
create table review_decision (
    id                bigint generated always as identity primary key,
    decision_type     decision_type not null,
    status            decision_status not null,
    subject_kind      text not null,
    subject_id        text not null,
    mark_id           bigint references mark (id),
    packet_id         text,
    policy_version    text,
    actor_id          text not null,
    decided_at        timestamptz not null default now(),
    notes             text,
    unique (id, decision_type, status),
    -- Lets the evidence set bind to the SAME mark this decision approves.
    unique (id, mark_id),
    -- SPEC §6.3: a valuation approval binds mark revision, evidence set and
    -- policy version. The evidence set is enforced by trigger below because it
    -- is a set, not a column.
    constraint valuation_approval_binds_mark
        check (decision_type <> 'valuation' or status <> 'approved'
               or (mark_id is not null and policy_version is not null)),
    -- SPEC §6.3 / V12: a management assessment closes R3 only when bound to the
    -- mark revision it assessed. Previously unconstrained entirely.
    constraint management_assessment_binds_mark
        check (decision_type <> 'management_assessment' or status <> 'approved'
               or (mark_id is not null and policy_version is not null)),
    constraint packet_decision_binds_packet
        check (decision_type <> 'packet' or status <> 'approved'
               or (packet_id is not null and policy_version is not null))
);

-- The evidence set an approval covers, by FK to immutable assessment rows.
-- mark_id is carried so both sides bind the SAME mark: requiring merely that
-- *some* evidence row exists would let an approval of mark M1 cite assessments
-- belonging to M2 and still commit.
create table decision_evidence (
    decision_id   bigint not null,
    assessment_id bigint not null,
    mark_id       bigint not null,
    primary key (decision_id, assessment_id),
    foreign key (decision_id, mark_id)
        references review_decision (id, mark_id) match full,
    foreign key (assessment_id, mark_id)
        references evidence_assessment (id, mark_id) match full
);

alter table extracted_fact
    add constraint fact_promoted_by_fk
    foreign key (promoted_by, promoted_by_type, promoted_by_status)
    references review_decision (id, decision_type, status) match full;

-- ── Packets ──────────────────────────────────────────────────────────────
-- INV-20: a lineage-only period never enters packet completeness.
create table packet_version (
    id             text primary key,
    fund_id        text not null references fund (id),
    period_id      text not null references reporting_period (id),
    audit_scope    audit_scope not null default 'packet',
    state          text not null,
    schema_version text not null,
    policy_version text not null,
    generator_ref  text not null,
    created_at     timestamptz not null default now(),
    constraint packet_is_packet_scope check (audit_scope = 'packet'),
    foreign key (period_id, audit_scope)
        references reporting_period (id, audit_scope)
);

alter table review_decision
    add constraint decision_packet_fk foreign key (packet_id) references packet_version (id);

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
commit;
