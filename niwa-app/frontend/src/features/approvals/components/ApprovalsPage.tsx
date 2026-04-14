import { useState } from 'react';
import {
  Group,
  SegmentedControl,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { ApprovalList } from './ApprovalList';
import { ApprovalResolveModal } from './ApprovalResolveModal';
import { useApprovals } from '../hooks/useApprovals';
import type { Approval, ApprovalStatus } from '../../../shared/types';

type Filter = ApprovalStatus | 'all';

/** /approvals — global list of approvals.  Defaults to ``pending``
 *  because that's the actionable set; ``all`` exposes history.
 *  No server-side filter for risk_level because Bug 9 (PR-06) means
 *  the column holds drifting values, so filtering on it would hide
 *  rows unexpectedly.  Filtering can come later if the inventory
 *  grows large enough to need it. */
export function ApprovalsPage() {
  const [filter, setFilter] = useState<Filter>('pending');
  const [resolving, setResolving] = useState<Approval | null>(null);
  const { data: approvals, isLoading } = useApprovals(filter);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Title order={3}>Aprobaciones</Title>
          <Text size="xs" c="dimmed">
            Solicitudes de approval generadas por el router o por el
            adapter en runtime. Un approval puede existir sin{' '}
            <code>backend_run</code> asociado (pre-routing) o con uno
            detenido en <code>waiting_approval</code>.
          </Text>
        </div>
        <SegmentedControl
          size="sm"
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          data={[
            { label: 'Pendientes', value: 'pending' },
            { label: 'Aprobadas', value: 'approved' },
            { label: 'Rechazadas', value: 'rejected' },
            { label: 'Todas', value: 'all' },
          ]}
        />
      </Group>

      <ApprovalList
        approvals={approvals ?? []}
        isLoading={isLoading}
        onResolve={setResolving}
        empty={
          filter === 'pending'
            ? 'No hay approvals pendientes. Todo al día.'
            : 'No hay approvals que coincidan con el filtro.'
        }
      />

      <ApprovalResolveModal
        approval={resolving}
        onClose={() => setResolving(null)}
      />
    </Stack>
  );
}
