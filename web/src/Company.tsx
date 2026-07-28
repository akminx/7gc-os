import { useEffect, useState } from "react";
import { AssistStrip } from "./Assist";
import { CoverageMap } from "./Coverage";
import type { HoldingRow } from "./contracts";
import type { Async } from "./data";
import { failureDetail, loadHolding } from "./data";
import { EvidencePanel } from "./Evidence";
import { ExportCompanyEvidence } from "./Export";
import type { HoldingResponse, Recomputation } from "./responses";
import { EvidenceTrail } from "./Trail";
import { Section, SourceBadge } from "./ui";
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
  fundId,
  periodId,
  measurementDate,
  rows,
  recomputations,
  selected,
  onSelect,
}: {
  fundId: string;
  periodId: string;
  measurementDate: string;
  rows: HoldingRow[];
  recomputations: Record<string, Recomputation> | null;
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

      {/* The letter's closing request, beside the picker that names its
          subject: the support for ONE portfolio company, taken away on its own.
          Here rather than next to the packet export because its subject is the
          holding selected above, and a second company picker elsewhere would be
          a second idea of which company is on screen. */}
      <ExportCompanyEvidence
        fundId={fundId}
        periodId={periodId}
        holdingId={row.holding_id}
        companyName={row.company_name}
      />

      {evidence.kind === "loading" && (
        <p className="note">Loading the evidence for this holding…</p>
      )}
      {evidence.kind === "error" && (
        <p
          className="error"
          title="A failed request and a finding of no evidence are opposite states, and must never render the same way."
        >
          Evidence request failed: {evidence.detail}. This is a failed request, not a finding of no
          evidence.
        </p>
      )}
      {evidence.kind === "ready" && (
        <>
          <Section
            title="Coverage"
            hint="Documents on file down the side, the five requirements across the top, a mark where a requirement relies on a document. A column with no mark is a gap. A row with no mark is a document nothing depends on."
          >
            <p className="note">
              <SourceBadge source={evidence.data.source} /> · holding{" "}
              <code>{evidence.data.holding_id}</code>
            </p>
            <CoverageMap claims={evidence.data.evidence} assessments={row.assessments} />
          </Section>

          <Section
            title="Evidence trail"
            note="Pick a requirement, then a figure, to open the passage that states it."
            hint="The passage on the right is the stored document version, with the cited characters marked in place at the offsets an auditor re-verifies against."
          >
            <EvidenceTrail
              assessments={row.assessments}
              claims={evidence.data.evidence}
              gaps={row.gaps}
            />
          </Section>

          <Section
            title="Ask about this company"
            note="Type a question and read the documents' own words, or read the finding restated in plain English."
            hint="The search runs no language model: it matches your words against the stored documents and quotes what it finds, with the page. The plain-English panel does use one, and everything it writes is checked against the record before it is shown."
          >
            <AssistStrip holdingId={evidence.data.holding_id} measurementDate={measurementDate} />
          </Section>

          {/* The full inventory, folded away. It is the appendix to the trail
              above — every claim on file with every figure and passage under it
              — and it is closed by default because the trail is the path a
              reader takes and this is what they check it against. */}
          <details className="appendix">
            <summary>All claims on file for this holding, in full</summary>
            <EvidencePanel holding={evidence.data} />
          </details>
        </>
      )}

      <Workspace row={row} recomputation={recomputations?.[row.holding_id]} />
    </>
  );
}
