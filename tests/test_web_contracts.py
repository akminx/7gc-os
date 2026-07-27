"""The browser's copy of the contract, checked against the contract.

`packages/contracts/enums.py` states the principle these tests exist to extend:

    Mirroring is verified, not assumed: `tests/test_contracts.py` reads the enum
    labels back out of the live database and asserts membership matches in both
    directions. A contract that has drifted from its schema is worse than no
    contract, because it reads as agreement.

The Python-to-Postgres direction was guarded. The Python-to-TypeScript direction
was not. `web/src/contracts.ts` is hand-transcribed from `models.py` and
`enums.py`, `web/src/responses.ts` from `api/routes.py` and `api/serialize.py`,
and `web/src/fixture.api.json` is captured from the four read routes; all three
were accurate when written and nothing reported when they stopped being. A
frontend built on a stale contract does not crash — it renders a field that is
always `undefined` as a blank cell, which on these screens reads as "nothing to
report".

Three artefacts, three checks:

  * the TS unions and model interfaces against the live enums and models
  * the TS route envelopes against what the routes actually return
  * the JSON snapshot against what the routes actually serve now

The second half of the snapshot's job — that `fixture.ts` still equals it —
belongs to `web/src/fixture.test.ts`, because only the Node gate can import a
TypeScript module. Splitting it that way keeps each half runnable in its own
gate: a Python test that shelled out to `vite-node` would start SKIPPING the
first time `node_modules` was absent, and a check that passes because it could
not run is the defect this repo has now found seven separate times.
"""

from __future__ import annotations

import json
import re
from dataclasses import fields as dataclass_fields
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel

from api import reconciliation, routes
from api.serialize import recomputation_json, row_json, totals_json
from packages.contracts import enums, models
from packages.contracts.base import Money
from packages.contracts.fixtures.dream import dream_packet
from packet.export import Written
from packet.layout import Layout
from packet.recompute import ClassAmount, Recomputation
from policy.validators import Outcome
from scripts import capture_web_fixture
from scripts.capture_web_fixture import SNAPSHOT, capture, main, render

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_TS = ROOT / "web" / "src" / "contracts.ts"
RESPONSES_TS = ROOT / "web" / "src" / "responses.ts"
ROUTES_PY = ROOT / "api" / "routes.py"

#: `Lot` and `LotConversion` are contract models that never reach the packet
#: wire — the packet carries `HoldingRow.held_at_date`, already computed from
#: the lots (INV-7). Declaring them in the browser would invite a surface to
#: recompute held-at-date from lots it was never sent.
NOT_ON_THE_WIRE = {"Lot", "LotConversion"}

#: What `api/serialize.py` attaches to a model dump on its way to the wire.
#: These are Python `@property` (plus one difference the browser must not
#: subtract), so they are absent from `model_fields` and present in the JSON.
#: Not hand-maintained on trust: the test below re-derives this from the
#: serialiser's own output and fails if it has moved.
SERIALISED_EXTRAS = {
    "HoldingRow": {"supported", "unsupported_reasons", "approved"},
    "PacketTotals": {"contains_unsupported_inputs", "unheld_gap_positions"},
    "RequirementAssessment": {"applicable"},
}

#: Which TypeScript interface each captured route payload must match, key for
#: key. `EvidenceClaim` is checked separately against `Claim`, because the
#: fixture branch has no claim store and so serves an empty evidence list —
#: there is no instance in the snapshot to compare against.
ROUTE_INTERFACES = {
    "funds": "FundsResponse",
    "packet": "PacketResponse",
    "totals": "TotalsResponse",
    "holding": "HoldingResponse",
}


def _ts(path: Path = CONTRACTS_TS) -> str:
    return path.read_text()


def _ts_unions(path: Path = CONTRACTS_TS) -> dict[str, set[str]]:
    """Every `export type X = "a" | "b";` and its members."""
    return {
        m.group(1): set(re.findall(r'"([^"]+)"', m.group(2)))
        for m in re.finditer(r"export type (\w+)\s*=\s*([^;]+);", _ts(path))
    }


