import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The page's job is to distinguish a working chain from a broken one. So each
 * test drives it into a different failure and asserts the screen says something
 * different — a page that renders identically whether or not the request
 * succeeded would prove nothing about the deploy.
 *
 * `API` is read at module scope, so every case re-imports after stubbing env.
 */

async function mount(apiBase: string) {
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  vi.resetModules();
  const { App } = await import("./App");
  render(<App />);
}

beforeEach(() => {
  vi.unstubAllEnvs();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("App", () => {
  it("says so when no API base is configured, instead of calling a relative path", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await mount("");
    expect(screen.getByText(/is not set/)).toBeDefined();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("renders the health body verbatim rather than a green tick", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        json: async () => ({ status: "ok", public_tables: 23 }),
      })),
    );
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText(/"public_tables": 23/)).toBeDefined();
    });
  });

  it("surfaces a failed request instead of leaving the page blank", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("NetworkError");
      }),
    );
    await mount("https://api.example.com");
    await waitFor(() => {
      expect(screen.getByText(/Request failed: NetworkError/)).toBeDefined();
    });
  });

  it("shows the cold-start warning while the request is in flight", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    await mount("https://api.example.com");
    expect(screen.getByText(/takes about 50 seconds to wake/)).toBeDefined();
  });
});
