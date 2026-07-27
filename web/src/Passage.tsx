import { useEffect, useRef, useState } from "react";

import type { Citation } from "./contracts";
import type { Async } from "./data";
import { failureDetail, loadDocument } from "./data";
import type { DocumentResponse } from "./responses";

/**
 * The passage pane. The screen this whole application is an argument for.
 *
 * Every other surface says a figure is supported. This one shows the page it is
 * supported by: the stored canonical text of the document version, with
 * `[span_start, span_end)` highlighted inside it, under the filename it was
 * extracted from and beside the offsets an auditor uses to find it again by
 * hand. `0008_citations_resolve.sql` enforces that
 * `substring(canonical_text, span) = quote`; this is that constraint, rendered.
 *
 * Three decisions here are not stylistic:
 *
 * 1. **A focus window, with the whole document one click away.** This pane used
 *    to render the entire document around the highlight, on the argument that a
 *    pane deciding how much context to show is deciding what an auditor may read
 *    — and "the surrounding paragraph contradicts it" is exactly the finding
 *    this product exists to make findable. That argument is right about
 *    DELETING context and wrong about defaulting to all of it. The citations are
 *    tight (237 of them, median 62 characters, longest 191) and the documents
 *    are not (median 2,049 characters, longest 4,015): Fluidstack's cap table is
 *    3,730 characters of columnar `pdftotext` output, and one highlighted line
 *    inside it is visually indistinguishable from the rest, scrolled to or not.
 *    The auditor asked to be shown the support and got a page to search. So the
 *    window is the default and the full text is a button, which deletes nothing.
 *
 *    Scoped to WHOLE LINES, not to a character count. A cap table's unit of
 *    meaning is the row — `7GC Fund II, L.P. … Series A-2 … 100,000 … $15.00` —
 *    and ±300 characters cuts it mid-row, which is a worse misreading than
 *    showing too much. The window is the span's own lines plus two either side.
 * 2. **Monospace and `pre-wrap`.** The corpus is extracted text whose columns
 *    are held by spaces; a cap table reflowed into a proportional font is a
 *    different document. This is the exception the "monospace is a costume"
 *    rule names: it is code, data and measurement.
 * 3. **The span is checked, on screen.** If the slice at those offsets is not
 *    the stored quote, the pane says so instead of highlighting the wrong
 *    sentence. A citation that silently drifts one character is the failure
 *    mode with no other detector in the browser. The window does not touch this:
 *    the slice compared against the quote is still `text[span_start:span_end]`
 *    of the WHOLE stored text, so narrowing what is displayed cannot make a
 *    drifted citation resolve.
 *
 * No arithmetic anywhere below, which is a constraint rather than a style.
 * `scripts/check-web-arch.mjs` refuses `+` or `-` on a numeric field the API
 * owns, and `span_start` is one. The line window is therefore computed by
 * splitting the text either side of the span and slicing the resulting arrays
 * at fixed offsets — which needs no character maths at all, and says what it
 * means more directly than `lastIndexOf(…) + 1` did.
 */

const RESOLVE_NOTE =
  "An auditor re-verifies a citation by taking these offsets out of the stored canonical text and comparing the result to the quote. The database enforces the same equality; this pane checks it again where it can be seen.";

/** Where the highlight lands, in the reader's own units. */
export function OffsetLabel({ citation }: { citation: Citation }) {
  return (
    <span className="offsets" title={RESOLVE_NOTE}>
      chars {citation.span_start}–{citation.span_end}
    </span>
  );
}

/**
 * The passage with nothing around it.
 *
 * Used when the document text cannot be fetched — no API configured, or a
 * document version the ledger does not hold. The quote is still verbatim and the
 * offsets are still on screen, and the pane states which of the two it is
 * showing, because "here is the sentence in its document" and "here is the
 * sentence we stored" are different strengths of evidence.
 */
function QuoteOnly({ citation, reason }: { citation: Citation; reason: string }) {
  return (
    <div className="paper paper--quote-only">
      <p className="paper__degraded">{reason}</p>
      <p className="paper__body">
        <mark className="cited">{citation.quote}</mark>
      </p>
    </div>
  );
}

/**
 * The document, with the cited span marked in it.
 *
 * Sliced at the two offsets rather than searched for by text: the offsets are
 * the citation. Finding the quote by string match would silently succeed at the
 * wrong occurrence, and a document that states $40.00 twice is the ordinary
 * case rather than the exotic one.
 */
/**
 * Where the window is cut, in lines.
 *
 * Negative on the near side because `before` is split at the span: its LAST
 * element is the head of the span's own line, and the two before that are the
 * context. Same idea mirrored below the span. Array slicing, so no offset is
 * ever added to another and the §5.3 boundary is not touched.
 */
const LINES_ABOVE = -3;
const LINES_BELOW = 3;

