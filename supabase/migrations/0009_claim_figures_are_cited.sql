-- 0009_claim_figures_are_cited.sql — a claim's own numbers must be cited too.
--
-- 0008 bound every `extracted_fact` to the passage it quotes. It said nothing
-- about the figures on the `claim` row itself, and `claim.price_per_share` and
-- `claim.stated_amount` are exactly that: numbers stored beside the citations
-- rather than through them.
--
-- Two independent cross-family reviews found this from opposite directions on
-- the same day — one reading the extractors, one reading the write path — which
-- is the strongest signal a finding gets. The failing shape:
--
--     claim.price_per_share = 800
--     extracted_fact        = '$8.00', cited to the row that states it
--
-- Every citation resolves. Every fact is bound. The claim beside them says eight
-- hundred, and the API renders 800 next to a passage reading $8.00. Nothing in
-- the contract, the writer or the schema compared the two, and the extractors
-- that did compare them did so one at a time, by hand, in about half the cases.
--
-- Deferred, because the facts are inserted after the claim they hang off — so
-- this fires at commit (or at `set constraints all immediate`), by which time
-- the whole claim exists or none of it does. `store_claim` performs the same
-- check first so the error can name the field; this is the side that cannot be
-- bypassed.

begin;

create or replace function claim_figures_are_cited() returns trigger
language plpgsql as $$
declare
    stated_currency_missing boolean;
begin
    if new.price_per_share is not null
       and not exists (
           select 1 from extracted_fact f
            where f.claim_id = new.id
              and f.value_numeric = new.price_per_share)
    then
        raise exception
            'INV-8: claim % states price_per_share % that no fact cited on it states',
            new.id, new.price_per_share;
    end if;

    if new.stated_amount is not null
       and not exists (
           select 1 from extracted_fact f
            where f.claim_id = new.id
              and f.value_numeric = new.stated_amount)
    then
        raise exception
            'INV-8: claim % states stated_amount % that no fact cited on it states',
            new.id, new.stated_amount;
    end if;

    -- Not a figure, but the same shape of omission: `claim_amount_currency_together`
    -- in 0001 already refuses one without the other, so this only documents that
    -- the pair travels together and never diverges here.
    stated_currency_missing := (new.stated_amount is null) <> (new.stated_currency is null);
    if stated_currency_missing then
        raise exception 'INV-11: claim % has an amount without its currency', new.id;
    end if;

    return null;
end;
$$;

create constraint trigger claim_figures_are_cited
    after insert on claim
    deferrable initially deferred
    for each row execute function claim_figures_are_cited();

commit;