def _declarations(path: Path) -> dict[str, tuple[str | None, set[str]]]:
    """Every `export interface X [extends Y] { ... }`, as (parent, own fields).

    Doc comments are stripped before the field pattern runs: several fields
    carry a `/** ... */` block whose prose contains colons, and matching those
    as fields would invent members that do not exist.
    """
    out: dict[str, tuple[str | None, set[str]]] = {}
    for m in re.finditer(r"export interface (\w+)(?: extends (\w+))? \{(.*?)\n\}", _ts(path), re.S):
        body = re.sub(r"/\*.*?\*/", "", m.group(3), flags=re.S)
        out[m.group(1)] = (m.group(2), set(re.findall(r"^\s{2}(\w+)\??:", body, re.M)))
    return out


def _all_declarations() -> dict[str, tuple[str | None, set[str]]]:
    return {**_declarations(CONTRACTS_TS), **_declarations(RESPONSES_TS)}


def _fields(name: str) -> set[str]:
    """An interface's fields including anything it inherits.

    A response envelope is declared as `extends Packet`, so reading only its own
    body would report it as carrying two fields when it carries nine — and the
    check would pass by measuring almost nothing.
    """
    declared = _all_declarations()
    parent, own = declared[name]
    return own if parent is None else own | _fields(parent)


def _ts_interfaces() -> dict[str, set[str]]:
    return {name: _fields(name) for name in _declarations(CONTRACTS_TS)}


def _py_enums() -> dict[str, type[StrEnum]]:
    """Keyed by CLASS name, not by the Postgres type name `PG_ENUMS` keys on.

    `TotalKind` lives in `models.py` and is not a Postgres enum, so it is absent
    from `PG_ENUMS` and has to be added by hand. It is also the enum INV-19
    turns on — a total that does not say what it is a total of — so a drift here
    is not cosmetic.
    """
    by_name: dict[str, type[StrEnum]] = {e.__name__: e for e in enums.PG_ENUMS.values()}
    by_name["TotalKind"] = models.TotalKind
    return by_name


def _py_models() -> dict[str, type[BaseModel]]:
    return {
        name: obj
        for name, obj in vars(models).items()
        if isinstance(obj, type) and issubclass(obj, models.Contract) and obj is not models.Contract
    }


def test_every_python_enum_is_declared_in_typescript() -> None:
    """Both directions. A union the TS declares and Python does not have is as
    much a drift as the reverse, and only one of the two is a compile error."""
    ts, py = _ts_unions(), _py_enums()
    assert set(ts) == set(py), (
        f"only in contracts.ts: {sorted(set(ts) - set(py))}; "
        f"only in Python: {sorted(set(py) - set(ts))}"
    )
    for name, enum in py.items():
        assert ts[name] == {m.value for m in enum}, f"{name} members differ"


def test_every_wire_model_is_declared_field_for_field() -> None:
    """Model fields plus whatever the serialiser attaches, and nothing else."""
    ts, py = _ts_interfaces(), _py_models()
    assert set(ts) == set(py) - NOT_ON_THE_WIRE, (
        f"only in contracts.ts: {sorted(set(ts) - set(py))}; "
        f"only in Python: {sorted(set(py) - NOT_ON_THE_WIRE - set(ts))}"
    )
    for name, fields in ts.items():
        expected = set(py[name].model_fields) | SERIALISED_EXTRAS.get(name, set())
        assert fields == expected, f"{name} fields differ"


def test_the_declared_extras_are_what_the_serialiser_actually_adds() -> None:
    """`SERIALISED_EXTRAS` is derived, not trusted.

    It is the pivot the model check turns on: an entry left in it after the
    serialiser stopped sending the field would make `contracts.ts` declare a
    field the browser never receives, and a surface that renders an absent field
    shows a blank cell, which on these screens reads as "nothing to report".
    """
    packet = dream_packet()
    row = row_json(packet.rows[0])
    assert row["assessments"], "the Dream fixture has no assessment to check `applicable` on"
    got = {
        "HoldingRow": set(row) - set(models.HoldingRow.model_fields),
        "PacketTotals": set(totals_json(packet.totals())) - set(models.PacketTotals.model_fields),
        "RequirementAssessment": set(row["assessments"][0])
        - set(models.RequirementAssessment.model_fields),
    }
    assert got == SERIALISED_EXTRAS


