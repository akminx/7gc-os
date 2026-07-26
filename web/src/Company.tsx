import { useEffect, useState } from "react";

import type { HoldingRow } from "./contracts";
import type { Async } from "./data";
import { failureDetail, loadHolding } from "./data";
import { EvidencePanel } from "./Evidence";
import type { HoldingResponse } from "./responses";
import { Workspace } from "./Workspace";

/**
 * SPEC §12.2 · the company evidence workspace, and the request that fills it.
 *
 * The packet row and the evidence are two different reads: the row comes from
 * the packet already on screen, the claims and their cited passages come from
 * `GET /holdings/{id}` when a company is selected. Kept separate because the
 * packet is one request for a whole fund and the evidence is one request per
 * holding — folding the second into the first would make opening the dashboard
 * fetch every document citation in the fund.
 *
 * The evidence comes FIRST on the page. It is the answer to the question the
 * engagement letter asks; the mark's own figures are context for it.
 */
export function Company({
  rows,
  selected,
  onSelect,
}: {
  rows: HoldingRow[];
  selected: string | null;
  onSelect: (holdingId: string) => void;
}) {
  const row = rows.find((candidate) => candidate.holding_id === selected) ?? rows.at(0);
  const holdingId = row === undefined ? null : row.holding_id;
  const [evidence, setEvidence] = useState<Async<HoldingResponse>>({ kind: "loading" });

  useEffect(() => {
    if (holdingId === null) return;
    let live = true;
    setEvidence({ kind: "loading" });
    loadHolding(holdingId)
      .then((data) => {
        if (live) setEvidence({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (live) setEvidence({ kind: "error", detail: failureDetail(error) });
      });
    return () => {
      live = false;
    };
  }, [holdingId]);

  if (row === undefined) return <p className="note">This packet contains no holdings.</p>;

  return (
    <>
      <label className="picker">
        <span>Holding</span>
        <select
          value={row.holding_id}
          onChange={(event) => {
            onSelect(event.target.value);
          }}
        >
          {rows.map((candidate) => (
            <option key={candidate.holding_id} value={candidate.holding_id}>
              {candidate.company_name}
            </option>
          ))}
        </select>
      </label>

      {evidence.kind === "loading" && (
        <p className="note">Loading the evidence for this holding…</p>
      )}
      {evidence.kind === "error" && (
        <p className="error">
          Evidence request failed: {evidence.detail}. This is a failed request, not a finding of no
          evidence — the two must never render the same way.
        </p>
      )}
      {evidence.kind === "ready" && <EvidencePanel holding={evidence.data} />}

      <Workspace row={row} />
    </>
  );
}
