import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectList } from "../src/features/projects/ProjectList";
import type { Project } from "../src/api";
import { renderWithProviders } from "./renderWithProviders";

function makeProject(overrides: Partial<Project> & { id: number; slug: string; name: string }): Project {
  return {
    kind: "library",
    git_remote: null,
    local_path: "/tmp/p",
    deploy_port: null,
    autonomy_mode: "safe",
    created_at: "2026-04-20T00:00:00Z",
    updated_at: "2026-04-20T00:00:00Z",
    ...overrides,
  };
}

function mockFetchJson(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

describe("ProjectList", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetchJson([]));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders empty state", async () => {
    vi.stubGlobal("fetch", mockFetchJson([]));
    renderWithProviders(<ProjectList />);
    await waitFor(() => {
      expect(screen.getByText("No projects yet")).toBeTruthy();
    });
  });

  it("renders two project cards", async () => {
    const projects: Project[] = [
      makeProject({ id: 1, slug: "alpha", name: "Alpha" }),
      makeProject({ id: 2, slug: "beta", name: "Beta", kind: "script" }),
    ];
    vi.stubGlobal("fetch", mockFetchJson(projects));
    renderWithProviders(<ProjectList />);
    await waitFor(() => {
      expect(screen.getByText("Alpha")).toBeTruthy();
      expect(screen.getByText("Beta")).toBeTruthy();
    });
  });
});
