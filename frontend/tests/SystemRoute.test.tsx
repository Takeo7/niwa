import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SystemRoute } from "../src/routes/SystemRoute";
import type { ReadinessResponse } from "../src/api";
import { renderWithProviders } from "./renderWithProviders";

function mockFetchJson(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

function allOk(): ReadinessResponse {
  return {
    db_ok: true,
    claude_cli_ok: true,
    git_ok: true,
    gh_ok: true,
    details: {
      db: { path: "/tmp/niwa.sqlite3", reachable: true },
      claude_cli: { path: "/usr/local/bin/claude", found: true },
      git: { version: "git version 2.43.0" },
      gh: { found: true },
    },
  };
}

describe("SystemRoute", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetchJson(allOk()));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders all four checks with OK badges", async () => {
    renderWithProviders(<SystemRoute />);

    await waitFor(() => {
      expect(screen.getByText(/database/i)).toBeTruthy();
      expect(screen.getByText(/claude cli/i)).toBeTruthy();
      expect(screen.getByText(/^git$/i)).toBeTruthy();
      expect(screen.getByText(/^gh$/i)).toBeTruthy();
    });

    const okBadges = await screen.findAllByText(/^OK$/);
    expect(okBadges.length).toBeGreaterThanOrEqual(4);
  });

  it("renders missing gh with hint text", async () => {
    const body: ReadinessResponse = {
      ...allOk(),
      gh_ok: false,
      details: {
        ...allOk().details,
        gh: { found: false, hint: "install from github.com/cli/cli" },
      },
    };
    vi.stubGlobal("fetch", mockFetchJson(body));

    renderWithProviders(<SystemRoute />);

    await waitFor(() => {
      expect(screen.getByText(/missing/i)).toBeTruthy();
      expect(screen.getByText(/github\.com\/cli\/cli/i)).toBeTruthy();
    });
  });
});
