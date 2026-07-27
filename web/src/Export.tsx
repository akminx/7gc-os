import { useState } from "react";

import { downloadCompanyEvidence, downloadPacket, exportPacket, failureDetail } from "./data";
import type { ExportResponse, PacketDownload } from "./responses";

/**
 * Build the auditor packet for one fund-period, and take it away.
 *
 * The exporter validates before it publishes: every citation is resolved
 * against the text actually exported, every manifest entry is re-hashed off
 * disk, and a packet holding an approved-but-unsupported position is refused by
 * `PacketTotals` itself. So a refusal here is a finding, not a fault, and it is
 * rendered in the API's own words — the message names which citation or which
 * position, and "Export failed" would keep the failure and throw the finding
 * away. That is true of all three controls on this surface.
 *
 * TWO ACTIONS, DELIBERATELY NOT ONE.
 *
 * *Build* generates the packet on the API host and reports where it landed and
 * what it contains. Nothing is downloaded by it, and nothing is recorded in the
 * ledger: `recorded_in_ledger` is on the wire saying so, because "a packet was
 * generated" and "a packet version was registered" are different facts
 * (SPEC §6.3). It is kept because a refusal reported in full, on the page, is
 * itself a deliverable, and a download that either arrives or does not is a
 * poor place to read one.
 *
 * *Download* streams the same packet to this browser as a zip. This docstring
 * used to state, as a deliberate fact, that nothing is downloaded here — which
 * was true when the only route was the JSON one, and stopped being true the day
 * `export.zip` was wired up. The second half of that sentence still holds: a
 * download registers nothing either, and every archive says so in a header the
 * screen renders.
 *
 * The per-company download is the same archive cut to one portfolio company —
 * the engagement letter's closing request, made obtainable one company at a
 * time. It carries that company's documents and every table whole, and states
 * inside itself which files it withheld.
 */

type Outcome =
  | { kind: "idle" }
  | { kind: "building" }
  | { kind: "built"; result: ExportResponse }
  | { kind: "refused"; detail: string };

type Delivery =
  | { kind: "idle" }
  | { kind: "downloading" }
  | { kind: "delivered"; archive: PacketDownload }
  | { kind: "refused"; detail: string };

/**
 * Hand the archive to the browser's own download machinery.
 *
 * An object URL and a synthetic click, which is the only way a `fetch`ed body
 * becomes a file on the reader's disk. The anchor is attached before the click
 * and removed after: a detached anchor is ignored by some browsers, and a
 * download that silently does nothing is worse than a button that says it
 * cannot.
 *
 * The object URL is revoked immediately afterwards. It holds the whole packet
 * in memory, and a page left open across several exports would accumulate every
 * one of them.
 */
