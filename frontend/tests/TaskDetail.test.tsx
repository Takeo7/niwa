import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Task } from "../src/api";
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
});
