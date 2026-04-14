import { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Modal,
  Stack,
  Text,
  Textarea,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Link } from 'react-router-dom';
import { ApiError } from '../../../shared/api/client';
import { MonoId } from '../../../shared/components/MonoId';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { useResolveApproval } from '../hooks/useApprovals';
import { riskStyle } from '../riskLevel';
import type { Approval, ApprovalDecision } from '../../../shared/types';

interface Props {
  approval: Approval | null;
  onClose: () => void;
}

/** Modal used from both /approvals and /tasks/:id/approvals to
 *  approve or reject a pending approval.
 *
 *  Colour choices follow the editorial register: the primary action
 *  (Approve) uses the app's default filled variant; reject uses an
 *  outlined grey button rather than a saturated red.  The severity
 *  of the approval is communicated through the risk badge and the
 *  reason text, not through button colour. */
export function ApprovalResolveModal({ approval, onClose }: Props) {
  const [note, setNote] = useState('');
  const resolve = useResolveApproval();
  const opened = approval !== null;

  // Reset the textarea whenever the modal reopens for a different
  // approval.  Leaving stale text across invocations would be a
  // footgun when resolving many approvals in sequence.
  useEffect(() => {
    if (approval) {
      setNote('');
      resolve.reset();
    }
  }, [approval?.id]);

  if (!approval) {
    return <Modal opened={false} onClose={onClose} title="" />;
  }

  const risk = riskStyle(approval.risk_level);
  const alreadyResolved = approval.status !== 'pending';

  const submit = (decision: ApprovalDecision) => {
    resolve.mutate(
      {
        id: approval.id,
        decision,
        resolution_note: note.trim() || null,
      },
      {
        onSuccess: () => {
          notifications.show({
            title:
              decision === 'approve'
                ? 'Approval aprobado'
                : 'Approval rechazado',
            message:
              decision === 'approve'
                ? 'La solicitud queda autorizada.'
                : 'La solicitud queda rechazada.',
            color: decision === 'approve' ? 'teal' : 'gray',
          });
          onClose();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            notifications.show({
              title: 'Approval ya resuelto',
              message:
                'Otra sesión ha resuelto este approval con una ' +
                'decisión distinta. Refresca la lista para ver el ' +
                'estado actual.',
              color: 'yellow',
              autoClose: 8000,
            });
          } else {
            notifications.show({
              title: 'Error al resolver',
              message:
                err instanceof Error
                  ? err.message
                  : 'No se pudo contactar con el servidor',
              color: 'red',
            });
          }
        },
      },
    );
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Resolver approval"
      size="lg"
      centered
      closeOnClickOutside={!resolve.isPending}
      closeOnEscape={!resolve.isPending}
    >
      <Stack gap="md">
        <Stack gap={4}>
          <Group gap="xs" wrap="wrap">
            <MonoId id={approval.id} chars={12} />
            <Badge
              variant="outline"
              radius="sm"
              size="sm"
              color="gray"
            >
              {approval.approval_type}
            </Badge>
            <Badge
              variant={risk.canonical ? 'light' : 'outline'}
              radius="sm"
              size="sm"
              color={risk.color}
              title={
                risk.canonical
                  ? undefined
                  : 'Valor no canónico (ver BUGS-FOUND Bug 9)'
              }
            >
              riesgo: {risk.label}
            </Badge>
            {approval.backend_run_id === null && (
              <Badge
                variant="dot"
                radius="sm"
                size="sm"
                color="gray"
                title="Approval creado antes de seleccionar backend"
              >
                pre-routing
              </Badge>
            )}
          </Group>
          <Group gap="xs" wrap="wrap">
            <Text size="xs" c="dimmed">
              Tarea:
            </Text>
            <Text
              size="sm"
              component={Link}
              to={`/tasks/${approval.task_id}`}
              onClick={onClose}
              style={{ textDecoration: 'none' }}
            >
              {approval.task_title ?? '(sin título)'}
            </Text>
            {approval.task_status && (
              <StatusBadge
                status={approval.task_status}
                kind="task"
              />
            )}
          </Group>
          {approval.backend_run_id && (
            <Text size="xs" c="dimmed">
              Run: <MonoId id={approval.backend_run_id} chars={8} />
            </Text>
          )}
        </Stack>

        <Divider />

        <div>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} mb={4}>
            Motivo
          </Text>
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {approval.reason ?? '—'}
          </Text>
        </div>

        {alreadyResolved && (
          <Alert color="yellow" variant="light">
            Este approval ya está resuelto como{' '}
            <strong>{approval.status}</strong>. Cualquier intento de
            cambiar la decisión será rechazado por el backend.
          </Alert>
        )}

        <Textarea
          label="Nota de resolución (opcional)"
          description="Queda adjunta al registro; útil para auditoría y para que el siguiente humano entienda por qué se tomó la decisión."
          placeholder="Ej: Aprobado porque el comando es seguro en este sandbox."
          value={note}
          onChange={(e) => setNote(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={8}
          disabled={resolve.isPending || alreadyResolved}
        />

        <Group justify="space-between" mt="sm">
          <Button
            variant="subtle"
            onClick={onClose}
            disabled={resolve.isPending}
          >
            Cancelar
          </Button>
          <Group gap="sm">
            <Button
              variant="default"
              onClick={() => submit('reject')}
              loading={
                resolve.isPending && resolve.variables?.decision === 'reject'
              }
              disabled={resolve.isPending || alreadyResolved}
            >
              Rechazar
            </Button>
            <Button
              onClick={() => submit('approve')}
              loading={
                resolve.isPending &&
                resolve.variables?.decision === 'approve'
              }
              disabled={resolve.isPending || alreadyResolved}
            >
              Aprobar
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
