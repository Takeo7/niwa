import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskCreateModal } from "../src/features/tasks/TaskCreateModal";
import type { Task } from "../src/api";
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
    created_at: "2026-04-20T00:00:00Z",
    updated_at: "2026-04-20T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("TaskCreateModal", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Default: succeed with a created task. Individual tests can override.
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => makeTask({ id: 1, title: "Do the thing" }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("submit button disabled with empty title", async () => {
    renderWithProviders(
      <TaskCreateModal slug="alpha" opened onClose={() => {}} />,
    );

    // Mantine Modal portals into document.body; assert against the
    // accessible submit button by its role + name.
    const submit = await screen.findByRole("button", { name: "Crear" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    // Sanity check: no network call attempted on mount.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("valid submit posts and closes", async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <TaskCreateModal slug="alpha" opened onClose={onClose} />,
    );

    const title = (await screen.findByLabelText(
      /Title/i,
    )) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(title, { target: { value: "Do the thing" } });
    });

    const submit = (await screen.findByRole("button", {
      name: "Crear",
    })) as HTMLButtonElement;
    await waitFor(() => {
      expect(submit.disabled).toBe(false);
    });
    await act(async () => {
      fireEvent.click(submit);
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/projects/alpha/tasks");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      title: "Do the thing",
      description: null,
    });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });
});
