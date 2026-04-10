import { useState } from 'react';
import {
  Card,
  TextInput,
  PasswordInput,
  Button,
  Title,
  Text,
  Stack,
  Alert,
  Center,
  Box,
} from '@mantine/core';
import { IconAlertCircle } from '@tabler/icons-react';
import { login } from '../api/client';

interface Props {
  onSuccess: () => void;
}

export function LoginPage({ onSuccess }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const ok = await login(username, password);
      if (ok) {
        onSuccess();
      } else {
        setError('Usuario o contraseña incorrectos.');
      }
    } catch {
      setError('Error de conexión. Intenta de nuevo.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Center h="100vh" bg="dark.9">
      <Card
        shadow="xl"
        p="xl"
        radius="lg"
        w={420}
        withBorder
        style={{ borderColor: 'var(--mantine-color-dark-5)' }}
      >
        <Stack gap="xs" mb="lg">
          <Title order={2} fw={800}>
            Niwa
          </Title>
          <Text size="sm" c="dimmed">
            Acceso protegido. Inicia sesión para abrir Niwa.
          </Text>
        </Stack>

        {error && (
          <Alert
            icon={<IconAlertCircle size={16} />}
            color="red"
            mb="md"
            variant="light"
          >
            {error}
          </Alert>
        )}

        <Box component="form" onSubmit={handleSubmit}>
          <Stack gap="sm">
            <TextInput
              label="Usuario"
              value={username}
              onChange={(e) => setUsername(e.currentTarget.value)}
              autoComplete="username"
              required
            />
            <PasswordInput
              label="Contraseña"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              autoComplete="current-password"
              required
            />
            <Button type="submit" fullWidth mt="xs" loading={loading}>
              Entrar
            </Button>
          </Stack>
        </Box>

        <Text size="xs" c="dimmed" mt="md" ta="center">
          Contacta al administrador si necesitas credenciales.
        </Text>
      </Card>
    </Center>
  );
}
