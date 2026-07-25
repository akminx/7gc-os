-- 0007 — three guards that answered the right question over the wrong set.
--
-- Each was proven by execution against this database before it was written, and
-- each is the same shape: a predicate that reads every row of a table where it
-- should read a subset, so a row nobody asked about changes an audited answer.
-- 0001-0006 are already applied and are not edited.
--
-- ── 1 · the realisation window opened at the wrong period ────────────────
--
-- `held_during_reported_period` (0005) opens the interval at the fund's
-- previous `reporting_period.period_date` of ANY scope. SPEC 2 / INV-20 make
-- the audited cadence the PACKET dates; the other six periods the tracker
-- carries are lineage-only and nobody asked about them. So a lineage-only date
-- sitting between two packet dates narrowed the window, and the guard refused a
-- mark it should take. Reproduced on Jackpocket's exact shape — a lot acquired
-- 2023-01-01 and realised 2024-05-20, with the packet date 2024-12-31:
--
--   with the lineage-only 24Q2 period present:  INSERT REFUSED
--   with that one period deleted:               the identical INSERT ACCEPTED
--
-- The oracle has always used the previous PACKET date (`_prev_packet_date`,
-- feeding `realized_in_window`), and it derives R4 = `sufficient` for
-- jackpocket at fund_ii 2024-12-31 off the merger notice. An
-- `evidence_assessment` binds to a `mark`, so refusing that mark deletes the
-- only row R4 could ever be assessed against, and 3,100,000 of realised value
-- becomes permanently unevidenceable — against the audit letter's request #4,
-- and the precise failure 0005's own header set out to avoid. Two sides
-- contradicting each other on the same facts; the schema is the wrong one.
--
-- ── 2 · an R1 document's price counted as pricing the mark ───────────────
--
-- `require_cross_class_policy` (0006) collects the priced classes from every
-- claim cited by the approval, whatever requirement its assessment answers. An
-- executed-transaction document supporting R1 (existence and cost) states the
-- acquisition PPS, so it supplied a priced class the fair-value evidence never
-- covered. Proven, with the control beside it:
--
--   held {series_a, series_b}, R2 prices series_b, no R1 claim   -> REFUSED
--   the same, plus an R1 claim carrying series_a's PPS           -> ACCEPTED
--
-- INV-17 asks whether the fair-value MARK propagates one class's price across
-- another's shares. Only the evidence relied on for fair value can answer that,
-- which is what the oracle's `r2()` reads. A historical acquisition price is
-- not a mark, and letting it close the set hides exactly the case INV-17 exists
-- for: series_b shares carried at the series_c price.
--
-- ── 3 · a superseded policy decision authorised a current approval ───────
--
-- The cross-class carve-out looks up `valuation_policy_decision` by holding,
-- period and class pair, and never by `policy_version`. So a decision recorded
-- under v0 cleared an approval taken under v1:
--
--   no decision at all         -> REFUSED
--   decision recorded under v1 -> ACCEPTED
--   decision recorded under v0 -> ACCEPTED
--
-- 0003 already requires `ea.policy_version = new.policy_version` for every
-- cited assessment, so this repository's own rule is that an approval's inputs
-- are read under the approval's policy. Enforcing it for assessments and not
-- for policy decisions is one-side-only enforcement inside a single guard.

begin;

-- ── 1 ────────────────────────────────────────────────────────────────────
create or replace function held_during_reported_period(
    p_holding text, p_period_id text
) returns boolean
language plpgsql as $$
declare
    measured date;
    fund     text;
    opened   date;
