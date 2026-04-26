import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskCreateModal } from "../src/features/tasks/TaskCreateModal";
import type { Task } from "../src/api";
import { renderWithProviders } from "./renderWithProviders";

interface FetchCall {
  url: string;
  init: RequestInit;
}

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

  it("uploads files sequentially after task create", async () => {
    // Capture each call so we can assert ordering: task create must
    // resolve before the first attachment POST fires.
    const calls: FetchCall[] = [];
    const fetchSeq = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({ url, init: init ?? {} });
      if (url === "/api/projects/alpha/tasks") {
        return {
          ok: true,
          status: 201,
          json: async () => makeTask({ id: 7, title: "with files" }),
        } as Response;
      }
      if (url === "/api/tasks/7/attachments") {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: calls.length,
            task_id: 7,
            filename: "x",
            content_type: "text/plain",
            size_bytes: 1,
            created_at: "2026-04-26T00:00:00Z",
          }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchSeq);

    renderWithProviders(<TaskCreateModal slug="alpha" opened onClose={() => {}} />);

    const title = (await screen.findByLabelText(/Title/i)) as HTMLInputElement;
    await act(async () => {
      fireEvent.change(title, { target: { value: "with files" } });
    });

    // Inject files directly into the dropzone's hidden input — Mantine's
    // Dropzone renders a `<input type="file">` we can drive via change().
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    const fileA = new File(["AAA"], "a.txt", { type: "text/plain" });
    const fileB = new File(["BB"], "b.txt", { type: "text/plain" });
    await act(async () => {
      fireEvent.change(fileInput, { target: { files: [fileA, fileB] } });
    });

    const submit = (await screen.findByRole("button", { name: "Crear" })) as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    await act(async () => {
      fireEvent.click(submit);
    });

    // 1 task create + 2 attachment uploads, in that exact order.
    await waitFor(() => expect(fetchSeq).toHaveBeenCalledTimes(3));
    expect(calls[0]!.url).toBe("/api/projects/alpha/tasks");
    expect((calls[0]!.init.method ?? "GET")).toBe("POST");
    expect(calls[1]!.url).toBe("/api/tasks/7/attachments");
    expect(calls[1]!.init.method).toBe("POST");
    expect(calls[2]!.url).toBe("/api/tasks/7/attachments");

    // Attachment payloads must be FormData with a `file` field carrying
    // the originally-selected File instance.
    const body1 = calls[1]!.init.body;
    expect(body1).toBeInstanceOf(FormData);
    expect((body1 as FormData).get("file")).toBe(fileA);
    const body2 = calls[2]!.init.body;
    expect(body2).toBeInstanceOf(FormData);
    expect((body2 as FormData).get("file")).toBe(fileB);
  });
});
