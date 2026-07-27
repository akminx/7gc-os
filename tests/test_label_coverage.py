"""Every code the packets can reach has a gloss in the browser.

Found by USING the product, not by reading it. Opening Fluidstack's fair-value
pane on the demo path showed:

    OFF_CLASS_EVIDENCE_NOT_RELIED · no gloss is recorded for this code

`web/src/labels.ts` is deliberately partial and never invents a label — an
unglossed code renders as the API's own word for it and says so, rather than as
a reassuring blank. That is the right failure mode and it is still a failure: on
screen it reads as a system that does not know what it just said.

The handoff states the rule in as many words — "if you make a new code reachable,
add its gloss in the same change" — and nothing checked it. Today's rulings on
the audit letter made five codes reachable and none of the five was glossed, so
the rule held for exactly as long as the person who wrote it was doing the work.
This is that rule as a test.

Read from the ASSEMBLED PACKETS rather than from the policy source. A scan of
`policy/` for string literals would report codes no corpus can produce and would
miss one composed at runtime; what matters is what an auditor can actually be
shown.
"""

from __future__ import annotations

import re
from pathlib import Path

from packages.contracts.models import Packet

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "web" / "src" / "labels.ts"

#: A key at the top level of a `Record<string, …>` in `labels.ts`. Matched on
#: the two-space indent so a code quoted inside a `meaning` string is not read
#: as a declaration — which would make this pass on a file that merely mentions
#: the code in prose.
_DECLARED = re.compile(r"^  ([A-Z][A-Z0-9_:]*): \{", re.MULTILINE)


def _declared() -> set[str]:
    return set(_DECLARED.findall(LABELS.read_text(encoding="utf-8")))


def _reachable(packets: dict[tuple[str, str], Packet | None]) -> tuple[set[str], set[str]]:
    reasons: set[str] = set()
    actions: set[str] = set()
    for packet in packets.values():
        if packet is None:
            continue
        for row in packet.rows:
            for assessment in row.assessments:
                reasons.update(assessment.reason_codes)
                actions.update(assessment.next_actions)
    return reasons, actions


def test_every_reason_code_a_packet_can_show_is_glossed(policy_packets: object) -> None:
    """An unglossed code on screen reads as a system that does not know what it
    just said. This is the check that was a convention until it failed."""
    assert isinstance(policy_packets, dict)
    reasons, _ = _reachable(policy_packets)
    assert reasons, "no reason code is reachable — this test would pass vacuously"
    missing = sorted(reasons - _declared())
    assert not missing, (
        f"{len(missing)} reason code(s) reachable in the packets have no gloss in "
        f"web/src/labels.ts and will render as 'no gloss is recorded for this code': {missing}"
    )


def test_every_next_action_a_packet_can_show_is_glossed(policy_packets: object) -> None:
    """The action is the half a reader acts on. An unglossed one tells an auditor
    that something is owed and not what, or to whom."""
    assert isinstance(policy_packets, dict)
    _, actions = _reachable(policy_packets)
    assert actions, "no next action is reachable — this test would pass vacuously"
    missing = sorted(actions - _declared())
    assert not missing, (
        f"{len(missing)} next action(s) reachable in the packets have no gloss in "
        f"web/src/labels.ts: {missing}"
    )


def test_the_browser_and_the_packet_quote_the_same_letter() -> None:
    """One mapping from requirement to the client's paragraph, checked in two places.

    `packet/tables.py::REQUIREMENTS` is what the EXPORTED packet states; the
    browser now shows the same sentence on the dashboard's column headers, so an
    auditor can answer "which of the four requests does this answer" by reading
    rather than by hovering five times.

    Two independent descriptions of what the client asked for is exactly the
    drift this project refuses everywhere else — and it would drift silently,
    because each side reads correctly on its own. So the transcription is
    checked character for character against the source it was taken from.
    """
    from packet.tables import REQUIREMENTS

    text = LABELS.read_text(encoding="utf-8")
    for code, (_slug, sentence) in REQUIREMENTS.items():
        # Read out of the TS source rather than executed, for the same reason
        # `tests/test_web_contracts.py` reads it: only the Node gate can import a
        # TypeScript module, and a check that needs `node_modules` starts
        # SKIPPING the first time it is absent.
        quoted = sentence.replace('"', '\\"')
        assert quoted in text, (
            f"web/src/labels.ts does not carry the letter sentence for {code.value} "
            f"that packet/tables.py states: {sentence!r}"
        )


def test_the_scan_reads_declarations_and_not_prose() -> None:
    """The guard's own failure mode, tested against a fixture.

    `labels.ts` names codes inside `meaning` strings and in comments — that is
    how a reader learns why two identically-worded verdicts send different
    letters. A scan matching those would report a merely-mentioned code as
    glossed, which is the shape of a check that cannot fail.

    Tested on text this function is handed rather than on the real file's
    incidental contents: an assertion about what `labels.ts` happens to mention
    today is an assertion about the wrong thing, and it goes red the first time
    someone rewords a comment.
    """
    sample = """
/**
 * `MENTIONED_IN_A_COMMENT` is discussed here and declared nowhere.
 */
export const REASON_CODE: Record<string, ReasonTerm> = {
  DECLARED_CODE: {
    label: "declared",
    origin: "unresolved",
    meaning: "This sentence names MENTIONED_IN_A_STRING and does not declare it.",
  },
    INDENTED_TOO_FAR: { label: "nested, not a top-level key" },
};
"""
    found = set(_DECLARED.findall(sample))
    assert found == {"DECLARED_CODE"}, found
    assert "MENTIONED_IN_A_COMMENT" not in found
    assert "MENTIONED_IN_A_STRING" not in found
    # And the real file is read by the same expression, so the guard above is
    # measuring declarations there too.
    assert "SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW" in _declared()
