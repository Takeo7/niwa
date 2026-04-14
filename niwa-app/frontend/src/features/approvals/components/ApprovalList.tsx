import {
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from '@mantine/core';
import { Link } from 'react-router-dom';
import { MonoId } from '../../../shared/components/MonoId';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { riskStyle } from '../riskLevel';
import type { Approval } from '../../../shared/types';

const APPROVAL_STATUS_COLORS: Record<string, string> = {
  pending: 'orange',
  approved: 'teal',
  rejected: 'gray',
};

const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pending: 'Pendiente',
  approved: 'Aprobado',
  rejected: 'Rechazado',
};

function ApprovalStatusBadge({ status }: { status: string }) {
  // Approvals have their own status triple — we don't reuse
  // StatusBadge because its palette is tuned for run/task states.
  return (
    <Badge
      color={APPROVAL_STATUS_COLORS[status] ?? 'gray'}
      variant="light"
      size="sm"
      radius="sm"
    >
      {APPROVAL_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

function truncateReason(reason: string | null): string {
  if (!reason) return '—';
  const oneLine = reason.replace(/\s+/g, ' ').trim();
  return oneLine.length > 160 ? `${oneLine.slice(0, 157)}…` : oneLine;
}

interface Props {
  approvals: Approval[];
  isLoading?: boolean;
  /** Hide the task column when the list is already scoped to one
   *  task (TaskDetailPage tab).  Default: false. */
  hideTaskColumn?: boolean;
  onResolve?: (approval: Approval) => void;
  empty?: string;
}

/** Shared approval row component.  Used by both the global
 *  /approvals page and the per-task tab.  Layout favours vertical
 *  scanning: status + type badges on the first line, reason below. */
export function ApprovalList({
  approvals,
  isLoading,
  hideTaskColumn = false,
  onResolve,
  empty = 'No hay approvals que mostrar.',
}: Props) {
  if (isLoading) {
    return (
      <Center py="lg">
        <Loader size="sm" />
      </Center>
    );
  }
  if (!approvals.length) {
    return (
      <Paper withBorder p="md" radius="sm">
        <Text size="sm" c="dimmed" ta="center">
          {empty}
        </Text>
      </Paper>
    );
  }
  return (
    <Stack gap={6}>
      {approvals.map((a) => {
        const risk = riskStyle(a.risk_level);
        const isPending = a.status === 'pending';
        return (
          <Paper
            key={a.id}
            withBorder
            p="sm"
            radius="sm"
            style={{
              borderColor: isPending
                ? 'var(--mantine-color-orange-filled)'
                : 'var(--mantine-color-default-border)',
              borderWidth: isPending ? 2 : 1,
            }}
          >
            <Stack gap={6}>
              <Group justify="space-between" wrap="nowrap" align="flex-start">
                <Group gap="xs" wrap="wrap" style={{ minWidth: 0 }}>
                  <MonoId id={a.id} chars={8} />
                  <ApprovalStatusBadge status={a.status} />
                  <Badge
                    variant="outline"
                    size="sm"
                    radius="sm"
                    color="gray"
                  >
                    {a.approval_type}
                  </Badge>
                  <Badge
                    variant={risk.canonical ? 'light' : 'outline'}
                    size="sm"
                    radius="sm"
                    color={risk.color}
                    title={
                      risk.canonical
                        ? undefined
                        : 'Valor no canónico (ver BUGS-FOUND Bug 9)'
                    }
                  >
                    riesgo: {risk.label}
                  </Badge>
                  {a.backend_run_id === null && (
                    <Badge
                      variant="dot"
                      size="sm"
                      radius="sm"
                      color="gray"
                      title="Approval creado antes de seleccionar backend"
                    >
                      pre-routing
                    </Badge>
                  )}
                </Group>
                <Group gap="sm" wrap="nowrap" style={{ flexShrink: 0 }}>
                  <RelativeTime iso={a.requested_at} />
                  {isPending && onResolve && (
                    <Button
                      size="compact-sm"
                      variant="light"
                      onClick={() => onResolve(a)}
                    >
                      Resolver
                    </Button>
                  )}
                </Group>
              </Group>

              {!hideTaskColumn && (
                <Group gap="xs" wrap="nowrap">
                  <Text size="xs" c="dimmed">
                    Tarea:
                  </Text>
                  <Text
                    size="sm"
                    component={Link}
                    to={`/tasks/${a.task_id}`}
                    style={{ textDecoration: 'none' }}
                  >
                    {a.task_title ?? '(sin título)'}
                  </Text>
                  {a.task_status && (
                    <StatusBadge status={a.task_status} kind="task" />
                  )}
                </Group>
              )}

              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {truncateReason(a.reason)}
              </Text>

              {a.status !== 'pending' && (
                <Group gap="md" wrap="wrap">
                  {a.resolved_by && (
                    <Text size="xs" c="dimmed">
                      resuelto por: {a.resolved_by}
                    </Text>
                  )}
                  {a.resolved_at && (
                    <Text size="xs" c="dimmed">
                      <RelativeTime iso={a.resolved_at} />
                    </Text>
                  )}
                  {a.resolution_note && (
                    <Text size="xs" c="dimmed" style={{ flex: 1 }}>
                      nota: {a.resolution_note}
                    </Text>
                  )}
                </Group>
              )}
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}
