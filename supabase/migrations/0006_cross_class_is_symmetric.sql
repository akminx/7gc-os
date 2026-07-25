-- INV-17 · the set of classes HELD must equal the set of classes PRICED.
--
-- 0002 asked only whether each priced class was among the held ones, which is
-- one direction of the test and clears the exact case INV-17 was written for:
-- a holding carrying Series B and Series C, priced by a single Series C claim,
-- passes because Series C IS held — while the Series B shares are marked at the
-- Series C price. The Mom Project's term sheet says Series C is "senior to
-- Series B and Series Seed", so that is precisely the economic equivalence the
-- document contradicts.
--
-- The other direction fails too, on Lucra: it holds Series A-1 and its mark
-- uses the A-2 price from a CEO email, so a class the fund does not hold priced
-- the position. 0002 caught that one; it is kept.
--
-- The oracle was amended to the same equality rule (`evals/oracle/policy.py`,
-- anchored in `cases_corpus.cross_class_is_symmetric`). Enforcing a rule in one
-- place and not the other is the defect this project has produced seven times,
-- and here the two had drifted into contradicting each other on the same facts:
-- the database accepted a two-class holding the oracle rejected.
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

    -- Every claim that PRICES the mark, whether or not it states a class. A
    -- cap-table extract carrying a price with the class left implicit is the
    -- normal shape of that document, not an exotic one, and an unstated class
    -- cannot be shown to be the same class.
    if exists (
        select 1
          from decision_evidence de
          join evidence_link el on el.assessment_id = de.assessment_id
          join claim c          on c.id = el.claim_id
         where de.decision_id = new.id
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
      join evidence_link el on el.assessment_id = de.assessment_id
      join claim c          on c.id = el.claim_id
     where de.decision_id = new.id
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
                   and p.to_class   = any (coalesce(held, array[]::text[])))
            then
                raise exception
                    'INV-17: mark % is priced from class %, which it does not hold, '
                    'with no cited cross-class policy decision', m.id, missing;
            end if;
        end if;
    end loop;

    -- Direction 2 — a class is HELD that nothing prices, so its shares are
    -- carried at some other class's price. This is the half 0002 was missing.
    foreach missing in array coalesce(held, array[]::text[]) loop
        if not (missing = any (priced)) then
            if not exists (
                select 1 from valuation_policy_decision p
                 where p.holding_id = m.holding_id
                   and p.period_id  = m.period_id
                   and p.to_class   = missing
                   and p.from_class = any (priced))
            then
                raise exception
                    'INV-17: mark % holds class % which no cited claim prices, '
                    'so it is carried at another class''s price with no cross-class '
                    'policy decision', m.id, missing;
            end if;
        end if;
    end loop;

    return null;
end;
$$;
