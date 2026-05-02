import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Deployment, Run, Task, TaskPlan, TaskReview } from "../src/api";
import { TaskDetail } from "../src/features/tasks/TaskDetail";
import { renderWithProviders } from "./renderWithProviders";

// TaskDetail fires two concurrent fetches: `/api/tasks/<id>` and
// `/api/tasks/<id>/runs`. Stub by URL suffix so the waiting_input
// assertions do not depend on the runs request completing first.
function stubFetchForTask(task: Task, respondCapture?: vi.Mock): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith(`/tasks/${task.id}/respond`) && init?.method === "POST") {
        respondCapture?.(url, init);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ...task,
            status: "queued",
            pending_question: null,
          }),
        } as Response;
      }
      if (url.endsWith(`/tasks/${task.id}/runs`)) {
        return { ok: true, status: 200, json: async () => [] } as Response;
      }
      if (url.endsWith(`/tasks/${task.id}/plan`) || url.endsWith(`/tasks/${task.id}/review`)) {
        return { ok: false, status: 404, json: async () => ({ detail: "not found" }) } as Response;
      }
      if (url.endsWith(`/tasks/${task.id}`)) {
        return { ok: true, status: 200, json: async () => task } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }),
  );
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 42,
    project_id: 1,
    parent_task_id: null,
    title: "t",
    description: null,
    status: "waiting_input",
    branch_name: null,
    pr_url: null,
    pending_question: "what should I do?",
    created_at: "2026-04-21T00:00:00Z",
    updated_at: "2026-04-21T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("TaskDetail waiting_input banner", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders banner with pending_question + disabled button when textarea empty", async () => {
    stubFetchForTask(makeTask());
    renderWithProviders(<TaskDetail taskId={42} />);

    await waitFor(() => {
      expect(screen.getByText(/Niwa necesita tu respuesta/i)).toBeTruthy();
    });
    expect(screen.getByText("what should I do?")).toBeTruthy();

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("");
    const button = screen.getByRole("button", { name: /Responder/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    // Non-empty input should enable the button.
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "do it" } });
    });
    expect((screen.getByRole("button", { name: /Responder/i }) as HTMLButtonElement).disabled)
      .toBe(false);
  });

  it("submits response via POST and triggers task query refetch", async () => {
    const captured = vi.fn();
    stubFetchForTask(makeTask(), captured);
    renderWithProviders(<TaskDetail taskId={42} />);

    await waitFor(() => {
      expect(screen.getByText(/Niwa necesita tu respuesta/i)).toBeTruthy();
    });

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "yes please" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Responder/i }));
    });

    await waitFor(() => {
      expect(captured).toHaveBeenCalledTimes(1);
    });
    const [, init] = captured.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ response: "yes please" });
  });

  it("shows operator plan, review, run, deployment details and approves plans", async () => {
    const task = makeTask({
      status: "waiting_approval",
      pending_question: null,
      title: "ship operator UI",
    });
    const plan: TaskPlan = {
      id: 1,
      task_id: task.id,
      status: "ready",
      summary: "Check the diff",
      steps: ["Inspect", "Approve"],
      risks: ["Regression"],
      planner: "fake-json",
      raw_json: "{}",
      created_at: "2026-04-21T00:01:00Z",
    };
    const review: TaskReview = {
      id: 2,
      task_id: task.id,
      run_id: 9,
      decision: "request_changes",
      iteration: 2,
      summary: "Needs one more pass",
      findings: ["Missing assertion"],
      reviewer: "fake-json",
      raw_json: "{}",
      created_at: "2026-04-21T00:03:00Z",
    };
    const run: Run = {
      id: 9,
      task_id: task.id,
      status: "completed",
      model: "claude-code",
      started_at: "2026-04-21T00:02:00Z",
      finished_at: "2026-04-21T00:03:00Z",
      exit_code: 0,
      pid: 123,
      outcome: "verified",
      session_handle: null,
      artifact_root: "/tmp/demo",
      verification_json: JSON.stringify({ passed: true }),
      created_at: "2026-04-21T00:02:00Z",
    };
    const deployment: Deployment = {
      id: 7,
      project_id: 1,
      task_id: task.id,
      commit_sha: "abc123",
      deploy_type: "static",
      status: "healthy",
      artifact_path: "/tmp/artifact",
      port: null,
      url_local: "http://127.0.0.1:9000",
      healthcheck_path: "/",
      build_log: null,
      error: null,
      pid: null,
      started_at: null,
      finished_at: null,
      last_health_check: null,
      created_at: "2026-04-21T00:04:00Z",
    };
    const approve = vi.fn();
    class NoopEventSource {
      onerror: (() => void) | null = null;
      addEventListener() {}
      close() {}
    }
    vi.stubGlobal("EventSource", NoopEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith(`/tasks/${task.id}/approve-plan`)) {
          approve(init);
          return { ok: true, status: 200, json: async () => ({ ...task, status: "queued" }) } as Response;
        }
        if (url.endsWith(`/tasks/${task.id}/runs`)) {
          return { ok: true, status: 200, json: async () => [run] } as Response;
        }
        if (url.endsWith(`/tasks/${task.id}/plan`)) {
          return { ok: true, status: 200, json: async () => plan } as Response;
        }
        if (url.endsWith(`/tasks/${task.id}/review`)) {
          return { ok: true, status: 200, json: async () => review } as Response;
        }
        if (url.endsWith(`/tasks/${task.id}/attachments`)) {
          return { ok: true, status: 200, json: async () => [] } as Response;
        }
        if (url.endsWith("/projects/demo/deployments")) {
          return { ok: true, status: 200, json: async () => [deployment] } as Response;
        }
        if (url.endsWith(`/tasks/${task.id}`)) {
          return { ok: true, status: 200, json: async () => task } as Response;
        }
        return { ok: true, status: 200, json: async () => ({}) } as Response;
      }),
    );

    renderWithProviders(<TaskDetail taskId={42} projectSlug="demo" />);

    expect(await screen.findByRole("button", { name: /Approve plan/i })).toBeTruthy();
    expect(screen.getByText("Timeline")).toBeTruthy();
    expect(screen.getByText("Latest run")).toBeTruthy();
    expect(screen.getByText("Task deployment")).toBeTruthy();
    expect(screen.getByText("request_changes")).toBeTruthy();
    expect(screen.getByText("http://127.0.0.1:9000")).toBeTruthy();
    expect(screen.getAllByText((_, el) => el?.textContent?.includes('"passed": true') ?? false)
      .length).toBeGreaterThan(0);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Approve plan/i }));
    });
    await waitFor(() => expect(approve).toHaveBeenCalledTimes(1));
  });
});
