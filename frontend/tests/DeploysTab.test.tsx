import { screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeploysTab } from "../src/features/deployments/DeploysTab";
import type { Deployment } from "../src/features/deployments/DeploysTab";
import { renderWithProviders } from "./renderWithProviders";

function makeDeployment(o: Partial<Deployment> & { id: number }): Deployment {
  return {
    project_id: 1,
    task_id: null,
    commit_sha: "abc1234",
    deploy_type: "static",
    status: "healthy",
    artifact_path: "/tmp/artifact",
    port: null,
    url_local: null,
    healthcheck_path: "/",
    build_log: null,
    error: null,
    pid: null,
    started_at: null,
    finished_at: null,
    last_health_check: null,
    created_at: "2026-04-20T12:00:00Z",
    ...o,
  };
}

describe("DeploysTab", () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it("shows 'No deployments yet' when list is empty", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, json: async () => [],
    } as Response)));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText(/No deployments yet/i)).toBeTruthy();
    });
  });

  it("renders a table row for each deployment", async () => {
    const deployments: Deployment[] = [
      makeDeployment({ id: 1, status: "healthy", commit_sha: "aaa1111" }),
      makeDeployment({ id: 2, status: "stopped", commit_sha: "bbb2222" }),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/deployments")) {
        return { ok: true, status: 200, json: async () => deployments } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText("aaa1111")).toBeTruthy();
    });
    expect(screen.getByText("bbb2222")).toBeTruthy();
  });

  it("shows Stop button only for healthy deployments", async () => {
    const deployments: Deployment[] = [
      makeDeployment({ id: 1, status: "healthy" }),
      makeDeployment({ id: 2, status: "stopped" }),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/deployments")) {
        return { ok: true, status: 200, json: async () => deployments } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getAllByText("abc1234").length).toBe(2);
    });

    const stopButtons = screen.getAllByRole("button", { name: /Stop/i });
    expect(stopButtons.length).toBe(1);
  });

  it("shows Rollback button for stopped deployments with artifact_path", async () => {
    const deployments: Deployment[] = [
      makeDeployment({ id: 1, status: "stopped", artifact_path: "/tmp/art" }),
      makeDeployment({ id: 2, status: "healthy", artifact_path: null }),
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/deployments")) {
        return { ok: true, status: 200, json: async () => deployments } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Rollback/i })).toBeTruthy();
    });
    const rollbackButtons = screen.getAllByRole("button", { name: /Rollback/i });
    expect(rollbackButtons.length).toBe(1);
  });

  it("shows a clickable URL link when url_local is set", async () => {
    const deployments: Deployment[] = [
      makeDeployment({ id: 1, status: "healthy", url_local: "http://localhost:41001" }),
    ];
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, json: async () => deployments,
    } as Response)));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText("http://localhost:41001")).toBeTruthy();
    });
    const link = screen.getByRole("link", { name: /localhost/ });
    expect(link).toBeTruthy();
  });

  it("shows error indicator for failed deployments with errors", async () => {
    const deployments: Deployment[] = [
      makeDeployment({ id: 1, status: "failed", error: "Build failed: exit 1" }),
    ];
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true, status: 200, json: async () => deployments,
    } as Response)));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getByText("⚠")).toBeTruthy();
    });
  });

  it("renders the Deploy button and fires a POST on click", async () => {
    let postCalled = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/deployments") && init?.method === "POST") {
        postCalled = true;
        return {
          ok: true, status: 201,
          json: async () => makeDeployment({ id: 10, status: "queued" }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => [] } as Response;
    }));

    renderWithProviders(<DeploysTab slug="demo" active />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Deploy/i })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: /Deploy/i }));

    await waitFor(() => {
      expect(postCalled).toBe(true);
    });
  });
});