def test_every_python_property_that_reaches_the_wire_is_declared() -> None:
    """The computed fields are load-bearing, so their presence is asserted.

    `supported`, `unsupported_reasons`, `approved`, `applicable` and
    `contains_unsupported_inputs` are Python `@property`; Pydantic does not
    serialise properties, so for a while none of them reached the browser and
    every screen said "not supplied by API". `api/serialize.py` attaches them by
    hand now. If one stopped arriving, the screens would render it as a blank —
    which is the failure this whole arrangement exists to prevent — so the
    browser is required to declare exactly the ones that arrive.
    """
    declared = {field for fields in _ts_interfaces().values() for field in fields}
    properties = {
        name
        for model in _py_models().values()
        for name, attr in vars(model).items()
        if isinstance(attr, property)
    }
    assert properties, "no @property found — this test would pass vacuously"
    serialised = {field for fields in SERIALISED_EXTRAS.values() for field in fields}
    assert properties <= serialised, (
        f"a @property never reaches the wire: {properties - serialised}"
    )
    assert properties <= declared, f"contracts.ts does not declare: {properties - declared}"


def test_every_route_envelope_is_declared_key_for_key() -> None:
    """`responses.ts` against the routes, not against a description of them."""
    payloads = capture()
    for route, interface in ROUTE_INTERFACES.items():
        assert _fields(interface) == set(payloads[route]), (
            f"{interface} does not match GET {capture_web_fixture.ROUTES[route]}"
        )


def test_the_evidence_claim_is_a_claim_plus_what_the_route_adds() -> None:
    """`GET /holdings/{id}` dumps the `Claim` model and adds one key.

    Checked against the model rather than against a captured instance because
    the fixture branch has no claim store, so the captured evidence list is
    empty — and an empty list agrees with any shape at all.

    The added key is read off `api/routes.py` rather than written here. It used
    to be the literal `"citations"`, which meant this assertion described the
    route instead of consulting it: the route moved to `facts`, this stayed
    green, and the browser crashed on every claim in the ledger.
    """
    extra = {routes.EVIDENCE_CLAIM_EXTRA}
    assert _fields("EvidenceClaim") == set(models.Claim.model_fields) | extra


def _a_recomputation() -> Recomputation:
    """Fluidstack's 25Q4 finding, constructed rather than captured.

    Constructed because the snapshot cannot supply one: the fixture branch has no
    ledger to derive from, so `recomputations` arrives as `null` and a null
    agrees with every shape there is — the same reason `EvidenceClaim` above is
    read off its model instead of off an instance.

    Every field is populated and `per_class` holds an entry, because an empty
    list agrees with every shape too, and `RecomputedClass` is the interface the
    per-class working is rendered from.
    """
    return Recomputation(
        holding_id="fluidstack",
        outcome=Outcome.FAIL,
        reason="PER_CLASS_SHARES_X_PPS",
        derived=Money(amount=Decimal("2500000"), currency="USD"),
        reported=Money(amount=Decimal("6000000"), currency="USD"),
        difference=Money(amount=Decimal("3500000"), currency="USD"),
        evidence_claim_ids=("fluidstack_spa",),
        per_class=(
            ClassAmount(
                lot_id="fluidstack_series_a",
                security_class="series_a",
                shares=100_000,
                price_per_share=Decimal("10.000000"),
                amount=Money(amount=Decimal("1000000"), currency="USD"),
                cross_class=False,
            ),
        ),
        policy_version="v1",
    )


