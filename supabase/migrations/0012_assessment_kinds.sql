-- 0012_assessment_kinds.sql — three of the letter's requests had one place to land
--
-- Harwell & Kent ask for three DIFFERENT documents written by management:
--
--   ¶2   "management's memo describing the basis of the mark"
--   ¶3b  "management's assessment that the last round price remains
--         representative of fair value at each subsequent measurement date"
--   closing  "a calibration assessment for positions held at an unchanged mark
--             for more than twelve months"
--
-- `review_decision.decision_type` had ONE value for all three:
-- `management_assessment`. So a fund that wrote only the basis memo would have
-- answered every one of them, and no query could say which artefact it actually
-- wrote. `scripts/acceptance.py` reported those three limbs as NOT EXPRESSIBLE
-- and exited non-zero rather than score them — a clause the ledger cannot record
-- is a defect in this system, not a gap in the fund's records.
--
-- WHY A DISCRIMINATOR RATHER THAN THREE NEW `decision_type` VALUES. Two
-- constraints and one trigger already branch on `decision_type =
-- 'management_assessment'` (0001's `management_assessment_binds_mark`, 0002's
-- `require_evidence_set`), and splitting the value would have required rewriting
-- each of them to list three. A rule restated in three places is a rule that
-- drifts; the type stays one thing and the KIND says which of the three it is.
--
-- NO BACKFILL. `review_decision` holds no `management_assessment` row in any
-- schema — the corpus contains none, which is precisely the finding ¶2, ¶3b and
-- the closing paragraph are reporting. So the constraint can be strict from the
-- first row rather than nullable-and-someday-tightened.

begin;

create type assessment_kind as enum (
    -- ¶2 · what the mark is based on, where the basis is not a financing round.
    'basis_memo',
    -- ¶3(b) · that the LAST round's price still represents fair value, at a
    -- measurement date after that round. A different claim from the basis memo:
    -- one says what was done, the other says it still holds.
    'representativeness',
    -- The closing paragraph's RECOMMENDATION, distinguished from ¶3(b) by verb —
    -- "we continue to recommend" against "please provide" — and by trigger: more
    -- than twelve months at an unchanged mark, not merely a subsequent date.
    'calibration'
);

alter table review_decision add column assessment_kind assessment_kind;

-- BOTH DIRECTIONS. Without the second half a valuation approval could carry an
-- assessment kind, which would read as an answer to ¶3(b) on a row that is not a
-- management assessment at all.
alter table review_decision
    add constraint management_assessment_states_its_kind
    check (decision_type <> 'management_assessment' or assessment_kind is not null),
    add constraint only_a_management_assessment_has_a_kind
    check (assessment_kind is null or decision_type = 'management_assessment');

-- ── ¶3(b) names its own contents ─────────────────────────────────────────
-- "(including consideration of company performance, market conditions, and any
-- indicators of impairment)" — three things the assessment must CONTAIN, not
-- merely that one exists. Nothing checked them, and nothing could: the contents
-- of a document cannot be verified while the document is indistinguishable from
-- two others. That is fixed above, so this is now buildable.
--
-- A TABLE rather than three columns, for the reason `evidence_link` is a table:
-- an assessment that considered two of the three is a real and reportable state,
-- and three booleans would make "considered" and "recorded as considered" the
-- same fact. Each row carries the note that says WHAT was considered, so an
-- auditor reads the consideration rather than a checkbox.
create type assessment_consideration as enum (
    'company_performance',
    'market_conditions',
    'impairment_indicators'
);

create table assessment_consideration_record (
    decision_id   bigint not null references review_decision (id),
    consideration assessment_consideration not null,
    note          text not null,
    primary key (decision_id, consideration),
    -- An empty note is a checkbox wearing a sentence's clothes.
    constraint consideration_note_is_not_blank check (length(trim(note)) > 0)
);

-- Append-only, like every other constituent of an approval. A consideration
-- edited after the fact would let an assessment's contents change while the
-- assessment it belongs to stayed immutable, which is the hole 0002's list
-- exists to close.
create trigger assessment_consideration_record_append_only
    before update or delete on assessment_consideration_record
    for each row execute function reject_mutation();

-- A consideration can only hang off the assessment kind that owes one. ¶3(b) is
-- the clause with the parenthetical; a basis memo and a calibration assessment
-- are not asked for these three, and letting them carry considerations would
-- make the ¶3(b) check answerable by the wrong document.
create or replace function consideration_belongs_to_a_representativeness_assessment()
returns trigger language plpgsql as $$
declare kind assessment_kind;
begin
    select assessment_kind into kind from review_decision where id = new.decision_id;
    if kind is distinct from 'representativeness' then
        raise exception
            '¶3(b): a consideration belongs to a representativeness assessment, not %',
            coalesce(kind::text, 'a decision that is not a management assessment');
    end if;
    return new;
end;
$$;

create trigger consideration_kind_is_checked
    before insert on assessment_consideration_record
    for each row execute function consideration_belongs_to_a_representativeness_assessment();

commit;
