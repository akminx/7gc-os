import { useEffect, useState } from "react";

import type { RequirementCode } from "./contracts";
import { explainRow, findPassages } from "./data";
import { REQUIREMENT, SOURCE_CLASS } from "./labels";
import type { ExplainResponse, PassagesResponse } from "./responses";

/**
 * Two windows beside the record, not a chat box.
 *
 * A conversation has no anchor: every answer floats free of a row, so where a
 * figure came from has to be re-established in prose each time, and prose is
 * where a wrong figure gets in. These windows belong to a SELECTION — this
 * holding, this date, this requirement — so they inherit their provenance from
 * it. The row is the citation.
 *
 * ── The two are not the same kind of thing ───────────────────────────────
 *
 * **Ask the documents** runs no model at all. The question goes to Postgres
 * full-text search, the source's own reliance window narrows the candidates in
 * SQL, and what comes back is a verbatim slice of the stored document with its
 * page and offsets. It cannot state a wrong figure because it does not state
 * anything — it quotes.
 *
 * **In plain English** does run a model, and everything it writes is checked
 * before it is rendered: every figure in it must already appear in the row, and
 * no verdict word but this row's own. Rejected, the paragraph simply is not
 * there and the record beneath is unchanged. The window can add a sentence or
 * add nothing; it can never contradict the finding.
 *
 * That asymmetry is why the refusal is rendered rather than hidden. A reader
 * who sees "this was not accepted, because it stated a figure the record does
 * not contain" learns something true about the system. A reader shown a blank
 * box learns that the feature is broken.
 */

const REQUIREMENTS: RequirementCode[] = ["R1", "R2", "R3", "R4", "R5"];

/** What the reader typed, and what they have actually asked for.
 *
 * `submitted: null` is "they have not asked yet", which is different from
 * asking with an empty box — that runs the request's default terms. Both panes
 * stay inert until asked, so selecting a company costs nothing: the plain
 * English pane would otherwise spend a model call on every click through a
 * portfolio, and the reader who wanted none of them pays for all of them. */
type Asked = { text: string; submitted: string | null };

type Loading<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "failed"; detail: string };

function detailOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Ask the documents a question and read what they say.
 *
 * The input is free text on purpose. This is the half of a chat box that is
 * safe here — the reader types whatever they like, and the ANSWER is passages
 * rather than sentences, so there is nothing for a model to get wrong.
 */
