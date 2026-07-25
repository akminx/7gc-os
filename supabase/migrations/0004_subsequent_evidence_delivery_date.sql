-- 0004_subsequent_evidence_delivery_date.sql — WHICH date makes evidence subsequent
--
-- 0002 derived `evidence_link.is_subsequent` from `claim.issued_date`:
--
--     if new.is_subsequent <> (c.issued_date > measured) then ... raise
--
-- SPEC V11 says the DELIVERY date is what sets `is_subsequent_evidence`, and
-- INV-3 is the reason the two are separate columns at all. Jio's FY2025 capital
-- account statement is the live case: Meridian Fund Services emails it on
-- 30 Jan 2026 for a 31 Dec 2025 measurement date, and the statement itself is
-- both issued and as-of in 2025. Under 0002 the truthful record — evidence that
-- did not exist in the fund's hands at the measurement date — was REJECTED, and
-- the false one was the only one that committed. Reproduced against the live
-- database before this file was written: `is_subsequent = true` raised INV-3,
-- `is_subsequent = false` was accepted.
--
-- `claim.received_date` already exists (0001, INV-3: three distinct instants),
-- so this needs no new column — only the guard reading the right one. It stays
-- NULLABLE: not every claim arrives by a channel that dates its delivery, and
-- inventing a receipt date to satisfy a NOT NULL is exactly the collapse INV-3
-- forbids. Where it is absent the issue date remains the best available
-- evidence of when the document could have been relied upon, which is what 0002
-- assumed universally.
--
-- 0001, 0002 and 0003 are already applied and are not edited.

begin;

-- INV-16 / INV-3, restated. The applicability half is unchanged from 0002;
-- only the temporal predicate moves from `issued_date` to the delivery date.
create or replace function check_link_applicability() returns trigger
language plpgsql as $$
declare
    measured  date;
    delivered date;
    c         claim%rowtype;
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

    -- SPEC V11: the authoritative receipt/delivery date, falling back to the
    -- issue date only where delivery was never recorded.
    delivered := coalesce(c.received_date, c.issued_date);

    if new.is_subsequent <> (delivered > measured) then
        raise exception
            'INV-3: is_subsequent must equal (delivery date > measurement date) for claim % '
            'at % (delivered %, issued %, received %)',
            c.id, measured, delivered, c.issued_date,
            coalesce(c.received_date::text, 'unrecorded');
    end if;
    return new;
end;
$$;

commit;
