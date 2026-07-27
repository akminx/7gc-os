import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apply, ThemeChoiceControl } from "./Theme";

/**
 * An in-memory store. This jsdom build ships no working `localStorage`, which
 * is also the state the control has to survive in a browser that refuses
 * storage — so the stub is the dependency, and the component's own try/catch is
 * what makes the page work without it.
 */
const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  });
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the theme choice", () => {
  /**
   * Three states, not two. A toggle cannot express "whatever this machine
   * says", so the moment it is touched it silently pins the page to one theme
   * and the system preference is gone.
   */
  it("offers system as a state of its own, and starts there", () => {
    render(<ThemeChoiceControl />);
    expect(screen.getByRole("button", { name: "system" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("pins the page to a chosen theme and releases it again", async () => {
    render(<ThemeChoiceControl />);
    screen.getByRole("button", { name: "dark" }).click();
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    });
    screen.getByRole("button", { name: "light" }).click();
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    });
    // Back to system means the attribute is REMOVED, not set to "system":
    // `prefers-color-scheme` has to be the thing that answers again.
    screen.getByRole("button", { name: "system" }).click();
    await waitFor(() => {
      expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    });
  });

  it("remembers the choice across a remount", async () => {
    const first = render(<ThemeChoiceControl />);
    screen.getByRole("button", { name: "dark" }).click();
    await waitFor(() => {
      expect(store.get("7gc-theme")).toBe("dark");
    });
    first.unmount();
    render(<ThemeChoiceControl />);
    expect(screen.getByRole("button", { name: "dark" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("applies a theme without a control mounted", () => {
    apply("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    apply("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });
});