begin
    -- Not computable: no lot to compute it from. See 0005's header.
    if not exists (select 1 from lot l where l.holding_id = p_holding) then
        return true;
    end if;

    select rp.period_date, rp.fund_id into measured, fund
      from reporting_period rp where rp.id = p_period_id;
    -- A period that does not exist is the foreign key's refusal to make.
    if measured is null then
        return true;
    end if;

    -- The interval this period reports on opens at the fund's previous PACKET
    -- measurement date — the last date anybody asked about. A lineage-only
    -- period is ingested and serves as an R3 predecessor; it is not a reporting
    -- boundary, and treating it as one refused realisations that belong to the
    -- audited window. NULL where there is no previous packet date, in which
    -- case only the acquisition side binds.
    select max(rp.period_date) into opened
      from reporting_period rp
     where rp.fund_id = fund
       and rp.period_date < measured
       and rp.audit_scope = 'packet';

    return exists (
        select 1 from lot l
         where l.holding_id = p_holding
           and l.acquired_date <= measured
           and (l.realized_date is null or opened is null or l.realized_date > opened));
end;
$$;

-- ── 2 and 3 ──────────────────────────────────────────────────────────────
create or replace function require_cross_class_policy() returns trigger
language plpgsql as $$
declare
    m         record;
    measured  date;
    held      text[];
    priced    text[];
    missing   text;
begin
    if new.decision_type <> 'valuation' or new.status <> 'approved' then
        return null;
    end if;

    select * into m from mark where id = new.mark_id;
    if not found then
        return null;
    end if;
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

    -- Every claim that prices the mark FOR FAIR VALUE, whether or not it states
    -- a class. Restricted to R2: an R1 acquisition document states a historical
    -- PPS, and counting it as pricing the mark let it supply a class the
    -- fair-value evidence never covered.
    if exists (
        select 1
          from decision_evidence de
          join evidence_assessment ea on ea.id = de.assessment_id
          join pbc_requirement pr     on pr.id = ea.requirement_id
          join evidence_link el       on el.assessment_id = de.assessment_id
          join claim c                on c.id = el.claim_id
         where de.decision_id = new.id
           and pr.requirement = 'R2'
           and c.price_per_share is not null
           and c.priced_class is null)
    then
        raise exception
            'INV-17: mark % is priced by a claim that states no priced_class, '
            'so cross-class pricing cannot be ruled out', m.id;
    end if;

    select array_agg(distinct c.priced_class)
      into priced
      from decision_evidence de
      join evidence_assessment ea on ea.id = de.assessment_id
      join pbc_requirement pr     on pr.id = ea.requirement_id
      join evidence_link el       on el.assessment_id = de.assessment_id
      join claim c                on c.id = el.claim_id
     where de.decision_id = new.id
       and pr.requirement = 'R2'
       and c.price_per_share is not null;

    if priced is null then           -- nothing prices this mark; not our question
        return null;
    end if;

    -- Direction 1 — a class is priced that the holding does not hold.
    foreach missing in array priced loop
        if held is null or not (missing = any (held)) then
            if not exists (
                select 1 from valuation_policy_decision p
                 where p.holding_id = m.holding_id
                   and p.period_id  = m.period_id
                   and p.from_class = missing
                   and p.to_class   = any (coalesce(held, array[]::text[]))
                   -- Under the approval's own policy, as 0003 already requires
                   -- of every cited assessment.
                   and p.policy_version = new.policy_version)
            then
                raise exception
                    'INV-17: mark % is priced from class %, which it does not hold, '
                    'with no cross-class policy decision cited under policy %',
                    m.id, missing, new.policy_version;
            end if;
        end if;
    end loop;

    -- Direction 2 — a class is HELD that nothing prices, so its shares are
    -- carried at some other class's price.
    foreach missing in array coalesce(held, array[]::text[]) loop
        if not (missing = any (priced)) then
            if not exists (
                select 1 from valuation_policy_decision p
                 where p.holding_id = m.holding_id
                   and p.period_id  = m.period_id
                   and p.to_class   = missing
                   and p.from_class = any (priced)
                   and p.policy_version = new.policy_version)
            then
                raise exception
                    'INV-17: mark % holds class % which no cited claim prices, '
                    'so it is carried at another class''s price with no cross-class '
                    'policy decision under policy %', m.id, missing, new.policy_version;
            end if;
        end if;
    end loop;

    return null;
end;
$$;

commit;
