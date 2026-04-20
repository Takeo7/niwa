import { useEffect, useState } from "react";
import { Alert, Badge, Button, Code, Group, Stack, Text } from "@mantine/core";

import type { EosPayload, RunEvent, RunStatus } from "../../api";

// EventSource has no wildcard listener; the executor forwards the adapter's
// stream-json `type` plus synthetic `started/completed/failed/cancelled/
// error` frames around the run lifecycle, so we subscribe to that union.
const KNOWN_EVENT_TYPES = [
  "assistant", "user", "system", "tool_use", "tool_result", "result",
  "message", "started", "completed", "failed", "cancelled", "error",
  "unknown",
] as const;

const RUN_STATUS_COLOR: Record<RunStatus, string> = {
  queued: "gray", running: "blue", completed: "green",
  failed: "red", cancelled: "gray",
};

interface Props { runId: number | null }
interface StreamState {
  events: RunEvent[];
  eos: EosPayload | null;
  error: string | null;
}

function formatTime(iso: string | null): string {
  if (!iso) return "--:--:--";
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

// Opens EventSource on mount, closes on unmount or `eos` (avoids the
// browser's SSE auto-reconnect). StrictMode-safe: each effect run owns
// its own ES instance and the cleanup closes it.
function useEventStream(runId: number | null): StreamState {
  const [state, setState] = useState<StreamState>({
    events: [], eos: null, error: null,
  });

  useEffect(() => {
    if (runId == null) return;
    setState({ events: [], eos: null, error: null });

    const source = new EventSource("/api/runs/" + runId + "/events");
    let closed = false;
    const close = () => { if (!closed) { closed = true; source.close(); } };

    const onEvent = (ev: MessageEvent) => {
      if (closed) return;
      try {
        const parsed = JSON.parse(ev.data) as RunEvent;
        // Drop duplicates if the stream ever replays a row.
        setState((prev) => prev.events.some((e) => e.id === parsed.id)
          ? prev
          : { ...prev, events: [...prev.events, parsed] });
      } catch { /* malformed frame: ignore */ }
    };

    const onEos = (ev: MessageEvent) => {
      if (closed) return;
      try {
        const eos = JSON.parse(ev.data) as EosPayload;
        setState((prev) => ({ ...prev, eos }));
      } catch { /* stream is done regardless */ }
      close();
    };

    const onError = () => {
      if (!closed) setState((prev) => ({ ...prev, error: "stream error" }));
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

function EventRow({ event }: { event: RunEvent }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Stack gap={2}>
      <Group gap="xs" wrap="nowrap">
        <Badge variant="light" size="sm">{event.event_type}</Badge>
        <Text size="xs" c="dimmed">{formatTime(event.created_at)}</Text>
        <Button size="compact-xs" variant="subtle"
          onClick={() => setExpanded((v) => !v)}>
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
    return <Text c="dimmed" ta="center" py="sm">Run no iniciado</Text>;
  }

  return (
    <Stack gap="sm">
      {eos ? (
        <Alert color={RUN_STATUS_COLOR[eos.final_status] ?? "gray"}
          title={`Run ${eos.final_status}`}>
          <Text size="sm">
            exit code: {eos.exit_code ?? "—"}
            {eos.outcome ? ` · outcome: ${eos.outcome}` : null}
          </Text>
        </Alert>
      ) : null}
      {error && !eos ? (
        <Alert color="red" title="Stream error">{error}</Alert>
      ) : null}
      {events.length === 0 && !eos ? (
        <Text c="dimmed" ta="center" py="sm">Esperando eventos…</Text>
      ) : (
        <Stack gap="xs">
          {events.map((e) => <EventRow key={e.id} event={e} />)}
        </Stack>
      )}
    </Stack>
  );
}
