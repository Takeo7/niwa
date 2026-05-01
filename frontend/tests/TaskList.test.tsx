import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Task } from "../src/api";
import { TaskList } from "../src/features/tasks/TaskList";
import { renderWithProviders } from "./renderWithProviders";

function makeTask(overrides: Partial<Task> & { id: number; title: string }): Task {
  return {
    project_id: 1,
    parent_task_id: null,
    description: null,
    status: "queued",
    branch_name: null,
    pr_url: null,
    pending_question: null,
    created_at: "2026-04-21T00:00:00Z",
    updated_at: "2026-04-21T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function stubTaskFetch(tasks: Task[], capture: ReturnType<typeof vi.fn>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/projects/demo/tasks")) {
        return { ok: true, status: 200, json: async () => tasks } as Response;
      }
      if (url.endsWith("/tasks/1/cancel") && init?.method === "POST") {
        capture("cancel");
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...tasks[0], status: "cancelled" }),
        } as Response;
      }
      if (url.endsWith("/tasks/3/retry") && init?.method === "POST") {
        capture("retry");
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...tasks[2], status: "queued" }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }),
  );
}

describe("TaskList backlog controls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("filters tasks, renders hierarchy, and exposes cancel/retry actions", async () => {
    const capture = vi.fn();
    const tasks = [
      makeTask({ id: 1, title: "Parent task", status: "queued" }),
      makeTask({ id: 2, title: "Child task", parent_task_id: 1, status: "done" }),
      makeTask({ id: 3, title: "Broken task", status: "failed" }),
    ];
    stubTaskFetch(tasks, capture);

    renderWithProviders(<TaskList slug="demo" />);

    await waitFor(() => {
      expect(screen.getByText("Parent task")).toBeTruthy();
    });
    expect(screen.getByText("-- Child task")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText(/Search backlog/i), {
      target: { value: "child" },
    });
    expect(screen.queryByText("Parent task")).toBeNull();
    expect(screen.getByText("-- Child task")).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText(/Search backlog/i), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByLabelText(/Cancelar tarea Parent task/i));
    fireEvent.click(screen.getByLabelText(/Reintentar tarea Broken task/i));

    await waitFor(() => {
      expect(capture).toHaveBeenCalledWith("cancel");
      expect(capture).toHaveBeenCalledWith("retry");
    });
  });
});