function save(archive: PacketDownload): void {
  const href = URL.createObjectURL(archive.blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = archive.filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

/**
 * The state machine both download buttons share.
 *
 * The request is passed at click time rather than held, so one hook serves the
 * whole packet and one company without either of them owning a stale closure
 * over a fund-period the reader has since changed.
 */
function useDelivery(): {
  delivery: Delivery;
  start: (request: () => Promise<PacketDownload>) => void;
} {
  const [delivery, setDelivery] = useState<Delivery>({ kind: "idle" });
  const start = (request: () => Promise<PacketDownload>) => {
    setDelivery({ kind: "downloading" });
    request()
      .then((archive) => {
        save(archive);
        setDelivery({ kind: "delivered", archive });
      })
      .catch((error: unknown) => {
        setDelivery({ kind: "refused", detail: failureDetail(error) });
      });
  };
  return { delivery, start };
}

/**
 * What arrived, in the terms the response supplied.
 *
 * Every figure here is a header the API sent. The counts are rendered as the
 * strings they arrived as: they are the API's counts of the manifest's entries,
 * and adding them up here to check would be this surface computing an aggregate
 * it does not own. The archive carries a note that does that arithmetic against
 * the manifest travelling beside it, which is where an auditor can act on it.
 */
function Delivered({ archive }: { archive: PacketDownload }) {
  const withheld = archive.withheld_file_count !== "0";
  return (
    <div className="export__result">
      <p className="export__headline">
        Downloaded <code>{archive.filename}</code> — {archive.file_count} packet files from{" "}
        <code>{archive.packet_id}</code>.
      </p>
      <dl className="export__facts">
        <div>
          <dt>manifest hash</dt>
          <dd>
            <code>{archive.manifest_hash}</code>
          </dd>
        </div>
        <div>
          <dt>files withheld</dt>
          <dd>
            {withheld
              ? `${archive.withheld_file_count} · other companies' source documents`
              : "none · this is the whole packet"}
          </dd>
        </div>
        <div>
          <dt>recorded in the ledger</dt>
          <dd>{archive.recorded_in_ledger ? "yes" : "no · generated only, no packet version"}</dd>
        </div>
      </dl>
      {withheld && (
        <p
          className="note"
          title="The tables describe the whole fund-period. A gap report trimmed to one company would report fewer findings than the packet found."
        >
          Every table, the workbook and the manifest are the full packet's, unmodified. Only the
          other companies' source documents were left out, and COMPANY_SCOPE.txt inside the archive
          names every one of them.
        </p>
      )}
    </div>
  );
}

function Refusal({ detail }: { detail: string }) {
  return (
    <p className="error" role="alert">
      The exporter refused to publish this packet: {detail} Nothing was written. Fix the citation or
      the approval it names, then export again.
    </p>
  );
}

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
        This build wrote to the API host and downloaded nothing, and no packet version was
        registered.
      </p>
    </div>
  );
}

export function ExportPacket({ fundId, periodId }: { fundId: string; periodId: string }) {
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });
  const { delivery, start } = useDelivery();
  const building = outcome.kind === "building";
  const downloading = delivery.kind === "downloading";

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
      <button
        type="button"
        className="export__act"
        disabled={downloading}
        onClick={() => {
          start(() => downloadPacket(fundId, periodId));
        }}
      >
        {downloading ? "Assembling the download…" : "Download packet (.zip)"}
      </button>
      <span className="export__scope">
        {fundId} · {periodId}
      </span>
      {(building || downloading) && (
        <p
          className="note"
          aria-live="polite"
          title="Reading the ledger, resolving every citation against the exported text, and re-hashing each file."
        >
          Validating. A packet that fails validation is not published.
        </p>
      )}
      {outcome.kind === "built" && <Result result={outcome.result} />}
      {outcome.kind === "refused" && <Refusal detail={outcome.detail} />}
      {delivery.kind === "delivered" && <Delivered archive={delivery.archive} />}
      {delivery.kind === "refused" && <Refusal detail={delivery.detail} />}
    </div>
  );
}

/**
 * The engagement letter's closing request, as a button: "the support organized
 * by portfolio company", one company at a time.
 *
 * It sits with the company workspace rather than beside the packet control,
 * because its subject is the holding already selected there. A second company
 * picker next to the period picker would be a second idea of which company the
 * reader is looking at, and the two would disagree the moment anyone used them.
 */
export function ExportCompanyEvidence({
  fundId,
  periodId,
  holdingId,
  companyName,
}: {
  fundId: string;
  periodId: string;
  holdingId: string;
  companyName: string;
}) {
  const { delivery, start } = useDelivery();
  const downloading = delivery.kind === "downloading";

  return (
    <div className="export">
      <button
        type="button"
        className="export__act"
        disabled={downloading}
        onClick={() => {
          start(() => downloadCompanyEvidence(fundId, periodId, holdingId));
        }}
      >
        {downloading ? "Assembling the download…" : `Download ${companyName} evidence (.zip)`}
      </button>
      <span className="export__scope">
        {holdingId} · {periodId}
      </span>
      {downloading && (
        <p className="note" aria-live="polite">
          Building the whole packet and cutting this company's slice out of it. A packet that fails
          validation is not published, whichever company was asked for.
        </p>
      )}
      {delivery.kind === "delivered" && <Delivered archive={delivery.archive} />}
      {delivery.kind === "refused" && <Refusal detail={delivery.detail} />}
    </div>
  );
}
