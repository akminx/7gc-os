-- 0005_mark_held_at_date.sql — INV-7, enforced where marks are written
--
-- INV-7 says a total is computed over the positions HELD at the measurement
-- date, and the ledger stores everything needed to decide that: `lot` carries
-- `acquired_date` and `realized_date`, and `reporting_period` carries the date.
-- Nothing consulted either when a mark was written. Reproduced against the live
-- database with the real corpus loaded, before this file was written:
--
--   * a 2023-12-31 mark for Dream, whose only lot is acquired 2025-08-01 —
--     accepted;
--   * a 2025-12-31 mark for Jackpocket, whose only lot was realised
--     2024-05-20 — accepted.
--
-- Both are assertions of fair value for a position the same database says the
-- fund did not hold. The contract layer already refuses to put such a row into
-- a held-at-date total; the schema did not refuse to store it, which is the
-- one-side-only enforcement this project keeps producing.
--
-- ── What must STILL be allowed ───────────────────────────────────────────
--
-- The obvious rule — "no mark outside the holding window" — is wrong, and
-- wrong in the expensive direction: it deletes the realisation row.
--
-- SPEC §7.1 gives R4 (realization_support) to realised lots, and V9 checks
-- `gross_cash == realized_shares × cash_per_share` per lot. That evidence hangs
-- off an `evidence_assessment`, which binds to a `mark`. Jackpocket is the live
-- case: realised 2024-05-20, inside the period ending 2024-06-30, with the
-- tracker cell reading `Realized 5/20/24: 3,100,000`. At 2024-06-30 no lot is
-- held, so a strict held-AT-the-date rule would refuse the only row R4 could
-- ever be assessed against, and 3,100,000 of realised value could never be
-- evidenced — directly against the audit letter's request #4.
--
-- So the window is the reporting INTERVAL, not the measurement point: a mark is
-- accepted when some lot was held at any moment the period covers. The period's
-- opening bound is the fund's previous `reporting_period.period_date`, which is
-- what "since we last reported" means in this ledger. A realisation-only row
-- therefore commits, and — correctly — still contributes nothing to a
-- held-at-date total, because `Lot.held_at` is false at the measurement date.
-- The two layers agree instead of disagreeing.
--
-- ── What this deliberately does NOT decide ───────────────────────────────
--
-- A holding with no lot at all is not refused. Jio is the live case: its only
-- master-breakdown row is an `Indirect Fund` tranche the reader does not
-- recognise, so the position reaches the ledger with five marks and zero lots.
-- Held-at-date is then not computable from lots, and a database that cannot
-- compute an answer must not assert one — rejecting those marks would make the
-- real corpus unloadable and would delete the fund's own reported figures. The
-- ingest layer records the same silence as a substitution on
-- `HoldingRow.held_at_date` rather than a `False` that quietly drops the
-- position from the fund total.
--
-- ── Why two triggers ─────────────────────────────────────────────────────
--
-- Checking only on `insert into mark` is defeated by insert order: a loader
-- that writes every mark before any lot finds every holding lot-less, takes the
-- carve-out above, and the guard never fires at all. The second trigger closes
-- that, and only ever bites once — when a holding's FIRST lot arrives, since
-- the predicate is an EXISTS over lots and further lots can only widen it.
--
-- `mark` and `lot` are both append-only (0002), so INSERT is the only event
-- either guard needs.
--
-- 0001, 0002, 0003 and 0004 are already applied and are not edited.

begin;

-- The shared predicate, so the two triggers cannot drift into different ideas
-- of what "held" means. Deliberately VOLATILE (the default): the lot-side
-- trigger calls it AFTER INSERT and must see the row its own statement just
-- wrote, which a STABLE function's statement snapshot would not show.
create or replace function held_during_reported_period(
    p_holding text, p_period_id text
) returns boolean
language plpgsql as $$
declare
    measured date;
    fund     text;
    opened   date;
begin
    -- Not computable: no lot to compute it from. See the header.
    if not exists (select 1 from lot l where l.holding_id = p_holding) then
        return true;
    end if;

    select rp.period_date, rp.fund_id into measured, fund
      from reporting_period rp where rp.id = p_period_id;
    -- A period that does not exist is the foreign key's refusal to make, not
    -- this one's. Answering `false` here would report the wrong reason.
    if measured is null then
        return true;
    end if;

    -- The interval this period reports on opens the day after the fund's
    -- previous measurement date. NULL where there is no previous one, in which
    -- case only the acquisition side binds: the ledger holds no earlier
    -- boundary and cannot claim the realisation preceded the interval.
    select max(rp.period_date) into opened
      from reporting_period rp
     where rp.fund_id = fund and rp.period_date < measured;

    return exists (
        select 1 from lot l
         where l.holding_id = p_holding
           and l.acquired_date <= measured
           and (l.realized_date is null or opened is null or l.realized_date > opened));
end;
$$;

create or replace function reject_mark_for_an_unheld_period() returns trigger
language plpgsql as $$
begin
    if held_during_reported_period(new.holding_id, new.period_id) then
        return new;
    end if;
    raise exception
        'INV-7 (%): holding % held no lot at any point in the period ending %; '
        'a mark is an assertion of value for a position this ledger says it did not hold',
        tg_name, new.holding_id,
        (select period_date from reporting_period where id = new.period_id);
end;
$$;

create trigger mark_held_at_date
    before insert on mark
    for each row execute function reject_mark_for_an_unheld_period();

-- The other direction: the first lot of a holding that already carries marks.
create or replace function reject_first_lot_contradicting_a_mark() returns trigger
language plpgsql as $$
declare offending text;
begin
    if exists (select 1 from lot l where l.holding_id = new.holding_id and l.id <> new.id) then
        return null;
    end if;
    select m.period_id into offending
      from mark m
     where m.holding_id = new.holding_id
       and not held_during_reported_period(new.holding_id, m.period_id)
     limit 1;
    if offending is not null then
        raise exception
            'INV-7 (%): lot % is the first lot of holding %, and under it the existing mark '
            'for period % values a position the ledger would then say was not held',
            tg_name, new.id, new.holding_id, offending;
    end if;
    return null;
end;
$$;

create trigger lot_agrees_with_existing_marks
    after insert on lot
    for each row execute function reject_first_lot_contradicting_a_mark();

commit;
