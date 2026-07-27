import { useEffect, useState } from "react";

import { Company } from "./Company";
import { Dashboard } from "./Dashboard";
import type { Async } from "./data";
import { failureDetail, loadFunds, loadPacket } from "./data";
import type { Surface } from "./deeplink";
import { readTrail, updateTrail } from "./deeplink";
import { Evals } from "./Evals";
import { ExportPacket } from "./Export";
import { GapInventory } from "./GapInventory";
import type { FundPeriod, FundsResponse, PacketResponse } from "./responses";
import { ThemeChoiceControl } from "./Theme";
import { SourceBadge, Why } from "./ui";

/**
 * The three read-only surfaces of SPEC §12: the dual-fund dashboard, the
 * company evidence workspace, and the gap inventory.
 *
 * Approval STATE is rendered everywhere, and always with the decision type
 * named, because a transcription approval is not a fair-value approval
 * (SPEC §6.3).
 *
 * This comment used to end "there is no approve or reject control anywhere in
 * this tree". That stopped being true when §6.3's four approvable resources
 * needed somewhere for a human to actually decide: the workspace now renders
 * one, and `api/decisions.py` serves the single route behind it. A stale
 * assurance is worse than none — a reader checking whether this app can write
 * would have found the answer here and stopped looking.
 *
 * The control appears only where the deployment names its actors. With
 * `DECISION_ACTORS` unset the API returns 403 and the UI renders nothing,
 * which is how the demo stays read-only without the code having two versions.
 *
 * Which fund-period is on screen now comes from `GET /funds`. It used to be two
 * constants in the data layer, which made a screen built to compare funds show
 * exactly one, forever, whatever the ledger held.
 */

const SURFACES: { id: Surface; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "company", label: "Company evidence" },
  { id: "gaps", label: "Gap inventory" },
  { id: "evals", label: "How well does it work" },
];

function keyOf(period: FundPeriod): string {
  return `${period.fund_id}/${period.period_id}`;
}

/**
 * The fund-period picker.
 *
 * It takes the list as it comes and assumes nothing about its length. The dev
 * database currently answers with about 140 entries, most of them left behind by
 * a schema test; the same screen has to work when that is cleaned up to six, and
 * neither number is written down anywhere here.
 */
