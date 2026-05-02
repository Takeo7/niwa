import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectDetail } from "../src/features/projects/ProjectDetail";
import type { Deployment, Project } from "../src/api";
import { renderWithProviders } from "./renderWithProviders";

// ProjectDetail fires two React Query fetches under the hood: the project
// (`/api/projects/<slug>`) and the task list (`/api/projects/<slug>/tasks`).
// We stub fetch by URL suffix so the banner assertions don't depend on the
// task list hook completing in a specific order.
function stubFetch(
  project: Project,
  onPatch?: ReturnType<typeof vi.fn>,
  deployments: Deployment[] = [],
  onHealthcheck?: ReturnType<typeof vi.fn>,
): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith(`/projects/${project.slug}`) && init?.method === "PATCH") {
        onPatch?.(init);
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...project, ...JSON.parse(init.body as string) }),
        } as Response;
      }
      if (url.endsWith(`/projects/${project.slug}/deployments`)) {
        return { ok: true, status: 200, json: async () => deployments } as Response;
      }
      if (url.match(/\/deployments\/\d+\/healthcheck$/)) {
        onHealthcheck?.(init);
        return { ok: true, status: 200, json: async () => deployments[0] } as Response;
      }
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
    deploy_type: "static",
    build_command: null,
    dist_dir: null,
    start_command: null,
    healthcheck_path: null,
    deploy_trigger: "manual",
    public_enabled: false,
    plan_approval_mode: "auto",
    max_review_iterations: 1,
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

  it("saves project deployment settings from the settings tab", async () => {
    const patched = vi.fn();
    stubFetch(makeProject(), patched);
    renderWithProviders(<ProjectDetail slug="demo" />);

    await waitFor(() => {
      expect(screen.getByText("Demo")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("tab", { name: /Settings/i }));
    fireEvent.click(screen.getByLabelText(/Public deployment/i));
    fireEvent.click(screen.getByRole("button", { name: /Save settings/i }));

    await waitFor(() => {
      expect(patched).toHaveBeenCalledTimes(1);
    });
    const init = patched.mock.calls[0][0] as RequestInit;
    expect(JSON.parse(init.body as string).public_enabled).toBe(true);
  });

  it("shows process deployment log path and healthcheck action", async () => {
    const healthcheck = vi.fn();
    const deployment: Deployment = {
      id: 5,
      project_id: 1,
      task_id: 42,
      commit_sha: "abc123",
      deploy_type: "process",
      status: "healthy",
      artifact_path: "/tmp/artifact",
      port: 8712,
      url_local: "http://127.0.0.1:8712",
      healthcheck_path: "/health",
      build_log: null,
      error: null,
      pid: 1234,
      started_at: null,
      finished_at: null,
      last_health_check: null,
      created_at: "2026-04-20T00:00:00Z",
    };
    stubFetch(makeProject(), undefined, [deployment], healthcheck);
    renderWithProviders(<ProjectDetail slug="demo" />);

    await waitFor(() => {
      expect(screen.getByText("Demo")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("tab", { name: /Deploys/i }));

    expect(await screen.findByText("~/.niwa/deployments/demo/5/process.log"))
      .toBeTruthy();
    expect(screen.getByText("pid 1234")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Healthcheck/i }));
    await waitFor(() => expect(healthcheck).toHaveBeenCalledTimes(1));
  });
});
