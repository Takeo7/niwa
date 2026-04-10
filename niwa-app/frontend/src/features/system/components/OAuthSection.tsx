import { useState } from 'react';
import {
  Stack,
  Text,
  Button,
  Group,
  Badge,
  Textarea,
  Alert,
  Paper,
} from '@mantine/core';
import { IconBrandOpenai, IconAlertCircle } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import {
  useOAuthStatus,
  useStartOAuth,
  useRevokeOAuth,
  useImportOAuth,
} from '../hooks/useServices';

interface Props {
  provider: string;
}

export function OAuthSection({ provider }: Props) {
  const { data: status, refetch } = useOAuthStatus(provider);
  const startOAuth = useStartOAuth();
  const revokeOAuth = useRevokeOAuth();
  const importOAuth = useImportOAuth();
  const [authJson, setAuthJson] = useState('');
  const [showImport, setShowImport] = useState(false);

  const handleStart = () => {
    startOAuth.mutate(provider);
    // Poll for status after opening window
    const interval = setInterval(() => {
      refetch().then((result) => {
        if (result.data?.authenticated) {
          clearInterval(interval);
          notifications.show({
            title: 'OAuth conectado',
            message: `Autenticación con ${provider} exitosa`,
            color: 'green',
          });
        }
      });
    }, 3000);
    setTimeout(() => clearInterval(interval), 120000);
  };

  const handleRevoke = async () => {
    await revokeOAuth.mutateAsync(provider);
    refetch();
    notifications.show({
      title: 'OAuth revocado',
      message: 'Tokens eliminados',
      color: 'yellow',
    });
  };

  const handleImport = async () => {
    if (!authJson.trim()) return;
    try {
      await importOAuth.mutateAsync({ provider, auth_json: authJson });
      setAuthJson('');
      setShowImport(false);
      refetch();
      notifications.show({
        title: 'Tokens importados',
        message: 'Autenticación exitosa',
        color: 'green',
      });
    } catch (e) {
      notifications.show({
        title: 'Error',
        message: e instanceof Error ? e.message : 'Error importando tokens',
        color: 'red',
      });
    }
  };

  return (
    <Paper p="md" radius="md" withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Group gap="xs">
            <IconBrandOpenai size={20} />
            <Text fw={500}>Suscripción {provider}</Text>
          </Group>
          {status?.authenticated ? (
            <Badge color="green">Conectado</Badge>
          ) : (
            <Badge color="gray">No conectado</Badge>
          )}
        </Group>

        {status?.authenticated && status.email && (
          <Text size="sm" c="dimmed">
            Cuenta: {status.email}
          </Text>
        )}

        <Group gap="xs">
          {!status?.authenticated ? (
            <>
              <Button
                size="xs"
                onClick={handleStart}
                leftSection={<IconBrandOpenai size={16} />}
              >
                Iniciar sesión con {provider}
              </Button>
              <Button
                size="xs"
                variant="light"
                onClick={() => setShowImport(!showImport)}
              >
                Importar JSON
              </Button>
            </>
          ) : (
            <Button
              size="xs"
              color="red"
              variant="light"
              onClick={handleRevoke}
              loading={revokeOAuth.isPending}
            >
              Revocar
            </Button>
          )}
        </Group>

        {showImport && (
          <Stack gap="xs">
            <Alert
              icon={<IconAlertCircle size={16} />}
              color="blue"
              variant="light"
            >
              Pega el contenido de tu archivo auth.json de OpenAI
            </Alert>
            <Textarea
              placeholder='{"tokens": {"access_token": "...", ...}}'
              value={authJson}
              onChange={(e) => setAuthJson(e.currentTarget.value)}
              minRows={3}
            />
            <Group gap="xs">
              <Button
                size="xs"
                onClick={handleImport}
                loading={importOAuth.isPending}
                disabled={!authJson.trim()}
              >
                Importar
              </Button>
              <Button
                size="xs"
                variant="subtle"
                onClick={() => setShowImport(false)}
              >
                Cancelar
              </Button>
            </Group>
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
