-- 0008_citations_resolve.sql — a citation must resolve to the text it quotes.
--
-- INV-8 · source fact ≠ derived figure. A source fact "resolves to an exact
-- immutable citation: text[start:end] equals the quote, content hash matches."
-- Until now it did not. `extracted_fact` carried `citation_quote`, `span_start`
-- and `span_end` with one constraint between them — `span_end > span_start` —
-- and nothing whatsoever binding any of the three to the document. Span (0, 1)
-- beside a forty-character quote was a valid row. The audit called it a
-- structural shell, and it was: the column existed, the check existed, and a
-- figure could resolve to nothing at all.
--
-- It stayed open on purpose. Nothing wrote a citation, so a constraint written
-- then would have been guessing at the shape of data that did not exist, and a
-- guess that cannot be exercised is how shells get built in the first place.
-- This lands in the same commit as the first extractor that writes one.
--
-- Three bindings, because a resolving span is necessary and not sufficient —
-- INV-8's second hole is that r1 "proved a quote existed, not that it supported
-- the figure":
--
--   1. substring(canonical_text, span) = citation_quote   the quote is in the document
--   2. value_text appears inside citation_quote           the figure is in the quote
--   3. cited_numeral(value_text) = value_numeric          the number is that figure
--
-- Each is mirrored in `packages/contracts/citations.py`, which the write path
-- calls before it inserts. Both sides, because every recurring defect this
-- project has found was a rule enforced on one side only — seven times now.
-- The database is the side that cannot be bypassed, so it is the side that must
-- be able to refuse.

begin;

-- The number a quoted figure states, or NULL if it does not state exactly one.
--
-- Mirrors `cited_numeral()` in packages/contracts/citations.py, and
-- tests/test_citations.py runs one shared table of cases through both to prove
-- they agree. Two implementations believed to agree is how a figure passes the
-- contract and is refused by the database — or worse, passes both while they
-- mean different numbers.
--
-- Deliberately NULL rather than an error for text that names no single figure:
-- '$8.00 and $3.20' reads as nothing, not as 8.0032 and not as the first of the
-- two. NULL then fails the equality below, so such a value_text cannot carry a
-- value_numeric at all. What must never happen is a silent zero.
-- Whitespace is spelled out rather than written `\s`. Python's `\s` on a str
-- pattern matches Unicode whitespace including a non-breaking space; Postgres
-- ARE `\s` does not. A figure carrying a NBSP — an ordinary thing for a PDF
-- table to contain — would then parse on one side and refuse on the other, and
-- the two rules would silently stop being mirrors of each other.
--
-- The anchors are `\A` and `\Z`, not `^` and `$`. In Postgres ARE without the
-- `n` flag `$` matches only at end of string, but in Python `$` also matches
-- immediately before a trailing newline — so `'8.00' || chr(10)` would parse in
-- the contract and refuse here. The absolute anchors mean the same thing in
-- both, and the Python side uses `fullmatch` for the same reason.
create or replace function cited_numeral(value_text text) returns numeric
language plpgsql immutable as $$
declare
    ws       constant text := '[ \t\n\r\f\v]';
    -- The integer part is a grammar, not "digits and commas". The looser
    -- version read '8,00' — a European decimal — as eight hundred, and the
    -- Python parser agreed with it, which is the one failure a mirror test
    -- cannot catch: both sides wrong in the same direction. A comma separates
    -- thousands only when it groups exactly three digits, and a leading zero on
    -- an integer ('008') is refused rather than normalised to 8.
    int_part constant text := '(0|[1-9][0-9]{0,2}(,[0-9]{3})+|[1-9][0-9]*)';
    shape    constant text :=
        '\A' || ws || '*\(?' || ws || '*-?' || ws || '*\$?' || ws || '*'
        || int_part || '(\.[0-9]+)?'
        || ws || '*%?' || ws || '*\)?' || ws || '*\Z';
    stripped text;
begin
    if value_text !~ shape then
        return null;
    end if;
    stripped := regexp_replace(value_text, '[^0-9.]', '', 'g');
    if stripped !~ '\A[0-9]+(\.[0-9]+)?\Z' then
        return null;
    end if;
    if value_text ~ ('\A' || ws || '*[(-]') then
        return -stripped::numeric;
    end if;
    return stripped::numeric;
end;
$$;

-- How many times a quote states a value as a figure in its own right.
--
-- Plain containment was not enough, and the gap was not theoretical: with a
-- citation resolving to `7GC Fund II, L.P.   625,000   $3.20`, storing
-- value_text '625' with value_numeric 625 satisfied all three bindings and this
-- trigger accepted it. So did '000' with 0. The ledger would hold six hundred
-- and twenty-five shares, cited to a row stating six hundred and twenty-five
-- thousand, with every check green.
--
-- A digit, comma or full stop on either side means the match is a fragment of a
-- longer figure. `$` and `%` do not count: '8.00' inside '$8.00' and '3.29'
-- inside '3.29%' are the number the page states, without its dressing.
--
-- Written as a scan rather than a regex because value_text is data — building a
-- pattern out of it would need a regex-escape Postgres does not provide, and an
-- unescaped one turns '(this financing)' into a capture group. That is the same
-- defect `locate()` has on the Python side, where `re.escape` answers it.
--
-- Mirrored by `value_token_occurrences()` in packages/contracts/citations.py.
create or replace function value_token_occurrences(quote text, value_text text)
returns int language plpgsql immutable as $$
declare
    found  int := 0;
    cursor_at int := 1;
    at     int;
    vlen   int := length(value_text);
    before_ch text;
    after_ch  text;
    beyond_ch text;
