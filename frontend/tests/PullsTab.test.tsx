import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PullsTab } from "../src/features/projects/PullsTab";
import type { PullRead } from "../src/features/projects/api";
import { renderWithProviders } from "./renderWithProviders";

// Stub global fetch for the single endpoint PullsTab hits
// (`/api/projects/<slug>/pulls?...`). Other URLs short-circuit so a
// future shared query in the page can't poison these assertions.
function makePull(o: Partial<PullRead> & { number: number }): PullRead {
  return {
    title: "feat: do the thing",
    state: "OPEN",
    url: `https://github.com/example/repo/pull/${o.number}`,
    mergeable: "MERGEABLE",
    checks: { state: "passing" },
    head_ref_name: `feat/branch-${o.number}`,
    created_at: "2026-04-20T12:00:00Z",
    updated_at: "2026-04-20T12:00:00Z",
    ...o,
  };
}

describe("PullsTab", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("renders the table with one row per pull and check icons", async () => {
    const pulls: PullRead[] = [
      makePull({ number: 1, title: "feat: passing pr" }),
      makePull({
        number: 2, title: "fix: failing pr",
        checks: { state: "failing" }, mergeable: "CONFLICTING",
      }),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/projects/demo/pulls")) {
        return { ok: true, status: 200, json: async () => ({ pulls }) } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }));

    renderWithProviders(<PullsTab projectSlug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText("feat: passing pr")).toBeTruthy();
    });
    expect(screen.getByText("fix: failing pr")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Open/i }).length).toBe(2);
    // Check icons are rendered with an aria-label that encodes their state.
    expect(screen.getByLabelText(/All checks passing/i)).toBeTruthy();
    expect(screen.getByLabelText(/Checks failing/i)).toBeTruthy();
  });

  it("only shows merge button on mergeable rows", async () => {
    const pulls: PullRead[] = [
      makePull({ number: 1, title: "feat: ok", mergeable: "MERGEABLE" }),
      makePull({ number: 2, title: "fix: conflict", mergeable: "CONFLICTING" }),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/projects/demo/pulls")) {
        return { ok: true, status: 200, json: async () => ({ pulls }) } as Response;
      }
      if (url.includes("/projects/demo")) {
        return {
          ok: true, status: 200,
          json: async () => ({ slug: "demo", autonomy_mode: "safe" }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }));

    renderWithProviders(<PullsTab projectSlug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText("feat: ok")).toBeTruthy();
    });
    const mergeButtons = screen.getAllByRole("button", { name: /Merge/i });
    expect(mergeButtons.length).toBe(1);
  });

  it("shows the GitHub CLI install message when the API returns 503", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/projects/demo/pulls")) {
        return {
          ok: false, status: 503,
          json: async () => ({ error: "gh_missing" }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }));

    renderWithProviders(<PullsTab projectSlug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText(/Install the GitHub CLI/i)).toBeTruthy();
    });
    expect(screen.getByText(/brew install gh/i)).toBeTruthy();
  });
});
