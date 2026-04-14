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

/** Try to pull a short, readable title out of the event payload.
 *  This is best-effort: the shape of payload_json is adapter-specific
 *  and can evolve.  If we can't find something useful, return null
 *  so the Timeline component renders just the kind label. */
function extractTitle(ev: BackendRunEvent): string | null {
  if (!ev.payload_json) return null;
  try {
    const p = JSON.parse(ev.payload_json) as Record<string, unknown>;
    if (typeof p.name === 'string') return p.name; // tool_use.name
    if (typeof p.tool === 'string') return p.tool as string;
    if (typeof p.model === 'string') return p.model as string;
    if (typeof p.command === 'string') return p.command as string;
  } catch {
    /* ignore */
  }
  return null;
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
