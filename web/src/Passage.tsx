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
 * 1. **The whole document, not a window around the quote.** A pane that decided
 *    how much context to show would be deciding what an auditor may read next to
 *    the sentence — and "the surrounding paragraph contradicts it" is exactly
 *    the finding this product exists to make findable.
 * 2. **Monospace and `pre-wrap`.** The corpus is extracted text whose columns
 *    are held by spaces; a cap table reflowed into a proportional font is a
 *    different document. This is the exception the "monospace is a costume"
 *    rule names: it is code, data and measurement.
 * 3. **The span is checked, on screen.** If the slice at those offsets is not
 *    the stored quote, the pane says so instead of highlighting the wrong
 *    sentence. A citation that silently drifts one character is the failure
 *    mode with no other detector in the browser.
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
function MarkedText({
  document: doc,
  citation,
}: {
  document: DocumentResponse;
  citation: Citation;
}) {
  const mark = useRef<HTMLElement>(null);

  // Mounted fresh for each citation — the caller keys this component on the
  // span — so the page opens at the top and travels to the highlight. That
  // travel is the one authored motion in the application, and it is the thing
  // being said: the sentence is HERE, this far into this document.
  useEffect(() => {
    mark.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, []);

  const before = doc.text.slice(0, citation.span_start);
  const cited = doc.text.slice(citation.span_start, citation.span_end);
  const after = doc.text.slice(citation.span_end);
  const resolves = cited === citation.quote;

  return (
    <>
      {!resolves && (
        <p className="paper__unresolved">
          These offsets do not select the stored quote in this document version. The highlight below
          is what the offsets actually select. Re-run the extractor named above, or correct the
          citation; do not read the highlight as the cited passage.
        </p>
      )}
      <div className="paper">
        <p className="paper__body">
          {before}
          <mark className={resolves ? "cited" : "cited cited--unresolved"} ref={mark}>
            {cited}
          </mark>
          {after}
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