begin
    if vlen = 0 then
        return 0;
    end if;
    loop
        at := position(value_text in substring(quote from cursor_at));
        exit when at = 0;
        at := cursor_at + at - 1;                  -- absolute, 1-based
        -- An empty string at the start or end of the quote matches no character
        -- class, so a boundary counts as a boundary rather than as a digit.
        before_ch := case when at = 1 then '' else substring(quote from at - 1 for 1) end;
        after_ch  := substring(quote from at + vlen for 1);
        beyond_ch := substring(quote from at + vlen + 1 for 1);
        -- Three continuations that change the VALUE rather than its dressing,
        -- each of which this counter accepted before:
        --   a leading minus  — 'loss was -8.00' matched '8.00' and stored +8.00
        -- Accounting parentheses are NOT a boundary: all four parenthesised
        -- figures in this corpus are grouping, not negatives, and the rule
        -- refused every one of them. `cited_fact` refuses the ambiguous shape
        -- at the producer instead.
        --   an exponent      — 'scaled 8e3' matched '8', out by 8000/8
        -- A leading '+' is not one: it states the sign the value already has,
        -- and Moonfare's '+$48,515' is a real corpus figure.
        if before_ch !~ '[0-9,.]'
           and after_ch !~ '[0-9,.]'
           and before_ch <> '-'
           and not (after_ch in ('e', 'E') and beyond_ch ~ '[0-9+-]')
        then
            found := found + 1;
        end if;
        cursor_at := at + 1;
    end loop;
    return found;
end;
$$;

create or replace function citation_resolves() returns trigger
language plpgsql as $$
declare
    body text;
    found text;
begin
    select dv.canonical_text into body
      from claim c
      join document_version dv on dv.id = c.document_version_id
     where c.id = new.claim_id;

    if body is null then
        -- Unreachable through the foreign keys, and checked anyway: if it ever
        -- became reachable, `substring(NULL, ...)` is NULL, `NULL <> quote` is
        -- NULL, and NULL is not FALSE — so every check below would pass and the
        -- guard would be silently off. That is the exact defeat the MATCH FULL
        -- constraints in 0001 were written against.
        raise exception
            'INV-8: fact on claim % has no document text to resolve against', new.claim_id;
    end if;

    -- span_start >= 0 is checked here rather than assumed. 0001 constrained only
    -- `span_end > span_start`, so (-9, -1) was a legal span, and Postgres
    -- `substring` treats a non-positive start as reaching before the string
    -- instead of failing.
    if new.span_start < 0 then
        raise exception 'INV-8: span_start % is negative', new.span_start;
    end if;

    if new.span_end > length(body) then
        raise exception
            'INV-8: span [%, %) runs past the end of document text for claim % '
            '(% code points)', new.span_start, new.span_end, new.claim_id, length(body);
    end if;

    -- `substring(from ... for ...)` is 1-based and counts characters; Python
    -- str slicing is 0-based and counts code points. For UTF-8 text those are
    -- the same unit, including astral-plane characters, which is what lets the
    -- same span mean the same thing on both sides. The +1 is the only
    -- adjustment, and getting it wrong shifts every citation by one character —
    -- tests/test_citations.py pins it against a real document.
    found := substring(body from new.span_start + 1 for new.span_end - new.span_start);
    if found is distinct from new.citation_quote then
        raise exception
            'INV-8: citation does not resolve — span [%, %) holds %, not %',
            new.span_start, new.span_end, quote_literal(found),
            quote_literal(new.citation_quote);
    end if;

    -- INV-8 second hole: a real but irrelevant quote. Without this, an extractor
    -- may cite the document's title for a share count and every check above
    -- still passes.
    if value_token_occurrences(new.citation_quote, new.value_text) <> 1 then
        raise exception
            'INV-8: the passage cited states % as a figure in its own right % time(s), '
            'not once (%)',
            quote_literal(new.value_text),
            value_token_occurrences(new.citation_quote, new.value_text),
            quote_literal(new.citation_quote);
    end if;

    -- Equality in BOTH directions. The first version only checked when
    -- value_numeric was non-NULL, so NULL short-circuited it and a figure-shaped
    -- value_text could be stored with no number beside it — a cited `$8.00`
    -- that every downstream reader sees as "states no figure". `is distinct
    -- from` treats NULL as a value, so NULL vs 8.00 and 8.00 vs NULL both fail
    -- and NULL vs NULL (a date, a party name) passes.
    if cited_numeral(new.value_text) is distinct from new.value_numeric then
        raise exception
            'INV-8: stored number % is not the figure the cited text states (%); '
            'the text reads as %',
            coalesce(new.value_numeric::text, 'NULL'),
            quote_literal(new.value_text),
            coalesce(cited_numeral(new.value_text)::text, 'no figure');
    end if;

    return new;
end;
$$;

-- INSERT *and* UPDATE. `extracted_fact` is already append-only against UPDATE
-- via 0002, so the UPDATE arm is unreachable today — and it is declared anyway,
-- because a guard that depends on a different trigger continuing to exist is
-- the one-side-only enforcement this project keeps rediscovering. Dropping the
-- append-only trigger must not silently reopen this one.
create trigger extracted_fact_citation_resolves
    before insert or update on extracted_fact
    for each row execute function citation_resolves();

commit;
