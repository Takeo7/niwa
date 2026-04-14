import {
  Paper,
  Stack,
  Group,
  Text,
  Badge,
  UnstyledButton,
  Loader,
  Center,
} from '@mantine/core';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { MonoId } from '../../../shared/components/MonoId';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import { DurationLabel } from '../../../shared/components/DurationLabel';
import type { BackendRun } from '../../../shared/types';

const RELATION_LABELS: Record<string, string> = {
  fallback: 'Fallback',
  resume: 'Resume',
  retry: 'Retry',
};

interface Props {
  runs: BackendRun[];
  selectedId: string | null;
  onSelect: (runId: string) => void;
  isLoading?: boolean;
}

/** Compact list of runs for a task.  Click to select (not navigate).
 *  The selected run's events render in a sibling panel. */
export function RunList({ runs, selectedId, onSelect, isLoading }: Props) {
  if (isLoading) {
    return (
      <Center py="md">
        <Loader size="sm" />
      </Center>
    );
  }
  if (!runs.length) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="dimmed" ta="center">
          Esta tarea todavía no ha generado ningún run.
        </Text>
      </Paper>
    );
  }
  return (
    <Stack gap={6}>
      {runs.map((run) => {
        const isSelected = run.id === selectedId;
        const isRunning =
          run.status === 'running' ||
          run.status === 'starting' ||
          run.status === 'queued';
        return (
          <UnstyledButton
            key={run.id}
            onClick={() => onSelect(run.id)}
            style={{
              display: 'block',
              width: '100%',
              borderRadius: 'var(--mantine-radius-sm)',
              border: '1px solid var(--mantine-color-default-border)',
              padding: '8px 10px',
              background: isSelected
                ? 'var(--mantine-color-default-hover)'
                : 'transparent',
              borderColor: isSelected
                ? 'var(--mantine-color-blue-filled)'
                : 'var(--mantine-color-default-border)',
            }}
          >
            <Group justify="space-between" wrap="nowrap">
              <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
                <MonoId id={run.id} chars={8} />
                <StatusBadge status={run.status} kind="run" />
                {run.backend_profile_slug && (
                  <Badge
                    variant="outline"
                    size="sm"
                    radius="sm"
                    color="gray"
                  >
                    {run.backend_profile_slug}
                  </Badge>
                )}
                {run.relation_type && (
                  <Badge
                    variant="dot"
                    size="sm"
                    radius="sm"
                    color="orange"
                  >
                    {RELATION_LABELS[run.relation_type] ??
                      run.relation_type}
                  </Badge>
                )}
              </Group>
              <Group gap="sm" wrap="nowrap">
                <DurationLabel
                  startedAt={run.started_at}
                  finishedAt={run.finished_at}
                  isRunning={isRunning}
                />
                <RelativeTime iso={run.created_at} />
              </Group>
            </Group>
            {run.error_code && (
              <Text size="xs" c="red" mt={4}>
                {run.error_code}
              </Text>
            )}
          </UnstyledButton>
        );
      })}
    </Stack>
  );
}
