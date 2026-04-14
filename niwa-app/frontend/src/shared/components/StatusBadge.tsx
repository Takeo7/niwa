import { Badge, type MantineColor } from '@mantine/core';

// Canonical state palettes for the v0.2 execution pipeline.
// Keep neutrals where there's no semantic urgency; one accent per
// family.  Matches the "editorial product" register — no saturated
// traffic lights.
const RUN_STATUS_COLORS: Record<string, MantineColor> = {
  queued: 'gray',
  starting: 'gray',
  running: 'blue',
  waiting_approval: 'orange',
  waiting_input: 'yellow',
  succeeded: 'teal',
  failed: 'red',
  cancelled: 'gray',
  timed_out: 'red',
  rejected: 'red',
};

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: 'En cola',
  starting: 'Iniciando',
  running: 'Ejecutando',
  waiting_approval: 'Esperando approval',
  waiting_input: 'Esperando input',
  succeeded: 'OK',
  failed: 'Fallido',
  cancelled: 'Cancelado',
  timed_out: 'Timeout',
  rejected: 'Rechazado',
};

const TASK_STATUS_COLORS: Record<string, MantineColor> = {
  inbox: 'gray',
  pendiente: 'yellow',
  en_progreso: 'blue',
  bloqueada: 'red',
  revision: 'grape',
  waiting_input: 'yellow',
  hecha: 'teal',
  archivada: 'gray',
};

const TASK_STATUS_LABELS: Record<string, string> = {
  inbox: 'Inbox',
  pendiente: 'Pendiente',
  en_progreso: 'En progreso',
  bloqueada: 'Bloqueada',
  revision: 'Revisión',
  waiting_input: 'Esperando input',
  hecha: 'Hecha',
  archivada: 'Archivada',
};

type Kind = 'run' | 'task';

interface Props {
  status: string;
  kind?: Kind;
  size?: 'xs' | 'sm' | 'md';
}

export function StatusBadge({ status, kind = 'run', size = 'sm' }: Props) {
  const colors = kind === 'task' ? TASK_STATUS_COLORS : RUN_STATUS_COLORS;
  const labels = kind === 'task' ? TASK_STATUS_LABELS : RUN_STATUS_LABELS;
  return (
    <Badge
      color={colors[status] ?? 'gray'}
      variant="light"
      size={size}
      radius="sm"
    >
      {labels[status] ?? status}
    </Badge>
  );
}
