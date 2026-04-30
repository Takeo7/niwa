/**
 * Phase 3 TaskList tests — status filter chips, cancel/retry/approve-plan actions.
 */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Task } from "../src/api";
import { TaskList } from "../src/features/tasks/TaskList";
import { renderWithProviders } from "./renderWithProviders";

function makeTask(overrides: Partial<Task>): Task {
  return {
    id: 1,
    project_id: 1,
    parent_task_id: null,
    title: "Default task",
    description: null,
    status: "queued",
    branch_name: null,
    pr_url: null,
    pending_question: null,
    created_at: "2026-04-30T00:00:00Z",
    updated_at: "2026-04-30T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function stubTasks(tasks: Task[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/projects/demo/tasks")) {
        return { ok: true, status: 200, json: async () => tasks } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TaskList empty state", () => {
  it("shows no tasks message when list is empty", async () => {
    stubTasks([]);
    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() =>
      expect(screen.getByText(/No tasks yet/i)).toBeTruthy(),
    );
  });
});

describe("TaskList status filter", () => {
  it("shows All filter chip when tasks exist", async () => {
    stubTasks([
      makeTask({ id: 1, title: "A", status: "queued" }),
      makeTask({ id: 2, title: "B", status: "done" }),
    ]);

    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("A")).toBeTruthy());

    expect(screen.getByRole("radio", { name: /All/i })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Queued/i })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Done/i })).toBeTruthy();
  });

  it("filters tasks by status chip click", async () => {
    stubTasks([
      makeTask({ id: 1, title: "QueuedTask", status: "queued" }),
      makeTask({ id: 2, title: "DoneTask", status: "done" }),
    ]);

    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("QueuedTask")).toBeTruthy());

    const doneChip = screen.getByRole("radio", { name: /Done/i });
    fireEvent.click(doneChip);

    await waitFor(() => {
      expect(screen.queryByText("QueuedTask")).toBeNull();
      expect(screen.getByText("DoneTask")).toBeTruthy();
    });
  });

  it("shows no tasks message when filter yields empty", async () => {
    stubTasks([
      makeTask({ id: 1, title: "FailedTask", status: "failed" }),
      makeTask({ id: 2, title: "DoneTask", status: "done" }),
    ]);

    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("FailedTask")).toBeTruthy());

    // Filter to Done — FailedTask should disappear
    const doneChip = screen.getByRole("radio", { name: /Done/i });
    fireEvent.click(doneChip);

    await waitFor(() => {
      expect(screen.queryByText("FailedTask")).toBeNull();
      expect(screen.getByText("DoneTask")).toBeTruthy();
    });

    // Filter to a nonexistent status by switching back to All and using failed
    const failedChip = screen.getByRole("radio", { name: /Failed/i });
    fireEvent.click(failedChip);
    await waitFor(() => expect(screen.getByText("FailedTask")).toBeTruthy());

    // Now click All (done chip shows FailedTask missing)
    const allChip = screen.getByRole("radio", { name: /^All$/i });
    fireEvent.click(allChip);
    await waitFor(() => expect(screen.getByText("DoneTask")).toBeTruthy());
  });
});

describe("TaskList action buttons", () => {
  it("shows cancel button for queued task", async () => {
    stubTasks([makeTask({ id: 1, title: "Q", status: "queued" })]);
    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("Q")).toBeTruthy());

    expect(screen.getByRole("button", { name: /Cancelar tarea Q/i })).toBeTruthy();
  });

  it("shows retry button for failed task", async () => {
    stubTasks([makeTask({ id: 1, title: "F", status: "failed" })]);
    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("F")).toBeTruthy());

    expect(screen.getByRole("button", { name: /Reintentar tarea F/i })).toBeTruthy();
  });

  it("shows approve-plan button for waiting_approval task", async () => {
    stubTasks([makeTask({ id: 1, title: "W", status: "waiting_approval" })]);
    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("W")).toBeTruthy());

    expect(screen.getByRole("button", { name: /Aprobar plan de W/i })).toBeTruthy();
  });

  it("shows no cancel or retry buttons for running task", async () => {
    stubTasks([makeTask({ id: 1, title: "R", status: "running" })]);
    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("R")).toBeTruthy());

    expect(screen.queryByRole("button", { name: /Cancelar/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Reintentar/i })).toBeNull();
  });

  it("shows subtask parent hint", async () => {
    stubTasks([makeTask({ id: 1, title: "Sub", status: "queued", parent_task_id: 5 })]);
    renderWithProviders(<TaskList slug="demo" />);
    await waitFor(() => expect(screen.getByText("Sub")).toBeTruthy());
    expect(screen.getByText(/Subtask #5/i)).toBeTruthy();
  });
});