function PeriodPicker({
  periods,
  chosen,
  onChoose,
}: {
  periods: FundPeriod[];
  chosen: string;
  onChoose: (key: string) => void;
}) {
  return (
    <label className="picker">
      <span>Fund · period</span>
      <select
        value={chosen}
        onChange={(event) => {
          onChoose(event.target.value);
        }}
      >
        {periods.map((period) => (
          <option key={keyOf(period)} value={keyOf(period)}>
            {period.fund_id} · {period.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function Surfaces({ packet }: { packet: PacketResponse }) {
  // Opened from the address bar, so a link a partner sent lands on the surface
  // and the company it names rather than on the dashboard with a note about
  // where to click next. Read ONCE, at mount: after that the reader's clicks
  // own the URL, and re-reading it on every render would make the app fight
  // whoever moved last.
  const [surface, setSurface] = useState<Surface>(() => readTrail().surface ?? "dashboard");
  const [selected, setSelected] = useState<string | null>(() => readTrail().holdingId ?? null);

  const show = (next: Surface) => {
    setSurface(next);
    updateTrail({ surface: next });
  };

  const choose = (holdingId: string) => {
    setSelected(holdingId);
    updateTrail({ holdingId });
  };

  const open = (holdingId: string) => {
    setSelected(holdingId);
    setSurface("company");
    updateTrail({ surface: "company", holdingId });
  };

  return (
    <>
      <nav className="tabs">
        {SURFACES.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={tab.id === surface ? "tab tab--on" : "tab"}
            aria-current={tab.id === surface}
            onClick={() => {
              show(tab.id);
            }}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      {surface === "dashboard" && <Dashboard packet={packet} onOpenCompany={open} />}
      {surface === "company" && (
        <Company
          fundId={packet.fund_id}
          periodId={packet.period.id}
          rows={packet.rows}
          recomputations={packet.recomputations}
          selected={selected}
          onSelect={choose}
        />
      )}
      {surface === "gaps" && <GapInventory packet={packet} />}
      {surface === "evals" && <Evals />}
    </>
  );
}

export function App() {
  const [funds, setFunds] = useState<Async<FundsResponse>>({ kind: "loading" });
  // The fund-period a link names, if it names one. `keyOf` is the same shape
  // the picker uses, so a link and a click produce one value and not two.
  const [chosen, setChosen] = useState<string | null>(() => {
    const trail = readTrail();
    return trail.fundId === undefined || trail.periodId === undefined
      ? null
      : `${trail.fundId}/${trail.periodId}`;
  });
  const [packet, setPacket] = useState<Async<PacketResponse>>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    loadFunds()
      .then((data) => {
        if (live) setFunds({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (live) setFunds({ kind: "error", detail: failureDetail(error) });
      });
    return () => {
      live = false;
    };
  }, []);

  const periods = funds.kind === "ready" ? funds.data.periods : [];
  const first = periods.at(0);
  const current = periods.find((p) => keyOf(p) === chosen) ?? first;
  const fundId = current === undefined ? null : current.fund_id;
  const periodId = current === undefined ? null : current.period_id;

  // The fund-period the app actually landed on, written back to the address bar
  // — including when a link named one the ledger does not hold and `current`
  // fell back to the first. A URL that keeps naming a period nobody is looking
  // at is a link that sends the next reader somewhere the sender never was.
  useEffect(() => {
    if (fundId !== null && periodId !== null) updateTrail({ fundId, periodId });
  }, [fundId, periodId]);

  useEffect(() => {
    if (fundId === null || periodId === null) return;
    let live = true;
    setPacket({ kind: "loading" });
    loadPacket(fundId, periodId)
      .then((data) => {
        if (live) setPacket({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (live) setPacket({ kind: "error", detail: failureDetail(error) });
      });
    return () => {
      live = false;
    };
  }, [fundId, periodId]);

  return (
    <main>
      <header className="masthead">
        <div className="masthead__top">
          <h1>7GC OS — Valuation Evidence Ledger</h1>
          <ThemeChoiceControl />
        </div>
        <p className="note">
          Audit support, read-only.{" "}
          <Why text="Every figure on these screens is supplied by the API; this surface formats and orders, and computes nothing." />
        </p>
        {funds.kind === "ready" && (
          <p className="note">
            <SourceBadge source={funds.data.source} />
          </p>
        )}
      </header>

      {funds.kind === "loading" && (
        <p className="note">
          Loading the fund list… a free Render instance sleeps after 15 minutes idle and takes about
          50 seconds to wake.
        </p>
      )}
      {funds.kind === "error" && <p className="error">Fund list failed: {funds.detail}</p>}
      {funds.kind === "ready" && current === undefined && (
        <p className="note" title="That is an empty ledger, not an empty screen.">
          The API lists no fund-period that a packet can be built for.
        </p>
      )}
      {current !== undefined && (
        <div className="bar">
          <PeriodPicker periods={periods} chosen={keyOf(current)} onChoose={setChosen} />
          {/* The exporter runs against the fund-period on screen, so the control
              sits beside the picker that chooses it rather than at the end of a
              surface. A packet button one scroll away from the period selector
              is a button whose subject the reader has to remember. */}
          <ExportPacket fundId={current.fund_id} periodId={current.period_id} />
        </div>
      )}

      {current !== undefined && packet.kind === "loading" && (
        <p className="note">Loading the packet…</p>
      )}
      {current !== undefined && packet.kind === "error" && (
        <p className="error">Packet request failed: {packet.detail}</p>
      )}
      {current !== undefined && packet.kind === "ready" && <Surfaces packet={packet.data} />}
    </main>
  );
}
