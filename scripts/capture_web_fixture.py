#!/usr/bin/env python3
"""Capture what the API serves into the snapshot the browser is checked against.

    .venv/bin/python scripts/capture_web_fixture.py

`web/src/fixture.ts` is the Dream slice the frontend renders when no API base is
configured. Its value as evidence rests entirely on it being the SERIALISER's
output rather than something typed to fit the screen — a hand-written fixture
agrees with whatever the frontend expects, so it can never report a disagreement.

All four read routes are captured, not two. `GET /funds` and `GET /holdings/{id}`
did not exist when this was written, and a snapshot that covers half the surface
says nothing about the other half: the evidence workspace — the screen the whole
product is for — reads `/holdings/{id}`, and until it was captured here nothing
outside the browser had an opinion about that response's shape.

It was captured correctly once, by hand, and nothing kept it captured. This
writes the same bytes to `web/src/fixture.api.json`, which both gates then check
in their own language and neither has to run the other's runtime:

    tests/test_web_contracts.py   API output  == fixture.api.json   (Python gate)
    web/src/fixture.test.ts       fixture.ts  == fixture.api.json   (Node gate)

Together those two say `fixture.ts` is what the API serves. Split that way
because a Python test that shells out to `vite-node` is a check that stops
running the first time `node_modules` is absent, and a check that passes because
it could not run is the failure this project has now found seven times.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "web" / "src" / "fixture.api.json"

#: The one packet the stub routes serve, and the one the bundled fixture holds.
FUND_ID = "fund_ii"
PERIOD_ID = "f2_25q4"
HOLDING_ID = "dream"

#: Every read route, keyed by the name the snapshot files it under. Written as
#: data rather than as four hand-rolled requests so that adding a route to the
#: API and forgetting to capture it is a one-line omission somebody can see,
#: instead of a silently half-covered contract.
ROUTES = {
    "funds": "/funds",
    "packet": f"/funds/{FUND_ID}/periods/{PERIOD_ID}/packet",
    "totals": f"/funds/{FUND_ID}/periods/{PERIOD_ID}/totals",
    "holding": f"/holdings/{HOLDING_ID}",
}


#: `api.config.dsn()` merges `.env` under the process environment and treats an
#: empty value as unset, so `""` is how a caller says "no database" without
#: editing `.env`.
_DSN_KEYS = ("MIGRATION_DATABASE_URL", "DATABASE_URL")


@contextmanager
def _no_database() -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in _DSN_KEYS}
    os.environ.update(dict.fromkeys(_DSN_KEYS, ""))
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def capture() -> dict[str, Any]:
    """Every read route, exactly as it answers.

    Fetched through the app rather than reconstructed from `fixtures/dream.py`,
    because the thing under test is the WIRE — Decimal-to-string serialisation,
    the computed fields `api/serialize.py` attaches to the model dump, and the
    `source` the route wraps around it all happen between the fixture object and
    the bytes the browser receives.

    Captured from the route's FIXTURE branch deliberately, by forcing the DSN
    empty. `web/src/fixture.ts` is what the browser renders when no API is
    configured; the route's fixture branch is what the API returns when no
    database is. Those two are the pair this snapshot pins. Capturing whatever a
    local ledger happens to hold would make the reference depend on the state of
    someone's database — and a reference that moves is not one. The ledger
    branch also stamps `generated_at` with the wall clock, so a ledger capture
    could not be a fixed reference even if the rows never changed.
    """
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    with _no_database():
        answered = {name: client.get(url) for name, url in ROUTES.items()}
    for name, response in answered.items():
        if response.status_code != 200:
            raise SystemExit(f"{name} returned {response.status_code}, not 200")
    return {name: response.json() for name, response in answered.items()}


def render(payload: dict[str, Any]) -> str:
    """Sorted keys and a trailing newline, so a re-capture diffs as content."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> Path:
    """Write the snapshot and return where it went.

    Writing is deliberately NOT something the test suite does to the real path.
    `tests/test_web_contracts.py` asserts the committed snapshot still equals
    the live capture; a test that also rewrote it would repair the drift it was
    meant to report, and which of the two ran first would decide whether the
    guard worked. Re-capturing is a command someone runs and reads the diff of.
    """
    # Run as a script, `sys.path[0]` is scripts/, so `packages` and `api` are
    # not importable. Inside the function because `capture()` imports the app
    # lazily, so the path only has to be right by the time it is called.
    # Unconditional: guarding it with `not in sys.path` makes a branch that only
    # one of the two entry points can ever take, so half of it is dead in every
    # run and neither half is ever proven.
    sys.path.insert(0, str(ROOT))
    SNAPSHOT.write_text(render(capture()))
    return SNAPSHOT


if __name__ == "__main__":
    print(f"wrote {main()}")
