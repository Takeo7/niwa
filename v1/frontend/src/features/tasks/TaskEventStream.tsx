import { useEffect, useState } from "react";
import { Alert, Badge, Button, Code, Group, Stack, Text } from "@mantine/core";

import type { EosPayload, RunEvent, RunStatus } from "../../api";

// Event types the backend may emit via SSE. EventSource requires one
// `addEventListener(type)` per named event (no wildcard). The executor
// fans out the adapter's `kind` directly (see backend executor core +
// adapter claude_code.py::_parse_line), so this set covers stream-json's
// known message types plus the synthetic `started/completed/failed/
// cancelled/error` frames the executor injects around the run lifecycle.
const KNOWN_EVENT_TYPES = [
  "assistant",
  "user",
  "system",
  "tool_use",
  "tool_result",
  "result",
  "message",
  "started",
  "completed",
  "failed",
  "cancelled",
  "error",
  "unknown",
] as const;

// Status badge colours map to the terminal RunStatus. Waiting is not a
// possible Run terminal state but we accept it here to match the task
// status palette if the caller reuses the component.
const RUN_STATUS_COLOR: Record<RunStatus, string> = {
  queued: "gray",
  running: "blue",
  completed: "green",
  failed: "red",
  cancelled: "gray",
};

interface Props {
  runId: number | null;
}

interface StreamState {
  events: RunEvent[];
  eos: EosPayload | null;
  error: string | null;
}

// Extracts HH:MM:SS from an ISO timestamp. Tolerates null/invalid input
// because the payload comes straight from JSON and we do not want the
// timeline to crash on a malformed row.
function formatTime(iso: string | null): string {
  if (!iso) return "--:--:--";
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

// Encapsulates the EventSource lifecycle for `runId`. Opens the stream on
// mount, subscribes to the known event types plus `eos`, and closes on
// unmount or as soon as `eos` arrives. StrictMode-safe: every effect run
// produces its own ES instance and the cleanup closes it, so the double
// mount in dev never leaves a dangling connection.
function useEventStream(runId: number | null): StreamState {
  const [state, setState] = useState<StreamState>({
    events: [],
    eos: null,
    error: null,
  });

  useEffect(() => {
    if (runId == null) return;
    // Fresh state for each mount: avoids showing stale events when the
    // user navigates between runs without unmounting the parent route.
    setState({ events: [], eos: null, error: null });

    const url = "/api/runs/" + runId + "/events";
    const source = new EventSource(url);
    let closed = false;

    const close = () => {
      if (closed) return;
      closed = true;
      source.close();
    };

    const onEvent = (ev: MessageEvent) => {
      if (closed) return;
      try {
        const parsed = JSON.parse(ev.data) as RunEvent;
        setState((prev) =>
          // Guard against duplicate ids if the backend ever resends a row
          // (heartbeats followed by a reconnect replay). Cheap linear
          // scan — timelines are small.
          prev.events.some((e) => e.id === parsed.id)
            ? prev
            : { ...prev, events: [...prev.events, parsed] },
        );
      } catch {
        // Ignore malformed frames; the timeline stays consistent.
      }
    };

    const onEos = (ev: MessageEvent) => {
      if (closed) return;
      try {
        const eos = JSON.parse(ev.data) as EosPayload;
        setState((prev) => ({ ...prev, eos }));
      } catch {
        // fall through: stream is done either way
      }
      // Close explicitly so the browser does not auto-reconnect per SSE
      // semantics (the server terminated cleanly, we are done).
      close();
    };

    const onError = () => {
      if (closed) return;
      setState((prev) => ({ ...prev, error: "stream error" }));
    };

    for (const type of KNOWN_EVENT_TYPES) {
      source.addEventListener(type, onEvent);
    }
    source.addEventListener("eos", onEos);
    source.onerror = onError;

    return close;
  }, [runId]);

  return state;
}

// Single timeline row. The payload is collapsible to keep the column
// readable when events carry large JSON blobs (see risks in the brief).
function EventRow({ event }: { event: RunEvent }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Stack gap={2}>
      <Group gap="xs" wrap="nowrap">
        <Badge variant="light" size="sm">
          {event.event_type}
        </Badge>
        <Text size="xs" c="dimmed">
          {formatTime(event.created_at)}
        </Text>
        <Button
          size="compact-xs"
          variant="subtle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "ocultar payload" : "ver payload"}
        </Button>
      </Group>
      {expanded ? (
        <Code block style={{ maxHeight: 240, overflow: "auto" }}>
          {JSON.stringify(event.payload, null, 2)}
        </Code>
      ) : null}
    </Stack>
  );
}

export function TaskEventStream({ runId }: Props) {
  const { events, eos, error } = useEventStream(runId);

  if (runId == null) {
    return (
      <Text c="dimmed" ta="center" py="sm">
        Run no iniciado
      </Text>
    );
  }

  return (
    <Stack gap="sm">
      {eos ? (
        <Alert
          color={RUN_STATUS_COLOR[eos.final_status] ?? "gray"}
          title={`Run ${eos.final_status}`}
        >
          <Text size="sm">
            exit code: {eos.exit_code ?? "—"}
            {eos.outcome ? ` · outcome: ${eos.outcome}` : null}
          </Text>
        </Alert>
      ) : null}
      {error && !eos ? (
        <Alert color="red" title="Stream error">
          {error}
        </Alert>
      ) : null}
      {events.length === 0 && !eos ? (
        <Text c="dimmed" ta="center" py="sm">
          Esperando eventos…
        </Text>
      ) : (
        <Stack gap="xs">
          {events.map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
