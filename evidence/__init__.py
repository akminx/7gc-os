"""Retrieval and model extraction — SPEC §10.

Two layers that sit *beside* the deterministic extractors in `ingest/documents/`
rather than replacing them:

* `retrieve` — SQL metadata filter, then Postgres full-text search, then a
  declared rerank. No model, no cost, no migration.
* `extract` — the one tier a pattern cannot cover: a figure stated in prose.

Neither layer is allowed to produce an offset. Both hand a quote to
`packages.contracts.citations.locate()`, which computes the span from the text,
so a passage that does not really say what it is cited for cannot be written
down at all.
"""
