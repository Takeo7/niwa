import {
  Stack,
  Group,
  Text,
  Badge,
  Loader,
  Center,
  Title,
  Divider,
  Button,
} from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { useServices } from '../hooks/useServices';
import { useReadiness } from '../../../shared/api/queries';
import { ServiceCard } from './ServiceCard';
import type { ReadinessBackend } from '../../../shared/types';

const CATEGORY_LABELS: Record<string, string> = {
  llm: 'Proveedores LLM',
  image: 'Generación de Imágenes',
  search: 'Búsqueda',
  hosting: 'Hosting',
  orchestration: 'Orquestación',
  notifications: 'Notificaciones',
  storage: 'Almacenamiento',
  tools: 'Herramientas',
};

// FIX-20260420: service.id is internal UI shorthand; the corresponding
// readiness backend lives under a canonical slug. This mapping exists
// because the legacy ServicesPanel had no concept of "backend probe" —
// rather than rename service ids across the settings surface, we
// bridge the two here. Add new backends to this map when they land.
const SERVICE_TO_BACKEND_SLUG: Record<string, string> = {
  llm_anthropic: 'claude_code',
  llm_openai: 'codex',
};

export function ServicesPanel() {
  const qc = useQueryClient();
  const { data: services, isLoading } = useServices();
  // Live probe from /api/readiness. When it fails or is pending the
  // per-card badge falls back to the legacy local heuristic — we do
  // not block the whole panel on the probe.
  const { data: readiness } = useReadiness();

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (!services?.length) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        No hay servicios configurados
      </Text>
    );
  }

  // FIX-20260420: build a slug → backend map once so ServiceCard
  // renders in O(1) per card instead of a linear scan per render.
  const backendBySlug: Record<string, ReadinessBackend> = {};
  for (const b of readiness?.backends ?? []) {
    backendBySlug[b.slug] = b;
  }

  const resolveProbe = (serviceId: string): ReadinessBackend | undefined => {
    const slug = SERVICE_TO_BACKEND_SLUG[serviceId];
    return slug ? backendBySlug[slug] : undefined;
  };

  // Counters now prefer the live probe when available; this keeps the
  // header honest even before the user expands any card.
  const totals = services.reduce(
    (acc, svc) => {
      const probe = resolveProbe(svc.id);
      if (probe) {
        const s = probe.claude_probe?.status;
        if (!probe.has_credential || s === 'credential_missing') {
          acc.notConfigured += 1;
        } else if (
          s === 'credential_expired'
          || s === 'credential_error'
          || s === 'no_cli'
          || s === 'error'
        ) {
          acc.errors += 1;
        } else {
          acc.configured += 1;
        }
        return acc;
      }
      const status = svc.status?.status;
      if (status === 'configured') acc.configured += 1;
      else if (status === 'error') acc.errors += 1;
      else acc.notConfigured += 1;
      return acc;
    },
    { configured: 0, notConfigured: 0, errors: 0 },
  );

  // Group by category
  const grouped = services.reduce<Record<string, typeof services>>(
    (acc, svc) => {
      const cat = svc.category || 'other';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(svc);
      return acc;
    },
    {},
  );

  const refresh = () => {
    // Invalidate both queries so the dashboard header and every badge
    // pull fresh state. No page reload — the brief calls this out
    // explicitly as "do not location.reload".
    qc.invalidateQueries({ queryKey: ['readiness'] });
    qc.invalidateQueries({ queryKey: ['services'] });
  };

  return (
    <Stack gap="md">
      {/* Dashboard header */}
      <Group gap="md" justify="space-between">
        <Group gap="md">
          <Badge size="lg" color="green" variant="light">
            {totals.configured} configurados
          </Badge>
          <Badge size="lg" color="gray" variant="light">
            {totals.notConfigured} sin configurar
          </Badge>
          {totals.errors > 0 && (
            <Badge size="lg" color="red" variant="light">
              {totals.errors} con errores
            </Badge>
          )}
        </Group>
        <Button
          size="xs"
          variant="subtle"
          leftSection={<IconRefresh size={14} />}
          onClick={refresh}
        >
          Refrescar
        </Button>
      </Group>

      {/* Categories */}
      {Object.entries(grouped).map(([category, svcs]) => (
        <Stack key={category} gap="sm">
          <Divider />
          <Title order={5}>
            {CATEGORY_LABELS[category] || category}
          </Title>
          {svcs.map((svc) => (
            <ServiceCard
              key={svc.id}
              service={svc}
              probe={resolveProbe(svc.id)}
            />
          ))}
        </Stack>
      ))}
    </Stack>
  );
}