function MarkedText({
  document: doc,
  citation,
}: {
  document: DocumentResponse;
  citation: Citation;
}) {
  const mark = useRef<HTMLElement>(null);
  const [whole, setWhole] = useState(false);

  const before = doc.text.slice(0, citation.span_start);
  const cited = doc.text.slice(citation.span_start, citation.span_end);
  const after = doc.text.slice(citation.span_end);
  // Compared against the WHOLE text's slice, before any windowing. Narrowing
  // what is displayed must not be able to change whether a citation resolves.
  const resolves = cited === citation.quote;

  const aboveLines = before.split("\n");
  const belowLines = after.split("\n");
  const hiddenAbove = aboveLines.slice(0, LINES_ABOVE);
  const hiddenBelow = belowLines.slice(LINES_BELOW);
  const windowed = hiddenAbove.length > 0 || hiddenBelow.length > 0;
  const showAll = whole || !windowed;

  // Mounted fresh for each citation — the caller keys this component on the
  // span — so the page opens at the top and travels to the highlight. That
  // travel is the one authored motion in the application, and it is the thing
  // being said: the sentence is HERE, this far into this document.
  //
  // Re-run on `whole`, because expanding to the full text puts the reader back
  // at the top of a 4,000-character page — without this the button that offers
  // the surrounding document loses the sentence it surrounds. And it lands
  // instantly rather than travelling: the arrival is the authored motion, and
  // repeating it on a control the reader just pressed is an animation they have
  // to wait through to get back to where they already were.
  useEffect(() => {
    mark.current?.scrollIntoView({ block: "center", behavior: whole ? "auto" : "smooth" });
  }, [whole]);

  return (
    <>
      {!resolves && (
        <p className="paper__unresolved">
          These offsets do not select the stored quote in this document version. The highlight below
          is what the offsets actually select. Re-run the extractor named above, or correct the
          citation; do not read the highlight as the cited passage.
        </p>
      )}
      {windowed && (
        <p className="paper__window">
          {showAll ? (
            <>
              <span>Showing the whole extracted document, {doc.text_length} characters.</span>{" "}
              <button
                type="button"
                className="paper__expand"
                onClick={() => {
                  setWhole(false);
                }}
              >
                Show just the cited lines
              </button>
            </>
          ) : (
            <>
              <span>
                Showing the cited lines and two either side. {hiddenAbove.length} line
                {hiddenAbove.length === 1 ? "" : "s"} above and {hiddenBelow.length} below are not
                on screen.
              </span>{" "}
              <button
                type="button"
                className="paper__expand"
                onClick={() => {
                  setWhole(true);
                }}
              >
                Show the whole document
              </button>
            </>
          )}
        </p>
      )}
      <div className={showAll ? "paper" : "paper paper--focused"}>
        <p className="paper__body">
          {showAll ? before : aboveLines.slice(LINES_ABOVE).join("\n")}
          <mark className={resolves ? "cited" : "cited cited--unresolved"} ref={mark}>
            {cited}
          </mark>
          {showAll ? after : belowLines.slice(0, LINES_BELOW).join("\n")}
        </p>
      </div>
    </>
  );
}

/**
 * The document behind one citation, fetched once per document version.
 *
 * The fetch is keyed on the document, not on the citation, because one
 * agreement states thirteen figures: moving between them re-highlights and
 * re-scrolls and must not re-request the page an auditor is reading.
 */
export function PassagePane({ citation, caption }: { citation: Citation; caption: string }) {
  const documentId = citation.document_version_id;
  const [doc, setDoc] = useState<Async<DocumentResponse>>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    setDoc({ kind: "loading" });
    loadDocument(documentId)
      .then((data) => {
        if (live) setDoc({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (live) setDoc({ kind: "error", detail: failureDetail(error) });
      });
    return () => {
      live = false;
    };
  }, [documentId]);

  const scrollKey = `${documentId}:${citation.span_start}:${citation.span_end}`;
  return (
    <section className="passage" aria-label="source passage">
      <header className="passage__head">
        <p className="passage__file">
          {doc.kind === "ready" ? doc.data.filename : documentId}
          <span className="passage__caption">{caption}</span>
        </p>
        <p className="passage__where">
          <code>{documentId}</code>
          <OffsetLabel citation={citation} />
          {doc.kind === "ready" && (
            <span
              className="passage__extractor"
              title="The tool that produced this text. Character offsets are only meaningful against the text it produced."
            >
              {doc.data.extractor} · {doc.data.text_length} chars
            </span>
          )}
        </p>
      </header>

      {doc.kind === "loading" && (
        <div className="paper paper--loading" aria-busy="true">
          <span className="skeleton skeleton--wide" />
          <span className="skeleton" />
          <span className="skeleton skeleton--short" />
        </div>
      )}
      {doc.kind === "error" && <QuoteOnly citation={citation} reason={doc.detail} />}
      {doc.kind === "ready" && (
        <MarkedText key={scrollKey} document={doc.data} citation={citation} />
      )}
    </section>
  );
}
