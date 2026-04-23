import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TaskEventStream } from "../src/features/tasks/TaskEventStream";
import { renderWithProviders } from "./renderWithProviders";

// Minimal EventSource stand-in for jsdom (which ships no implementation).
// `_emit(eventType, data)` drives a named SSE event into the component
// synchronously — the production `useEventStream` hook subscribes with
// `addEventListener(<eventType>, ...)` for each well-known type plus
// `eos`, so the test dispatches the same event types the backend emits.
class MockEventSource {
  url: string;
  readyState = 0;
  onerror: ((ev: Event) => void) | null = null;
  closed = false;
  private listeners = new Map<string, Set<(ev: MessageEvent) => void>>();

  static instances: MockEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    this.readyState = 1;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, cb: (ev: MessageEvent) => void): void {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(cb);
  }

  removeEventListener(type: string, cb: (ev: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(cb);
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }

  _emit(eventType: string, data: unknown): void {
    if (this.closed) return;
    const set = this.listeners.get(eventType);
    if (!set) return;
    const payload = typeof data === "string" ? data : JSON.stringify(data);
    const ev = new MessageEvent(eventType, { data: payload });
    for (const cb of set) cb(ev);
  }
}

describe("TaskEventStream", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders historical events from mocked EventSource", async () => {
    renderWithProviders(<TaskEventStream runId={42} />);

    // Wait for the hook's useEffect to instantiate the EventSource.
    await waitFor(() => {
      expect(MockEventSource.instances.length).toBe(1);
    });
    const es = MockEventSource.instances[0]!;
    expect(es.url).toBe("/api/runs/42/events");

    await act(async () => {
      es._emit("assistant", {
        id: 1,
        event_type: "assistant",
        payload: { text: "hi" },
        created_at: "2026-04-20T10:00:00Z",
      });
      es._emit("tool_use", {
        id: 2,
        event_type: "tool_use",
        payload: { name: "Read" },
        created_at: "2026-04-20T10:00:01Z",
      });
      es._emit("assistant", {
        id: 3,
        event_type: "assistant",
        payload: { text: "done" },
        created_at: "2026-04-20T10:00:02Z",
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText("assistant").length).toBe(2);
      expect(screen.getByText("tool_use")).toBeTruthy();
    });
  });

  it("shows eos summary when stream closes", async () => {
    renderWithProviders(<TaskEventStream runId={7} />);

    await waitFor(() => {
      expect(MockEventSource.instances.length).toBe(1);
    });
    const es = MockEventSource.instances[0]!;

    await act(async () => {
      es._emit("eos", {
        run_id: 7,
        final_status: "completed",
        exit_code: 0,
        outcome: "cli_ok",
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/Run completed/i)).toBeTruthy();
      expect(screen.getByText(/exit code: 0/i)).toBeTruthy();
    });

    // After eos the hook must close the connection so the browser does
    // not auto-reconnect per SSE semantics.
    expect(es.closed).toBe(true);

    // Subsequent emits are ignored: no new timeline rows appear.
    await act(async () => {
      es._emit("assistant", {
        id: 99,
        event_type: "assistant",
        payload: { text: "late" },
        created_at: "2026-04-20T10:05:00Z",
      });
    });
    expect(screen.queryByText(/late/i)).toBeNull();
  });
});
