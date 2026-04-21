import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectDetail } from "../src/features/projects/ProjectDetail";
import type { Project } from "../src/api";
import { renderWithProviders } from "./renderWithProviders";

// ProjectDetail fires two React Query fetches under the hood: the project
// (`/api/projects/<slug>`) and the task list (`/api/projects/<slug>/tasks`).
// We stub fetch by URL suffix so the banner assertions don't depend on the
// task list hook completing in a specific order.
function stubFetch(project: Project): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      const body = url.endsWith(`/projects/${project.slug}`) ? project : [];
      return {
        ok: true,
        status: 200,
        json: async () => body,
      } as Response;
    }),
  );
}

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 1,
    slug: "demo",
    name: "Demo",
    kind: "library",
    git_remote: null,
    local_path: "/tmp/demo",
    deploy_port: null,
    autonomy_mode: "safe",
    created_at: "2026-04-20T00:00:00Z",
    updated_at: "2026-04-20T00:00:00Z",
    ...overrides,
  };
}

describe("ProjectDetail dangerous-mode banner", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the red alert when autonomy_mode is dangerous", async () => {
    stubFetch(makeProject({ autonomy_mode: "dangerous" }));
    renderWithProviders(<ProjectDetail slug="demo" />);

    await waitFor(() => {
      expect(screen.getByText("Demo")).toBeTruthy();
    });
    // The banner title and body both land in the DOM; check both so a
    // stray badge swap can't pass this test.
    expect(screen.getByText(/Dangerous mode/i)).toBeTruthy();
    expect(
      screen.getByText(/Runs auto-merge PRs without review/i),
    ).toBeTruthy();
  });

  it("omits the banner when autonomy_mode is safe", async () => {
    stubFetch(makeProject({ autonomy_mode: "safe" }));
    renderWithProviders(<ProjectDetail slug="demo" />);

    await waitFor(() => {
      expect(screen.getByText("Demo")).toBeTruthy();
    });
    expect(
      screen.queryByText(/Runs auto-merge PRs without review/i),
    ).toBeNull();
  });
});
