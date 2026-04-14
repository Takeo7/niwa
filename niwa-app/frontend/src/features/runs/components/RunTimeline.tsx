import { useMemo } from 'react';
import { Paper, Loader, Center, Text, Stack, Group } from '@mantine/core';
import {
  Timeline,
  type TimelineItem,
} from '../../../shared/components/Timeline';
import { MonoId } from '../../../shared/components/MonoId';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { DurationLabel } from '../../../shared/components/DurationLabel';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import { useRun, useRunEvents } from '../hooks/useRuns';
import type { BackendRunEvent } from '../../../shared/types';

interface Props {
  runId: string | null;
}

const RAW_SENTINEL = '(raw event)';
const UNPARSABLE_SENTINEL = '(unparsable payload)';

/** Pull a short, readable title out of a backend_run_event for the
 *  Timeline.  Rules are explicit per event_type (PR-04 Decisión 7:
 *  system_init, assistant_message, tool_use, tool_result, result,
 *  error, raw_output — plus fallback_escalation from PR-07 Dec 5).
 *
 *  Contract:
 *    - ``null`` is returned ONLY when the event has no payload_json
 *      and the event_type carries no discriminator (``raw_output``):
 *      the Timeline renders just the ``kind`` badge in that case.
 *    - For every other case we return a non-empty string.  If the
 *      payload is present but the shape is unrecognised we return
 *      ``(raw event)`` rather than silently empty — the reader can
 *      then open the payload block below to inspect it.
 *
 *  No silent empty strings.  If the contract evolves (adapter adds
 *  a new event_type or changes a field name) the sentinel surfaces
 *  the drift instead of hiding it.
 */
function extractTitle(ev: BackendRunEvent): string | null {
  const type = ev.event_type;

  // raw_output never carries payload_json — the ``message`` column
  // carries the unparsable stdout line, which the Timeline renders
  // as body.  Returning null is the correct signal here.
  if (type === 'raw_output') return null;

  if (!ev.payload_json) {
    return RAW_SENTINEL;
  }

  let p: Record<string, unknown>;
  try {
    const parsed = JSON.parse(ev.payload_json);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return RAW_SENTINEL;
    }
    p = parsed as Record<string, unknown>;
  } catch {
    return UNPARSABLE_SENTINEL;
  }

  const str = (v: unknown): string | null =>
    typeof v === 'string' && v.length > 0 ? v : null;

  // ── system_* (includes system_init) ──
  //   payload is the full stream-json ``system`` message; useful
  //   discriminators are ``subtype``, ``model``, ``session_id``.
  if (type.startsWith('system')) {
    const subtype = str(p.subtype);
    const model = str(p.model);
    const session = str(p.session_id);
    if (subtype && model) return `${subtype} · ${model}`;
    if (subtype) return subtype;
    if (model) return model;
    if (session) return `session ${session.slice(0, 8)}`;
    return RAW_SENTINEL;
  }

  // ── assistant_message ──
  //   payload = {"content": [{"type":"text","text": "..."}]}
  if (type === 'assistant_message') {
    const content = p.content;
    if (Array.isArray(content)) {
      for (const block of content) {
        if (
          block && typeof block === 'object' &&
          (block as Record<string, unknown>).type === 'text'
        ) {
          const text = str((block as Record<string, unknown>).text);
          if (text) {
            const firstLine = text.split('\n')[0].trim();
            return firstLine.length > 120
              ? `${firstLine.slice(0, 117)}…`
              : firstLine;
          }
        }
      }
    }
    return RAW_SENTINEL;
  }

  // ── tool_use ──
  //   payload = {"tool_name": "Bash", "input": {...}}
  //   Historical payloads from earlier PR-04 snapshots may also have
  //   ``name``; honour both.
  if (type === 'tool_use') {
    return (
      str(p.tool_name) ?? str(p.name) ?? str(p.tool) ?? RAW_SENTINEL
    );
  }

  // ── tool_result ──
  //   payload = {"content": "..."} (string) or a blocks array
  if (type === 'tool_result') {
    const content = p.content;
    if (typeof content === 'string' && content.length > 0) {
      const oneLine = content.replace(/\s+/g, ' ').trim();
      return oneLine.length > 120
        ? `${oneLine.slice(0, 117)}…`
        : oneLine;
    }
    if (Array.isArray(content) && content.length > 0) {
      return `${content.length} block(s)`;
    }
    return RAW_SENTINEL;
  }

  // ── result ──
  //   payload = full result message with cost_usd / model / duration
  if (type === 'result') {
    const cost = p.cost_usd;
    const model = str(p.model);
    const costStr =
      typeof cost === 'number' ? `$${cost.toFixed(4)}` : null;
    if (costStr && model) return `${costStr} · ${model}`;
    if (costStr) return costStr;
    if (model) return model;
    return RAW_SENTINEL;
  }

  // ── error ──
  //   payload = {"error": {"type": "...", "message": "..."}} or
  //   a flat {"message": "..."} depending on source.
  if (type === 'error') {
    const err = p.error;
    if (err && typeof err === 'object') {
      const e = err as Record<string, unknown>;
      const et = str(e.type);
      const em = str(e.message);
      if (et && em) return `${et}: ${em.slice(0, 100)}`;
      if (em) return em.slice(0, 120);
      if (et) return et;
    }
    const flat = str(p.message);
    if (flat) return flat.slice(0, 120);
    return RAW_SENTINEL;
  }

  // ── fallback_escalation (PR-07 Decisión 5) ──
  if (type === 'fallback_escalation') {
    const from = str(p.from_slug) ?? str(p.from);
    const to = str(p.to_slug) ?? str(p.to);
    if (from && to) return `${from} → ${to}`;
    return RAW_SENTINEL;
  }

  // ── Unknown event_type — payload exists but we have no rule.
  // Return sentinel, not empty.  This is the "adapter evolved"
  // signal.
  return RAW_SENTINEL;
}

