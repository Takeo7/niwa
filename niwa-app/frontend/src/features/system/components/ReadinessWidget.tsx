import {
  Alert,
  Badge,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconCheck,
  IconX,
} from '@tabler/icons-react';
import { useReadiness } from '../../../shared/api/queries';
import type { Readiness, ReadinessBackend } from '../../../shared/types';

type Item = {
  label: string;
  ok: boolean;
  detail?: string;
};

function okBadge(ok: boolean) {
  return ok ? (
    <Badge color="teal" leftSection={<IconCheck size={12} />}>
      OK
    </Badge>
  ) : (
    <Badge color="red" leftSection={<IconX size={12} />}>
      Falta
    </Badge>
  );
}

function backendToItem(b: ReadinessBackend): Item {
  const reasons: string[] = [];
  if (!b.enabled) reasons.push('deshabilitado');
  if (!b.has_credential) reasons.push('sin credencial');
  if (!b.model_present) reasons.push('sin modelo por defecto');
  if (b.enabled && b.has_credential && b.model_present && !b.reachable) {
    reasons.push('sin comando CLI configurado');
  }
  const mode = b.auth_mode || 'api_key';
  const detailParts = [`auth=${mode}`];
  if (b.default_model) detailParts.push(`model=${b.default_model}`);
  if (reasons.length) detailParts.push(reasons.join(', '));
  return {
    label: `Backend · ${b.display_name}`,
    ok: b.reachable,
    detail: detailParts.join(' · '),
  };
}

function buildItems(r: Readiness): Item[] {
  return [
    { label: 'Docker', ok: r.docker_ok },
    { label: 'Base de datos', ok: r.db_ok },
    {
      label: 'Credenciales admin',
      ok: r.admin_ok,
      detail: r.admin_detail,
    },
    ...r.backends.map(backendToItem),
    {
      label: 'Hosting',
      ok: r.hosting_ok,
      detail: r.hosting_detail,
    },
  ];
}

export function ReadinessWidget() {
  const { data, isLoading, isError, error } = useReadiness();

  if (isLoading) {
    return (
      <Card withBorder>
        <Group gap="sm">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Comprobando readiness…
          </Text>
        </Group>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Alert
        color="red"
        icon={<IconAlertTriangle size={16} />}
        title="No pude leer /api/readiness"
      >
        {error instanceof Error ? error.message : 'Error desconocido'}
      </Alert>
    );
  }

  const items = buildItems(data);
  const missing = items.filter((i) => !i.ok);
  const allOk = missing.length === 0;

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Group justify="space-between">
          <Title order={5}>Qué falta para estar listo</Title>
          {allOk ? (
            <Badge color="teal" leftSection={<IconCheck size={12} />}>
              Todo listo
            </Badge>
          ) : (
            <Badge color="red">{missing.length} pendiente(s)</Badge>
          )}
        </Group>
        {allOk ? (
          <Text size="sm" c="dimmed">
            Todos los componentes necesarios para ejecutar tareas están
            configurados.
          </Text>
        ) : (
          <Stack gap={4}>
            {items.map((item) => (
              <Group key={item.label} justify="space-between" wrap="nowrap">
                <Stack gap={0}>
                  <Text size="sm" fw={500}>
                    {item.label}
                  </Text>
                  {item.detail && (
                    <Text size="xs" c="dimmed">
                      {item.detail}
                    </Text>
                  )}
                </Stack>
                {okBadge(item.ok)}
              </Group>
            ))}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
