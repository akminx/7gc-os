import { useState } from "react";

import { exportPacket, failureDetail } from "./data";
import type { ExportResponse } from "./responses";

/**
 * Build the auditor packet for one fund-period.
 *
 * The exporter validates before it publishes: every citation is resolved
 * against the text actually exported, every manifest entry is re-hashed off
 * disk, and a packet holding an approved-but-unsupported position is refused by
 * `PacketTotals` itself. So a refusal here is a finding, not a fault, and it is
 * rendered in the API's own words — the message names which citation or which
 * position, and "Export failed" would keep the failure and throw the finding
 * away.
 *
 * What comes back is stated precisely because two nearby things are not true:
 * nothing is downloaded to this browser, and nothing is recorded in the ledger.
 * The packet is written on the API host and `recorded_in_ledger` is on the wire
 * saying so, since "a packet was generated" and "a packet version was
 * registered" are different facts (SPEC §6.3).
 */

type Outcome =
  | { kind: "idle" }
  | { kind: "building" }
  | { kind: "built"; result: ExportResponse }
  | { kind: "refused"; detail: string };

function Result({ result }: { result: ExportResponse }) {
  return (
    <div className="export__result">
      <p className="export__headline">
        Packet <code>{result.packet_id}</code> written on the API host. {result.file_count} files.
      </p>
      <dl className="export__facts">
        <div>
          <dt>directory</dt>
          <dd>
            <code>{result.root}</code>
          </dd>
        </div>
        <div>
          <dt>manifest hash</dt>
          <dd>
            <code>{result.manifest_hash}</code>
          </dd>
        </div>
        <div>
          <dt>schema · policy</dt>
          <dd>
            {result.schema_version} · {result.policy_version}
          </dd>
        </div>
        <div>
          <dt>recorded in the ledger</dt>
          <dd>{result.recorded_in_ledger ? "yes" : "no · generated only, no packet version"}</dd>
        </div>
      </dl>
      <p
        className="note"
        title="The files are on the machine serving the API, under the directory above. Generating the files and recording an official packet version are different actions; this does the first."
      >
        Nothing was downloaded to this browser, and no packet version was registered.
      </p>
    </div>
  );
}

export function ExportPacket({ fundId, periodId }: { fundId: string; periodId: string }) {
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const building = outcome.kind === "building";

  const build = () => {
    setOutcome({ kind: "building" });
    exportPacket(fundId, periodId)
      .then((result) => {
        setOutcome({ kind: "built", result });
      })
      .catch((error: unknown) => {
        setOutcome({ kind: "refused", detail: failureDetail(error) });
      });
  };

  return (
    <div className="export">
      <button type="button" className="export__act" disabled={building} onClick={build}>
        {building ? "Building the packet…" : "Export auditor packet"}
      </button>
      <span className="export__scope">
        {fundId} · {periodId}
      </span>
      {building && (
        <p
          className="note"
          aria-live="polite"
          title="Reading the ledger, resolving every citation against the exported text, and re-hashing each file."
        >
          Validating. A packet that fails validation is not published.
        </p>
      )}
      {outcome.kind === "built" && <Result result={outcome.result} />}
      {outcome.kind === "refused" && (
        <p className="error" role="alert">
          The exporter refused to publish this packet: {outcome.detail} Nothing was written. Fix the
          citation or the approval it names, then export again.
        </p>
      )}
    </div>
  );
}
