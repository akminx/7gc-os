import { describe, expect, it } from "vitest";
import {
  FIXTURE_FUNDS,
  FIXTURE_HOLDING,
  FIXTURE_PACKET,
  FIXTURE_ROW,
  FIXTURE_TOTALS,
} from "./fixture";
import SNAPSHOT from "./fixture.api.json";

/**
 * Half of the guard that keeps `fixture.ts` a capture rather than a drawing.
 *
 * `fixture.api.json` is written by `scripts/capture_web_fixture.py` straight out
 * of all four read routes, and `tests/test_web_contracts.py` re-captures it on
 * every Python gate run — so the snapshot is what the API serves. This file
 * closes the other side: that the module the browser actually bundles still
 * equals the snapshot.
 *
 * Split across the two gates on purpose. Comparing `fixture.ts` to the live
 * serialiser in one step needs both runtimes in one process, and the version of
 * that check that shells out to `vite-node` from pytest stops running the first
 * time `node_modules` is absent — passing, not failing. This repo has found six
 * checks that passed because they measured nothing; this is not going to be the
 * seventh.
 *
 * Why it can drift at all: `fixture.ts` is typed against `contracts.ts`, so
 * `tsc` catches a field that changed SHAPE. It cannot catch a field that changed
 * VALUE, or one the API stopped sending that the fixture still carries — and a
 * stale amount rendered beside a real caption is precisely the polished wrong
 * number this project is arranged against.
 */

describe("the bundled fixture", () => {
  it("is the packet the API serves, not a drawing of it", () => {
    expect(FIXTURE_PACKET).toEqual(SNAPSHOT.packet);
  });

  it("lists the fund-periods the API lists", () => {
    expect(FIXTURE_FUNDS).toEqual(SNAPSHOT.funds);
  });

  it("carries the totals the API serves from the totals route", () => {
    expect(FIXTURE_TOTALS).toEqual(SNAPSHOT.totals);
  });

  it("carries the holding-evidence response the API serves", () => {
    expect(FIXTURE_HOLDING).toEqual(SNAPSHOT.holding);
  });

  it("exports the first packet row as FIXTURE_ROW", () => {
    expect(FIXTURE_ROW).toEqual(SNAPSHOT.packet.rows[0]);
  });

  /**
   * The packet's embedded totals and the standalone totals route must agree
   * apart from the envelope. They are two code paths over one `PacketTotals`,
   * and the whole reason the totals moved inside the packet was that two
   * separately-fetched figures had nothing tying them together.
   */
  it("serves the same totals inside the packet as it does on their own route", () => {
    expect(FIXTURE_PACKET.totals).toEqual(
      Object.fromEntries(Object.entries(SNAPSHOT.totals).filter(([k]) => k !== "source")),
    );
  });

  /**
   * These five used to be absent, and every screen said so. They are Python
   * `@property`, which Pydantic does not serialise; `api/serialize.py` now
   * attaches each one by hand. Asserted against the API's own output because a
   * `NotSupplied` marker rendered where a value exists still looks tidy, and
   * nothing else would notice.
   */
  it("carries the computed fields the API attaches to the model dump", () => {
    const keys = (node: unknown): string[] => {
      if (Array.isArray(node)) return node.flatMap(keys);
      if (node !== null && typeof node === "object")
        return Object.entries(node).flatMap(([k, v]) => [k, ...keys(v)]);
      return [];
    };
    const present = new Set(keys({ FIXTURE_PACKET, FIXTURE_TOTALS }));
    expect(present.has("unsupported_amount")).toBe(true);
    for (const computed of [
      "supported",
      "unsupported_reasons",
      "approved",
      "applicable",
      "contains_unsupported_inputs",
      "unheld_gap_positions",
    ]) {
      expect(present.has(computed)).toBe(true);
    }
  });

  /** The offline demo must announce itself as the demo, in the data itself. */
  it("says it is the fixture, on every response", () => {
    expect(FIXTURE_FUNDS.source).toBe("fixture");
    expect(FIXTURE_PACKET.source).toBe("fixture");
    expect(FIXTURE_TOTALS.source).toBe("fixture");
    expect(FIXTURE_HOLDING.source).toBe("fixture");
  });
});
