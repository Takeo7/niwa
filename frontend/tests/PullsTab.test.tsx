import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PullsTab } from "../src/features/projects/PullsTab";
import type { PullRead } from "../src/features/projects/api";
import { renderWithProviders } from "./renderWithProviders";

// PullsTab fires a single fetch against
// `/api/projects/<slug>/pulls?...`. We stub the global fetch by URL
// suffix so the table-render and error-state assertions don't depend
// on any other in-flight query in the page.
function makePull(overrides: Partial<PullRead> & { number: number }): PullRead {
  return {
    title: "feat: do the thing",
    state: "OPEN",
    url: `https://github.com/example/repo/pull/${overrides.number}`,
    mergeable: "MERGEABLE",
    checks: { state: "passing" },
    head_ref_name: `feat/branch-${overrides.number}`,
    created_at: "2026-04-20T12:00:00Z",
    updated_at: "2026-04-20T12:00:00Z",
    ...overrides,
  };
}

describe("PullsTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the table with one row per pull and check icons", async () => {
    const pulls: PullRead[] = [
      makePull({ number: 1, title: "feat: passing pr" }),
      makePull({
        number: 2,
        title: "fix: failing pr",
        checks: { state: "failing" },
        mergeable: "CONFLICTING",
      }),
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/projects/demo/pulls")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ pulls }),
          } as Response;
        }
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }),
    );

    renderWithProviders(<PullsTab projectSlug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText("feat: passing pr")).toBeTruthy();
    });
    expect(screen.getByText("fix: failing pr")).toBeTruthy();
    // Two open-in-github links rendered, one per pull.
    const links = screen.getAllByRole("link", { name: /Open/i });
    expect(links.length).toBe(2);
    // Each row renders a check icon with an aria-label encoding its state.
    expect(screen.getByLabelText(/All checks passing/i)).toBeTruthy();
    expect(screen.getByLabelText(/Checks failing/i)).toBeTruthy();
  });

  it("shows the GitHub CLI install message when the API returns 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/projects/demo/pulls")) {
          return {
            ok: false,
            status: 503,
            json: async () => ({ error: "gh_missing" }),
          } as Response;
        }
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }),
    );

    renderWithProviders(<PullsTab projectSlug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText(/Install the GitHub CLI/i)).toBeTruthy();
    });
    expect(screen.getByText(/brew install gh/i)).toBeTruthy();
  });
});
