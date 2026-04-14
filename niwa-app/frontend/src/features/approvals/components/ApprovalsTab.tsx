import { Stack, Text, Title } from '@mantine/core';
import { useParams } from 'react-router-dom';
import { ApprovalList } from './ApprovalList';
import { useTaskApprovals } from '../hooks/useApprovals';

/** /tasks/:taskId/approvals — approvals scoped to a single task.
 *  Tab is always visible (even when empty) so the URL remains a
 *  stable deep-link. */
export function ApprovalsTab() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: approvals, isLoading } = useTaskApprovals(taskId);

  return (
    <Stack gap="md">
      <div>
        <Title order={5}>Approvals</Title>
        <Text size="xs" c="dimmed">
          Solicitudes de approval ligadas a esta tarea. Incluye tanto
          gates pre-routing (sin <code>backend_run</code>) como
          violaciones detectadas en runtime (<code>
            waiting_approval
          </code>).
        </Text>
      </div>
      <ApprovalList
        approvals={approvals ?? []}
        isLoading={isLoading}
        hideTaskColumn
        empty="Esta tarea aún no ha generado ningún approval."
      />
    </Stack>
  );
}