def test_the_recomputation_is_declared_key_for_key() -> None:
    """SPEC §8's V2, which reached the browser compared to nothing.

    `Recomputation` and `RecomputedClass` are hand-written TypeScript with no
    Pydantic model behind them, and `recomputation_json` is a hand-written dict
    literal. Neither of the two checks above sees them: the model check reads
    `contracts.ts` against `models.py` and these live in `responses.ts`, and the
    envelope check walks the captured payloads, where `recomputations` is `null`.

    So renaming `security_class` to `class` in the serialiser left the Python
    gate green and `tsc` green, and put `undefined` where every class name goes —
    on the one screen whose entire purpose is showing which half of a mark is
    wrong. The per-class row is checked as well as the envelope, because the
    finding is only legible per class: 100,000 Series A at $10.00 plus 100,000
    Series A-2 at $15.00 against a reported 6,000,000 priced off Series B.
    """
    sent = recomputation_json(_a_recomputation())
    assert set(sent) == _fields("Recomputation")
    per_class = sent["per_class"]
    assert per_class, "no per-class row to compare — this check would pass vacuously"
    assert set(per_class[0]) == _fields("RecomputedClass")


def test_the_recomputation_carries_every_field_the_derivation_produced() -> None:
    """The serialiser against the dataclass, not only against the browser.

    The check above pins the two ends to each other, and two ends renamed
    together still agree. This one pins the wire to what the derivation actually
    computed, so a field dropped from `recomputation_json` is a red test rather
    than a value that stops arriving — `cross_class` is INV-17's flag that a
    class was priced off evidence for a class the fund does not hold, and its
    absence renders as a per-class row with nothing wrong with it.
    """
    sent = recomputation_json(_a_recomputation())
    assert set(sent) == {f.name for f in dataclass_fields(Recomputation)}
    assert set(sent["per_class"][0]) == {f.name for f in dataclass_fields(ClassAmount)}


#: The two fields on `PacketDownload` that no header carries: the filename is
#: read out of `Content-Disposition`, and the archive itself is the body. Named
#: here rather than filtered by a pattern, so adding a third undeclared field
#: has to be a decision somebody wrote down.
DOWNLOAD_WITHOUT_A_HEADER = {"filename", "blob"}


def test_the_download_interface_declares_the_headers_the_routes_actually_send() -> None:
    """`PacketDownload` against `_download_facts`, not against a description of it.

    The export routes that return a zip have no JSON envelope, so the two checks
    above cannot see them: there is no captured payload to walk and no Pydantic
    model to compare against. Everything the screen can say about a download it
    has just handed to the operating system arrives in a header, and a header the
    API renamed would reach the browser as `null` — which renders as a blank
    beside a label, and a blank where a packet id belongs reads as "this packet
    has no id" rather than as a contract that has moved.

    Both directions, for the reason the enum check states: a field the browser
    declares and the API does not send is as much a drift as the reverse, and
    only one of the two is visible from the TypeScript side.
    """
    stub = Written(
        packet_id="pkx_test",
        root=Path("/nonexistent"),
        manifest={"entries": [], "manifest_hash": "h"},
        fund_id="fund_ii",
        period_id="fund_ii_25q4",
        schema_version="0.1.0",
        policy_version="v1",
        layout=Layout(),
    )
    sent = reconciliation._download_facts(stub, present=1, withheld=0)
    assert sent, "no header to compare — this check would pass vacuously"
    declared = _fields("PacketDownload")
    assert declared > DOWNLOAD_WITHOUT_A_HEADER
    as_fields = {name.removeprefix("X-").lower().replace("-", "_") for name in sent}
    assert as_fields == declared - DOWNLOAD_WITHOUT_A_HEADER


def test_the_source_field_names_the_two_stores_the_routes_can_answer_from() -> None:
    """A demo silently serving the one-row fixture is the failure `source` exists
    to prevent, so the browser's idea of the two values is checked against the
    route that produces them."""
    members = _ts_unions(RESPONSES_TS)["Source"]
    assert members == {"ledger", "fixture"}
    routes = ROUTES_PY.read_text()
    for member in members:
        assert f'"{member}"' in routes, f"api/routes.py never returns source={member!r}"


def test_the_bundled_fixture_snapshot_is_what_the_api_serves() -> None:
    """The captured payloads, re-captured. Regenerate with
    `.venv/bin/python scripts/capture_web_fixture.py` when the change is
    intended — and read the diff, because it is the auditor-facing payload."""
    assert SNAPSHOT.exists(), (
        "web/src/fixture.api.json is missing; run scripts/capture_web_fixture.py"
    )
    assert json.loads(SNAPSHOT.read_text()) == capture()


