import { useEffect, useState } from "react";

import type { Async } from "./data";
import { failureDetail, loadEvals } from "./data";
import { outcomeGloss } from "./derivation.labels";
import { formatMoney } from "./format";
import { REQUIREMENT } from "./labels";
import type { EvalsResponse, RecallAtK, RetrievalMiss } from "./responses";
import { Section, SourceBadge, Why } from "./ui";

/**
 * SPEC §11 · what this system has been measured to do.
 *
 * **The unflattering number leads.** A page of green hundreds is marketing and a
 * reader discounts every figure on it; volunteering the weak one is what makes
 * the strong ones credible. So the blind Recall figure is the first thing on the
 * screen and the entity-scoped one stands beside it, smaller, with the reason
 * they differ — the SQL filter leaves about one candidate document per case, so
 * the scoped number scores the filter and not the ranker.
 *
 * **Nothing here is computed.** Every count arrives from `GET /evals`, which
 * measures it when the request lands. This component divides nothing, sums
 * nothing and ranks nothing: `scripts/check-web-arch.mjs` refuses a browser that
 * turns one count into a rate, and it is right to — a percentage is a conclusion.
 * Counts render as `24 of 40`, which is the auditable form.
 *
 * **Every miss is named, and so is every blind spot.** "Recall@1 is 39/40" is a
 * score; "the miss is Lucra's existence-and-cost at 25Q4" is a finding. And the
 * last block on the page is what this page does NOT measure, with the command
 * that measures each one — including the largest: nothing here checks whether a
 * citation that resolves is the RIGHT passage.
 */

const BLIND_NOTE =
  "Blind means the SQL entity filter is removed, so the ranker is asked to find the right document among all twenty rather than among the one or two already narrowed to this holding. It is not how retrieval runs in the product; it is the only way to say what the ranker is worth on its own.";

const SCOPED_NOTE =
  "Entity-scoped is how retrieval actually runs. This corpus leaves about one candidate document per case after the filter, so a recall of 1.000 over a candidate set of one measures the SQL filter and says almost nothing about the ranking.";

/** A count and its denominator. Never a percentage — the API sends both. */
function Count({ of, n, label }: { of: number; n: number; label: string }) {
  return (
    <span className="count">
      <span className="count__n">{n}</span>
      <span className="count__of"> of {of}</span>
      <span className="count__label">{label}</span>
    </span>
  );
}

