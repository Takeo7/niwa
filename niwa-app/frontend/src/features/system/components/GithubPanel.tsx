import { useState } from 'react';
import {
  Card,
  Stack,
  Group,
  Title,
  Text,
  PasswordInput,
  Button,
  Badge,
  Alert,
  Loader,
  Anchor,
  Code,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconBrandGithub,
  IconInfoCircle,
  IconCheck,
} from '@tabler/icons-react';
import {
  useGithubStatus,
  useSaveGithubToken,
  useDisconnectGithub,
} from '../../../shared/api/queries';

export function GithubPanel() {
  const status = useGithubStatus();
  const save = useSaveGithubToken();
  const disconnect = useDisconnectGithub();
  const [token, setToken] = useState('');

  async function handleSave() {
    const trimmed = token.trim();
    if (!trimmed) {
      notifications.show({
        title: 'Token vacío',
        message: 'Pega tu PAT antes de guardar.',
        color: 'red',
      });
      return;
    }
    try {
      const result = await save.mutateAsync(trimmed);
      notifications.show({
        title: 'GitHub conectado',
        message: `@${result.username}`,
        color: 'green',
      });
      setToken('');
    } catch (err) {
      notifications.show({
        title: 'No se pudo guardar el token',
        message: err instanceof Error ? err.message : 'Error desconocido',
        color: 'red',
      });
    }
  }

  async function handleDisconnect() {
    try {
      await disconnect.mutateAsync();
      notifications.show({
        title: 'GitHub desconectado',
        message: 'El token ha sido eliminado.',
        color: 'yellow',
      });
    } catch (err) {
      notifications.show({
        title: 'Error',
        message: err instanceof Error ? err.message : 'Fallo desconocido',
        color: 'red',
      });
    }
  }

  if (status.isLoading) {
    return (
      <Card withBorder>
        <Loader size="sm" />
      </Card>
    );
  }

  const connected = Boolean(status.data?.connected);

  return (
    <Stack gap="md">
      <Card withBorder>
        <Stack gap="md">
          <Group justify="space-between">
            <Group gap="xs">
              <IconBrandGithub size={20} />
              <Title order={4}>Integración con GitHub</Title>
            </Group>
            {connected ? (
              <Badge color="green" variant="light" leftSection={<IconCheck size={12} />}>
                conectado
              </Badge>
            ) : (
              <Badge color="gray" variant="light">
                sin conectar
              </Badge>
            )}
          </Group>

          {connected ? (
            <ConnectedView
              username={status.data?.username ?? null}
              scopes={status.data?.scopes ?? []}
              updatedAt={status.data?.updated_at ?? null}
              onDisconnect={handleDisconnect}
              disconnecting={disconnect.isPending}
            />
          ) : (
            <DisconnectedView
              token={token}
              setToken={setToken}
              onSave={handleSave}
              saving={save.isPending}
            />
          )}
        </Stack>
      </Card>
    </Stack>
  );
}

function DisconnectedView({
  token,
  setToken,
  onSave,
  saving,
}: {
  token: string;
  setToken: (s: string) => void;
  onSave: () => void;
  saving: boolean;
}) {
  return (
    <Stack gap="sm">
      <Alert color="blue" variant="light" icon={<IconInfoCircle size={16} />}>
        Pega un{' '}
        <Anchor
          href="https://github.com/settings/tokens"
          target="_blank"
          rel="noopener noreferrer"
        >
          Personal Access Token
        </Anchor>
        {' '}de GitHub. Para empezar, un classic PAT con scope <Code>repo</Code>
        {' '}es suficiente. Niwa lo usará para push, pull y crear repos.
      </Alert>
      <PasswordInput
        label="Token"
        placeholder="ghp_..."
        value={token}
        onChange={(e) => setToken(e.currentTarget.value)}
        autoComplete="off"
      />
      <Group justify="flex-end">
        <Button onClick={onSave} loading={saving} disabled={!token.trim()}>
          Validar y guardar
        </Button>
      </Group>
      <Text size="xs" c="dimmed">
        El token se guarda obfuscado en la base de datos local. No se envía
        a ningún servidor fuera de este host.
      </Text>
    </Stack>
  );
}

function ConnectedView({
  username,
  scopes,
  updatedAt,
  onDisconnect,
  disconnecting,
}: {
  username: string | null;
  scopes: string[];
  updatedAt: string | null;
  onDisconnect: () => void;
  disconnecting: boolean;
}) {
  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Text size="sm">Cuenta:</Text>
        <Anchor
          href={username ? `https://github.com/${username}` : '#'}
          target="_blank"
          rel="noopener noreferrer"
          size="sm"
        >
          @{username ?? 'desconocido'}
        </Anchor>
      </Group>
      <Group gap="xs" wrap="wrap">
        <Text size="sm">Scopes:</Text>
        {scopes.length === 0 ? (
          <Text size="sm" c="dimmed">
            sin scopes reportados (fine-grained PAT)
          </Text>
        ) : (
          scopes.map((s) => (
            <Badge key={s} size="sm" variant="light">
              {s}
            </Badge>
          ))
        )}
      </Group>
      {updatedAt && (
        <Text size="xs" c="dimmed">
          Actualizado: {updatedAt}
        </Text>
      )}
      <Group justify="flex-end">
        <Button
          color="red"
          variant="light"
          onClick={onDisconnect}
          loading={disconnecting}
        >
          Desconectar
        </Button>
      </Group>
    </Stack>
  );
}
