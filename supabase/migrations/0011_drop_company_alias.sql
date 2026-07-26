-- 0011_drop_company_alias.sql — remove a table nothing reads or writes.
--
-- `company_alias` was created in 0001 for a problem that got solved a different
-- way. The two workbooks name the same position differently — the tracker row
-- reads `Jio (Indirect)` while the master breakdown's tab is `Jio` — and the
-- fix turned out to be `company_key()` in `ingest/trackers/read.py`, which
-- strips the parenthesised annotation at read time and joins on what the label
-- NAMES. No row was ever written here, and no code has ever selected from it.
--
-- Dropped rather than left in place because an empty table with no reader is
-- the same failure this project keeps finding one level down: it reads as
-- coverage and provides none. Someone auditing the schema sees an alias
-- facility and assumes aliases are handled somewhere they are not.
--
-- The trigger to rebuild it: a company whose two names do not reduce to the
-- same key — an acquisition, a rename, or two funds recording the same company
-- under different legal entities. `company_key` refuses that case rather than
-- guessing (`ingest/trackers/to_contracts.py` records it as a `Refusal`), so
-- the need would surface as a refusal rather than as a silent mismatch.

begin;

drop table if exists company_alias;

commit;
