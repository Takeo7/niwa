import { Group, Badge, Tooltip } from '@mantine/core';
import { useNavigate } from 'react-router-dom';
import {
  IconChecklist,
  IconShieldCheck,
  IconActivity,
} from '@tabler/icons-react';
import type { Turn } from '../types';

interface Props {
  turn: Turn;
}

/**
 * Chips horizontales con los IDs devueltos por actions_taken del
 * turn.  Cada chip es clicable y navega al detalle correspondiente
 * en otra vista de PR-10 (tasks, runs, approvals).
 *
 * task_id → /tasks/:id
 * run_id  → /tasks (fallback — el run_id por sí solo no tiene ruta
 *           dedicada; el detalle vive en /tasks/:taskId/runs cuando
 *           el task_id es conocido)
 * approval_id → /approvals
 */
export function ActionChips({ turn }: Props) {
  const navigate = useNavigate();
  const hasAny =
    turn.task_ids.length > 0 ||
    turn.approval_ids.length > 0 ||
    turn.run_ids.length > 0;
  if (!hasAny) return null;

  return (
    <Group gap={6} wrap="wrap">
      {turn.task_ids.map((id) => (
        <Tooltip key={`t-${id}`} label={id} withArrow openDelay={300}>
          <Badge
            variant="light"
            color="blue"
            leftSection={<IconChecklist size={12} />}
            style={{
              cursor: 'pointer',
              fontVariantNumeric: 'tabular-nums',
              fontFamily: 'var(--mantine-font-family-monospace)',
              textTransform: 'none',
            }}
            onClick={() => navigate(`/tasks/${id}`)}
          >
            task:{short(id)}
          </Badge>
        </Tooltip>
      ))}
      {turn.approval_ids.map((id) => (
        <Tooltip key={`a-${id}`} label={id} withArrow openDelay={300}>
          <Badge
            variant="light"
            color="yellow"
            leftSection={<IconShieldCheck size={12} />}
            style={{
              cursor: 'pointer',
              fontVariantNumeric: 'tabular-nums',
              fontFamily: 'var(--mantine-font-family-monospace)',
              textTransform: 'none',
            }}
            onClick={() => navigate('/approvals')}
          >
            approval:{short(id)}
          </Badge>
        </Tooltip>
      ))}
      {turn.run_ids.map((id) => {
        // Si el turn trae exactamente un task_id, asumimos que el run
        // pertenece a esa tarea y navegamos a /tasks/:taskId/runs.  En
        // caso contrario (ambiguo o sin task_id), vamos a /tasks.
        const taskId =
          turn.task_ids.length === 1 ? turn.task_ids[0] : null;
        const target = taskId ? `/tasks/${taskId}/runs` : '/tasks';
        return (
          <Tooltip key={`r-${id}`} label={id} withArrow openDelay={300}>
            <Badge
              variant="light"
              color="teal"
              leftSection={<IconActivity size={12} />}
              style={{
                cursor: 'pointer',
                fontVariantNumeric: 'tabular-nums',
                fontFamily: 'var(--mantine-font-family-monospace)',
                textTransform: 'none',
              }}
              onClick={() => navigate(target)}
            >
              run:{short(id)}
            </Badge>
          </Tooltip>
        );
      })}
    </Group>
  );
}

function short(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}
