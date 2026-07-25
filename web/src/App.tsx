import { useEffect, useState } from "react";

/**
 * Step 0's frontend exists to prove one thing: the chain from this page to
 * FastAPI on Render to Postgres on Supabase is real. So it renders the health
 * response verbatim rather than a green tick — a tick can be drawn without the
 * request ever succeeding, which is the failure this page is here to rule out.
 */

const API = import.meta.env.VITE_API_BASE_URL ?? "";

type State =
  | { kind: "unconfigured" }
  | { kind: "loading" }
  | { kind: "ok"; body: unknown }
  | { kind: "error"; detail: string };

export function App() {
  const [state, setState] = useState<State>(API ? { kind: "loading" } : { kind: "unconfigured" });

  useEffect(() => {
    if (!API) return;
    let live = true;
    fetch(`${API}/health`)
      .then(async (r) => {
        const body: unknown = await r.json();
        if (live) setState({ kind: "ok", body });
      })
      .catch((e: unknown) => {
        if (live) setState({ kind: "error", detail: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <main
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        maxWidth: "44rem",
        margin: "4rem auto",
        padding: "0 1.5rem",
        lineHeight: 1.6,
      }}
    >
      <h1 style={{ fontSize: "1.25rem", marginBottom: "0.25rem" }}>
        7GC OS — Valuation Evidence Ledger
      </h1>
      <p style={{ opacity: 0.65, marginTop: 0 }}>Step 0 — deploy path verification</p>

      <h2 style={{ fontSize: "0.9rem", marginTop: "2rem" }}>API health</h2>
      {state.kind === "unconfigured" && (
        <p>
          <code>VITE_API_BASE_URL</code> is not set, so this page has no service to call.
        </p>
      )}
      {state.kind === "loading" && (
        <p>
          Calling <code>{API}/health</code>… a free Render instance sleeps after 15 minutes idle and
          takes about 50 seconds to wake.
        </p>
      )}
      {state.kind === "error" && <p>Request failed: {state.detail}</p>}
      {state.kind === "ok" && (
        <pre
          style={{
            background: "rgba(127,127,127,0.12)",
            padding: "1rem",
            borderRadius: "6px",
            overflowX: "auto",
          }}
        >
          {JSON.stringify(state.body, null, 2)}
        </pre>
      )}
    </main>
  );
}
