import { useEffect, useState } from "react";

import { Company } from "./Company";
import { Dashboard } from "./Dashboard";
import type { Async } from "./data";
import { failureDetail, loadFunds, loadPacket } from "./data";
import { GapInventory } from "./GapInventory";
import type { FundPeriod, FundsResponse, PacketResponse } from "./responses";
import { SourceBadge } from "./ui";

/**
 * The three read-only surfaces of SPEC §12: the dual-fund dashboard, the
 * company evidence workspace, and the gap inventory.
 *
 * SPEC §3.1 · the public surface is read-only. There is no approve or reject
 * control anywhere in this tree — approval STATE is rendered, and always with
 * the decision type named, because a transcription approval is not a fair-value
 * approval (SPEC §6.3).
 *
 * Which fund-period is on screen now comes from `GET /funds`. It used to be two
 * constants in the data layer, which made a screen built to compare funds show
 * exactly one, forever, whatever the ledger held.
 */

type Surface = "dashboard" | "company" | "gaps";

const SURFACES: { id: Surface; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "company", label: "Company evidence" },
  { id: "gaps", label: "Gap inventory" },
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
  const [surface, setSurface] = useState<Surface>("dashboard");
  const [selected, setSelected] = useState<string | null>(null);

  const open = (holdingId: string) => {
    setSelected(holdingId);
    setSurface("company");
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
              setSurface(tab.id);
            }}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      {surface === "dashboard" && <Dashboard packet={packet} onOpenCompany={open} />}
      {surface === "company" && (
        <Company rows={packet.rows} selected={selected} onSelect={setSelected} />
      )}
      {surface === "gaps" && <GapInventory packet={packet} />}
    </>
  );
}

export function App() {
  const [funds, setFunds] = useState<Async<FundsResponse>>({ kind: "loading" });
  const [chosen, setChosen] = useState<string | null>(null);
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
        <h1>7GC OS — Valuation Evidence Ledger</h1>
        <p className="note">
          Audit support, read-only. Every figure on these screens is supplied by the API; this
          surface formats and orders, and computes nothing.
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
        <p className="note">
          The API lists no fund-period that a packet can be built for. That is an empty ledger, not
          an empty screen.
        </p>
      )}
      {current !== undefined && (
        <PeriodPicker periods={periods} chosen={keyOf(current)} onChoose={setChosen} />
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