function RecallBlock({
  title,
  note,
  rows,
  lead,
}: {
  title: string;
  note: string;
  rows: (RecallAtK | undefined)[];
  lead?: boolean;
}) {
  return (
    <div className={lead ? "recall recall--lead" : "recall"}>
      <p className="recall__title">
        {title} <Why text={note} />
      </p>
      <ul className="recall__rows">
        {rows.map((row) =>
          row === undefined ? null : (
            <li key={row.k}>
              <span className="recall__k">top {row.k}</span>
              <Count n={row.found_some_relied_on} of={row.cases} label="found some support" />
              <Count n={row.found_every_relied_on} of={row.cases} label="found all of it" />
              <span className="recall__cand">
                {row.candidate_documents} documents returned over {row.cases} cases
              </span>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

function Miss({ miss }: { miss: RetrievalMiss }) {
  return (
    <li className="miss">
      <span className="miss__where">
        {miss.company_name} · {REQUIREMENT[miss.requirement].label} · {miss.measurement_date}
      </span>
      <span className="miss__scope">
        {miss.scope}, top {miss.k}
      </span>
      <span className="miss__detail">
        the ledger relies on {miss.relied_on.join(", ")}; retrieval returned{" "}
        {miss.retrieved.length === 0 ? "nothing" : miss.retrieved.join(", ")}
      </span>
    </li>
  );
}

function Measured({ data }: { data: EvalsResponse }) {
  const blind = data.retrieval.blind;
  const scoped = data.retrieval.scoped;
  const extraction = data.extraction;
  const outcomes = Object.entries(data.validators.outcomes);
  return (
    <>
      <Section
        title="Retrieval"
        note="The blind figure first. It is the one that says what the ranker does."
        hint="Recall is measured by running the retrieval against a gold set read out of `claim_requirement` — the table recording which requirement each document is relied upon for. So it measures whether retrieval finds what the ledger already relies on, not whether the ledger relies on the right documents."
      >
        <p className="note">
          {data.retrieval.retrievals_run} retrievals run over {data.retrieval.gold_cases} gold cases
          when this page was requested.
        </p>
        <div className="recalls">
          <RecallBlock
            lead
            title="Blind — the entity filter removed"
            note={BLIND_NOTE}
            rows={data.retrieval.k_reported.map((k) => blind[`k${k}`])}
          />
          <RecallBlock
            title="Entity-scoped — how retrieval actually runs"
            note={SCOPED_NOTE}
            rows={data.retrieval.k_reported.map((k) => scoped[`k${k}`])}
          />
        </div>
        <details className="appendix" open>
          <summary>
            Every case where retrieval returned nothing the ledger relies on ({" "}
            {data.retrieval.misses.length} )
          </summary>
          <ul className="misses">
            {data.retrieval.misses.map((miss) => (
              <Miss
                key={`${miss.scope}:${miss.k}:${miss.holding_id}:${miss.requirement}:${miss.measurement_date}`}
                miss={miss}
              />
            ))}
          </ul>
        </details>
      </Section>

      <Section
        title="Citations"
        hint="Every stored citation re-resolved against the text it points into. The database enforces the same equality on write; this measures whether the rows satisfy it now, which is a different statement from `a constraint exists`."
      >
        <Count
          n={data.citations.resolving}
          of={data.citations.total}
          label="offsets select the stored quote"
        />
        {data.citations.failures.length > 0 && (
          <ul className="misses">
            {data.citations.failures.map((failure) => (
              <li className="miss" key={failure.fact_id}>
                <span className="miss__where">
                  {failure.claim_id} · {failure.field_name}
                </span>
                <span className="miss__detail">
                  chars {failure.chars[0]}–{failure.chars[1]} in {failure.document_version_id}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Model extraction"
        note="The refusals are the result, not the fault."
        hint="A recorded call, replayed. Never a live one: CI has no key and must not need one, and a page that called a model would report a different number every time it was opened."
      >
        {!extraction.measured ? (
          <p className="note">Not measured: {extraction.why}</p>
        ) : (
          <>
            <p className="note">
              {extraction.model} on {extraction.document}
            </p>
            <Count
              n={extraction.accepted ?? 0}
              of={extraction.proposed ?? 0}
              label="proposed figures the citation binding accepted"
            />
            <ul className="refusals">
              {(extraction.refused ?? []).map((refusal) => (
                <li key={refusal.field_name}>
                  <code>{refusal.field_name}</code> — {refusal.value_text}
                  <span className="refusals__why">{refusal.reason}</span>
                </li>
              ))}
            </ul>
            <p className="note">
              A refusal here is the guardrail firing. One of them is the price the claim is priced
              from: the model quoted a passage that ends in a comma, and the value could not be read
              as a whole figure inside it.
            </p>
          </>
        )}
      </Section>

      <Section
        title="The system's own recomputation"
        hint="SPEC §8's V2 over every holding-date the packets carry. A census of outcomes and not a pass rate: `not_comparable` is not a soft fail and `unconfirmable` is not a weak pass, so one ratio over the six would be a number with no meaning."
      >
        <ul className="census">
          {outcomes.map(([outcome, n]) => (
            <li key={outcome}>
              <span className={`recheck-chip recheck-chip--${outcome}`}>
                {outcomeGloss(outcome).label}
              </span>
              <span className="census__n">
                {n} of {data.validators.holding_dates}
              </span>
            </li>
          ))}
        </ul>
        {data.validators.disagreements.map((row) => (
          <p className="census__finding" key={`${row.holding_id}:${row.measurement_date}`}>
            <strong>{row.company_name}</strong> at {row.measurement_date}: reported{" "}
            {formatMoney(row.reported)}, the cited evidence derives {formatMoney(row.derived)} —{" "}
            <span className="recheck__delta">{formatMoney(row.difference)} apart</span>
          </p>
        ))}
      </Section>

      <Section
        title="Per holding"
        note="Because Market reads zero across the board. That is the honest worst case and it is not hidden."
        hint="One row per position. A holding with no documents has none because the fund holds none, which is a finding about the fund's records rather than about this system."
      >
        <div className="scroller">
          <table>
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col" className="num">
                  Documents
                </th>
                <th scope="col" className="num">
                  Claims
                </th>
                <th scope="col" className="num">
                  Cited figures
                </th>
                <th scope="col" className="num">
                  Citations that fail
                </th>
                <th scope="col" className="num">
                  Requirements sufficient
                </th>
                <th scope="col">Recomputation outcomes</th>
              </tr>
            </thead>
            <tbody>
              {data.by_holding.map((row) => (
                <tr key={row.holding_id}>
                  <th scope="row">
                    {row.company_name}
                    <span className="sub">{row.packet_appearances} measurement dates</span>
                  </th>
                  <td className="num">{row.documents}</td>
                  <td className="num">{row.claims}</td>
                  <td className="num">{row.facts}</td>
                  <td className="num">{row.facts_with_a_failing_citation}</td>
                  <td className="num">
                    {row.requirements_sufficient} of {row.requirements_applicable}
                  </td>
                  <td>
                    {Object.entries(row.recomputation_outcomes).map(([outcome, n]) => (
                      <span key={outcome} className={`recheck-chip recheck-chip--${outcome}`}>
                        {outcomeGloss(outcome).label} ×{n}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        title="What this page does not measure"
        note="The block that decides whether a reader believes the rest."
        hint="A page that lists its own blind spots is the one a reader believes. Each entry names where the measurement does happen, so a gap is a pointer rather than an apology."
      >
        <ul className="blindspots">
          {data.not_measured.map((spot) => (
            <li key={spot.what}>
              <span className="blindspots__what">{spot.what}</span>
              <span className="blindspots__why">{spot.why}</span>
              <code className="blindspots__how">{spot.measured_by}</code>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

export function Evals() {
  const [state, setState] = useState<Async<EvalsResponse>>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    loadEvals()
      .then((data) => {
        if (live) setState({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (live) setState({ kind: "error", detail: failureDetail(error) });
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      {state.kind === "loading" && (
        <p className="note">
          Measuring. This route runs the retrieval over every gold case and re-resolves every stored
          citation, so it is the slowest one this service serves.
        </p>
      )}
      {/* No numbers, and a sentence saying so. A zero here would read as a
          measurement — which is the one thing this page must never do, since a
          measurement of zero is exactly what several of these figures could
          legitimately be. */}
      {state.kind === "error" && (
        <p className="error">
          Nothing on this page could be measured: {state.detail} No figures are shown, because a
          zero here would read as a measurement rather than as an absent one.
        </p>
      )}
      {state.kind === "ready" && (
        <>
          <Section title="Measured on request">
            <p className="note">
              <SourceBadge source={state.data.source} /> · measured at {state.data.measured_at}
            </p>
            <p className="note">
              {state.data.corpus.holdings} holdings · {state.data.corpus.documents} documents ·{" "}
              {state.data.corpus.claims} claims · {state.data.corpus.facts} cited figures ·{" "}
              {state.data.corpus.packet_periods} measurement dates. Every number below was computed
              when this page was requested; none is transcribed from a previous run.
            </p>
          </Section>
          <Measured data={state.data} />
        </>
      )}
    </>
  );
}