export function AskDocuments({
  holdingId,
  measurementDate,
  requirement,
}: {
  holdingId: string;
  measurementDate: string;
  requirement: RequirementCode;
}) {
  const [asked, setAsked] = useState<Asked>({ text: "", submitted: null });
  const [state, setState] = useState<Loading<PassagesResponse>>({ kind: "idle" });
  const question = asked.submitted;

  useEffect(() => {
    if (question === null) return;
    let live = true;
    setState({ kind: "loading" });
    findPassages(holdingId, measurementDate, requirement, question)
      .then((data) => live && setState({ kind: "ready", data }))
      .catch((error: unknown) => live && setState({ kind: "failed", detail: detailOf(error) }));
    return () => {
      live = false;
    };
  }, [holdingId, measurementDate, requirement, question]);

  return (
    <div className="assist assist--ask">
      <form
        className="assist__form"
        onSubmit={(event) => {
          event.preventDefault();
          setAsked((a) => ({ ...a, submitted: a.text }));
        }}
      >
        <label className="assist__label" htmlFor="assist-question">
          Ask the documents
        </label>
        <div className="assist__row">
          <input
            id="assist-question"
            className="assist__input"
            type="text"
            placeholder="what currency is this denominated in?"
            value={asked.text}
            onChange={(event) => setAsked((a) => ({ ...a, text: event.target.value }))}
          />
          <button className="assist__go" type="submit">
            Search
          </button>
        </div>
      </form>

      {state.kind === "idle" && (
        <p className="assist__note">
          Ask anything about this company's paperwork. The answer is the documents' own words —
          quoted, with the page — and no language model writes any part of it. Leave the box empty
          to search the terms this request usually turns on.
        </p>
      )}

      {state.kind === "loading" && <p className="assist__note">Searching the documents…</p>}

      {state.kind === "failed" && (
        <p className="assist__note assist__note--failed">
          The search did not run: {state.detail}. This is a failed request, not a finding that the
          documents say nothing.
        </p>
      )}

      {state.kind === "ready" && (
        <>
          <p className="assist__note">
            {state.data.query.supplied ? (
              <>Searched for your words. </>
            ) : (
              <>
                Nothing was typed, so this searched the terms this request usually turns on:{" "}
                <em>{state.data.query.text}</em>.{" "}
              </>
            )}
            Passages are the documents' own words, quoted, with the page they sit on.
          </p>

          {state.data.outcome === "none_matched" ? (
            <p className="assist__note assist__note--empty">
              Nothing in this company's documents matches that, for this date. Documents whose own
              stated reliance period does not cover this date are left out of the search, so a
              document you know exists may be excluded rather than missing.
            </p>
          ) : (
            <ol className="assist__hits">
              {state.data.passages.map((passage) => (
                <li className="assist__hit" key={`${passage.claim_id}-${passage.span_start}`}>
                  <blockquote className="verbatim">{passage.quote}</blockquote>
                  <p className="assist__cite">
                    <span className="assist__file">{passage.filename}</span>
                    <span className="assist__page">page {passage.page}</span>
                    <span className="assist__class">{SOURCE_CLASS[passage.source_class]}</span>
                  </p>
                  {passage.matched.length > 0 && (
                    <p className="assist__matched">matched on {passage.matched.join(", ")}</p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </div>
  );
}

/**
 * The row, restated for a reader who does not know the vocabulary.
 *
 * Loads on selection rather than on a button, because it is a caption for what
 * is already on screen rather than an action the reader takes. A refusal is a
 * normal outcome and is shown as one.
 */
export function InPlainEnglish({
  holdingId,
  measurementDate,
  requirement,
}: {
  holdingId: string;
  measurementDate: string;
  requirement: RequirementCode;
}) {
  const [state, setState] = useState<Loading<ExplainResponse>>({ kind: "idle" });

  //: WHICH selection was asked about, not whether one was.
  //:
  //: A boolean plus an effect that reset it on change looked equivalent and
  //: raced: both effects run in the same commit, so the fetch still saw the old
  //: `true` and fired against the NEW requirement before the reset landed —
  //: leaving a paragraph loading for a row nobody asked about. Keyed to the
  //: selection there is nothing to reset and nothing to race: a request that is
  //: not for what is on screen simply does not match.
  const key = `${holdingId}|${measurementDate}|${requirement}`;
  const [wantedFor, setWantedFor] = useState<string | null>(null);
  const wanted = wantedFor === key;

  useEffect(() => {
    if (!wanted) return;
    let live = true;
    setState({ kind: "loading" });
    explainRow(holdingId, measurementDate, requirement)
      .then((data) => live && setState({ kind: "ready", data }))
      .catch((error: unknown) => live && setState({ kind: "failed", detail: detailOf(error) }));
    return () => {
      live = false;
    };
  }, [wanted, holdingId, measurementDate, requirement]);

  //: Anything held from a previous selection is not this row's answer, so it is
  //: not this row's pane. Derived rather than cleared, which is what keeps the
  //: stale paragraph from being rendered for even one frame.
  const showing: Loading<ExplainResponse> = wanted ? state : { kind: "idle" };

  return (
    <div className="assist assist--plain">
      <p className="assist__label">In plain English</p>

      {showing.kind === "idle" && (
        <>
          <p className="assist__note">
            The finding above, written out for a reader who does not know the vocabulary. A language
            model writes it from the record and never from anything else, and what it writes is
            checked before you see it.
          </p>
          <button className="assist__go" type="button" onClick={() => setWantedFor(key)}>
            Write it out
          </button>
        </>
      )}

      {showing.kind === "loading" && <p className="assist__note">Writing it out…</p>}

      {showing.kind === "failed" && (
        <p className="assist__note assist__note--failed">
          The restatement did not run: {showing.detail}.
        </p>
      )}

      {showing.kind === "ready" && showing.data.outcome === "explained" && (
        <>
          <p className="assist__prose">{showing.data.text}</p>
          {/* Stated, not implied. Every figure in the paragraph above was
              checked against the record before it was shown, and a reader is
              entitled to know that a machine wrote it and what was checked. */}
          <p className="assist__provenance">
            Written from the record above by {showing.data.model}, then checked: every figure in it
            appears in the record, and the finding it names is the one the record reaches. It adds
            no fact of its own.
          </p>
        </>
      )}

      {showing.kind === "ready" && showing.data.outcome === "refused" && (
        <p className="assist__note assist__note--refused">
          No plain-English version is shown here, because the one written did not pass its check:{" "}
          {showing.data.refusal} The record above is complete and unaffected.
        </p>
      )}
    </div>
  );
}

/**
 * Both windows, with the requirement they are both about.
 *
 * One picker for the pair rather than one each: they are two views of the same
 * selection, and letting them disagree about which request is open would put a
 * restatement of ¶1 beside passages retrieved for ¶2.
 */
export function AssistStrip({
  holdingId,
  measurementDate,
}: {
  holdingId: string;
  measurementDate: string;
}) {
  const [requirement, setRequirement] = useState<RequirementCode>("R2");
  return (
    <div className="assist__strip">
      <div className="assist__picker">
        {REQUIREMENTS.map((code) => (
          <button
            key={code}
            type="button"
            className={`assist__tab${code === requirement ? " assist__tab--on" : ""}`}
            title={REQUIREMENT[code].meaning}
            onClick={() => setRequirement(code)}
          >
            {REQUIREMENT[code].label}
          </button>
        ))}
      </div>
      <div className="assist__panes">
        <AskDocuments
          holdingId={holdingId}
          measurementDate={measurementDate}
          requirement={requirement}
        />
        <InPlainEnglish
          holdingId={holdingId}
          measurementDate={measurementDate}
          requirement={requirement}
        />
      </div>
    </div>
  );
}