def test_the_snapshot_covers_every_route_the_browser_reads() -> None:
    """A snapshot of half the surface says nothing about the other half.

    `GET /funds` and `GET /holdings/{id}` were added to the API after this
    capture existed, and the evidence workspace — the screen the product is for
    — reads the second of them.
    """
    assert set(json.loads(SNAPSHOT.read_text())) == set(capture_web_fixture.ROUTES)


def test_a_route_that_does_not_serve_aborts_instead_of_writing_a_partial_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half a capture is worse than none: it would commit as a real diff.

    The snapshot is the reference both gates measure against, so a run against a
    half-serving app must stop before the write rather than record whatever came
    back.
    """

    class Unavailable:
        status_code = 503

        def json(self) -> dict[str, object]:
            return {}

    class Client:
        def __init__(self, app: object) -> None:
            pass

        def get(self, url: str) -> Unavailable:
            return Unavailable()

    monkeypatch.setattr("fastapi.testclient.TestClient", Client)
    with pytest.raises(SystemExit, match="returned 503"):
        capture()


def test_the_snapshot_is_rendered_deterministically() -> None:
    """Sorted keys and a trailing newline, so a re-capture diffs as content.

    Without both, a key-order change from an unrelated edit rewrites the whole
    file and the real change is invisible in the diff — which is the only place
    anyone reviews it.
    """
    assert render({"b": 1, "a": {"d": 2, "c": 3}}) == (
        '{\n  "a": {\n    "c": 3,\n    "d": 2\n  },\n  "b": 1\n}\n'
    )


def test_capturing_writes_where_the_module_points_and_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The re-capture path works, without this suite rewriting the reference."""
    before = SNAPSHOT.read_text()
    target = tmp_path / "fixture.api.json"
    monkeypatch.setattr(capture_web_fixture, "SNAPSHOT", target)
    assert main() == target
    assert json.loads(target.read_text()) == capture()
    assert SNAPSHOT.read_text() == before, "the committed snapshot must not be a test output"


def _keys(node: object) -> set[str]:
    """Every mapping key anywhere in the payload.

    Keys, not a substring search over the text. The first version of this test
    asked whether `"supported"` appeared in the JSON and failed on
    `unsupported_amount`, which is a real field — a check that reports a
    correct payload as broken gets deleted, and takes the true half with it.
    """
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for item in node for k in _keys(item)}
    return set()


@pytest.mark.parametrize(
    "computed",
    ["supported", "unsupported_reasons", "approved", "applicable", "contains_unsupported_inputs"],
)
def test_the_snapshot_carries_the_computed_fields(computed: str) -> None:
    """What makes the fixture evidence rather than decoration.

    Each of these was absent from the wire, and every screen rendered "not
    supplied by API" in its place. That marker was true then and would be a lie
    now, and nothing else would notice — a marker where a value exists still
    looks tidy.
    """
    present = _keys(json.loads(SNAPSHOT.read_text()))
    assert "unsupported_amount" in present, "the payload is not being walked at all"
    assert computed in present


def test_no_field_reaches_the_browser_undeclared() -> None:
    """Every key in the payload is a field some TypeScript interface declares.

    The generic half of the model check: that one compares TS to Python model by
    model, and a field the API starts sending on a model nobody thought to look
    at would slip past it. This compares TS to the BYTES, so anything new on the
    wire has to be declared before this goes green.
    """
    declared = {field for _, fields in _all_declarations().values() for field in fields}
    #: `unsupported_reasons` is an object keyed by requirement code, so its
    #: keys are values, not field names.
    declared |= {code.value for code in enums.RequirementCode}
    #: Walked per route, because the snapshot's own top level is a filing
    #: convention — `funds`, `packet`, `holding`, `totals` are route names and
    #: reach no browser as fields.
    snapshot = json.loads(SNAPSHOT.read_text())
    undeclared = {key for route in snapshot.values() for key in _keys(route)} - declared
    assert undeclared == set(), f"on the wire and undeclared in TypeScript: {sorted(undeclared)}"
