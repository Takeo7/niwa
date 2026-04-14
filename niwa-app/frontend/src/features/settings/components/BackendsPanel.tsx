import { useState } from 'react';
import {
  Badge,
  Card,
  Center,
  Group,
  Loader,
  Stack,
  Text,
} from '@mantine/core';
import { useBackendProfiles } from '../../../shared/api/queries';
import type { BackendProfile } from '../../../shared/types';
import { BackendProfileRow } from './BackendProfileRow';
import { BackendProfileEditModal } from './BackendProfileEditModal';

/** Listado de ``backend_profiles`` — cada fila muestra metadata
 *  (read-only) + campos editables mediante modal.
 */
export function BackendsPanel() {
  const { data: profiles, isLoading, isError } = useBackendProfiles();
  const [editing, setEditing] = useState<BackendProfile | null>(null);

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader size="sm" />
      </Center>
    );
  }

  if (isError) {
    return (
      <Card withBorder padding="md">
        <Text size="sm" c="red">
          No se pudo cargar la lista de backends.
        </Text>
      </Card>
    );
  }

  if (!profiles || profiles.length === 0) {
    return (
      <Card withBorder padding="md">
        <Text size="sm" c="dimmed">
          No hay perfiles de backend registrados. El seed de
          <code> backend_profiles </code> se aplica al arrancar la
          app. Si la lista está vacía, revisa los logs de{' '}
          <code>init_db()</code>.
        </Text>
      </Card>
    );
  }

  const enabled = profiles.filter((p) => p.enabled).length;

  return (
    <Stack gap="md">
      <Group gap="xs">
        <Badge variant="light" color="brand">
          {profiles.length} perfiles
        </Badge>
        <Badge variant="light" color="green">
          {enabled} habilitados
        </Badge>
      </Group>

      <Stack gap="sm">
        {profiles.map((p) => (
          <BackendProfileRow
            key={p.id}
            profile={p}
            onEdit={() => setEditing(p)}
          />
        ))}
      </Stack>

      {editing && (
        <BackendProfileEditModal
          profile={editing}
          opened
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}