function eventsToTimeline(events: BackendRunEvent[]): TimelineItem[] {
  return events.map((ev) => ({
    id: ev.id,
    kind: ev.event_type,
    title: extractTitle(ev),
    timestamp: ev.created_at,
    body: ev.message ?? undefined,
    payload: ev.payload_json ?? null,
  }));
}

export function RunTimeline({ runId }: Props) {
  const { data: run, isLoading: runLoading } = useRun(runId);
  const {
    data: events,
    isLoading: evLoading,
  } = useRunEvents(runId);

  const items = useMemo(
    () => eventsToTimeline(events ?? []),
    [events],
  );

  if (!runId) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="dimmed" ta="center">
          Selecciona un run para ver su timeline.
        </Text>
      </Paper>
    );
  }

  if (runLoading) {
    return (
      <Center py="lg">
        <Loader size="sm" />
      </Center>
    );
  }

  if (!run) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="dimmed" ta="center">
          Run no encontrado.
        </Text>
      </Paper>
    );
  }

  const isRunning =
    run.status === 'running' ||
    run.status === 'starting' ||
    run.status === 'queued';

  return (
    <Stack gap="sm">
      <Paper withBorder p="sm" radius="sm">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <MonoId id={run.id} chars={12} />
            <StatusBadge status={run.status} kind="run" />
            {run.backend_profile_display_name && (
              <Text size="sm" c="dimmed">
                {run.backend_profile_display_name}
              </Text>
            )}
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Text size="xs" c="dimmed">
              Duración:{' '}
              <DurationLabel
                startedAt={run.started_at}
                finishedAt={run.finished_at}
                isRunning={isRunning}
              />
            </Text>
            <Text size="xs" c="dimmed">
              Heartbeat:{' '}
              <RelativeTime iso={run.heartbeat_at} />
            </Text>
          </Group>
        </Group>
        {run.model_resolved && (
          <Text size="xs" c="dimmed" mt={6}>
            Modelo: {run.model_resolved}
          </Text>
        )}
        {run.error_code && (
          <Text size="xs" c="red" mt={6}>
            Error: {run.error_code}
          </Text>
        )}
      </Paper>

      <Paper withBorder p="sm" radius="sm">
        {evLoading && !events ? (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        ) : (
          <Timeline
            items={items}
            empty="Este run aún no ha emitido eventos."
          />
        )}
      </Paper>
    </Stack>
  );
}
