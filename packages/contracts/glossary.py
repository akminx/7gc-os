"""The display vocabulary, read from the file the UI generates it into.

`web/src/labels.ts` is where every code an auditor sees is defined, carefully
and in one place. `scripts/emit-glossary.mjs` reads that file's object literals
and writes `glossary.json`; this reads the JSON. Nothing here restates a
definition, and there is no second wording to drift.

**Why this exists at all.** The assistant payload originally carried reason
CODES and no meanings, on the reasoning that copying `labels.ts` into Python
would be the duplication this project keeps refusing. That was right about the
duplication and wrong about the consequence: handed
`SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW` and no definition, a model wrote that
the evidence "falls outside the time window on which R2 itself relies" — when
the window is the SOURCE DOCUMENT's own stated one. That is INV-16 exactly
inverted, stated fluently, and no numeral guard can see it.

The lesson is that withholding a definition does not make a model cautious. It
makes it inventive. So the definition travels, and it travels from the same
sentence the reader sees.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GLOSSARY_PATH = Path(__file__).resolve().parent / "glossary.json"


class GlossaryMissing(RuntimeError):
    """The generated glossary is absent. Never silently an empty vocabulary."""


def load() -> dict[str, dict[str, Any]]:
    """The whole vocabulary, or a loud failure.

    Not cached and not defaulted. An empty dict here would mean every payload
    quietly loses its definitions and the model goes back to guessing — the
    exact regression this module exists to prevent, arriving as better-looking
    prose rather than as an error.
    """
    if not GLOSSARY_PATH.exists():
        raise GlossaryMissing(
            f"{GLOSSARY_PATH} is missing. Generate it with: node scripts/emit-glossary.mjs"
        )
    parsed: dict[str, dict[str, Any]] = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    return parsed


def describe(kind: str, code: str) -> dict[str, str] | None:
    """One code's label and meaning, or `None` where the vocabulary has none.

    `None` rather than a placeholder. A code with no gloss is a real state —
    `labels.ts` renders it as "no gloss is recorded for this code" — and
    inventing a stand-in here would hide from the model that it is being asked
    about something nobody has defined.
    """
    entry = load().get(kind, {}).get(code)
    if not isinstance(entry, dict):
        return None
    return {k: v for k, v in entry.items() if isinstance(v, str)}


def glossed(kind: str, codes: list[str]) -> list[dict[str, str]]:
    """Codes paired with their definitions, in the order given.

    A code the vocabulary does not know still appears, carrying the fact that
    it is undefined. Dropping it would make the payload shorter than the
    finding, and the model would restate a row missing one of its reasons.
    """
    out: list[dict[str, str]] = []
    for code in codes:
        entry = describe(kind, code)
        out.append(
            {"code": code, **entry}
            if entry is not None
            else {"code": code, "meaning": "No definition is recorded for this code."}
        )
    return out
