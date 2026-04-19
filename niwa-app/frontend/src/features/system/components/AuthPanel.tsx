import { useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Collapse,
  Group,
  Loader,
  PasswordInput,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconCheck,
  IconChevronDown,
  IconChevronUp,
  IconX,
} from '@tabler/icons-react';
import {
  useApplyClaudeSetupToken,
  useReadiness,
} from '../../../shared/api/queries';
import type { Readiness, ReadinessBackend } from '../../../shared/types';

const CLAUDE_SLUG = 'claude_code';

function findClaudeBackend(r: Readiness | undefined): ReadinessBackend | null {
  if (!r) return null;
  return r.backends.find((b) => b.slug === CLAUDE_SLUG) ?? null;
}

function statusBadge(backend: ReadinessBackend | null) {
  if (!backend || !backend.has_credential) {
    return (
      <Badge color="red" leftSection={<IconX size={12} />}>
        No autenticado
      </Badge>
    );
  }
  if (backend.auth_mode === 'setup_token') {
    return (
      <Badge color="teal" leftSection={<IconCheck size={12} />}>
        Autenticado vía suscripción
      </Badge>
    );
  }
  // API key or OAuth: still a valid credential, but surfaced as secondary.
  return (
    <Badge color="blue" leftSection={<IconCheck size={12} />}>
      Autenticado ({backend.auth_mode})
    </Badge>
  );
}

export function AuthPanel() {
  const { data, isLoading, isError, error } = useReadiness();
  const apply = useApplyClaudeSetupToken();
  const [token, setToken] = useState('');
  const [showApiKeyHint, setShowApiKeyHint] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  if (isLoading) {
    return (
      <Card withBorder>
        <Group gap="sm">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Cargando estado de autenticación…
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

  const backend = findClaudeBackend(data);
  const authed = !!backend?.has_credential;
  const viaSubscription =
    authed && backend?.auth_mode === 'setup_token';

  const handleApply = async () => {
    setErrorMsg(null);
    setSuccessMsg(null);
    const trimmed = token.trim();
    if (!trimmed) {
      setErrorMsg('Pega un setup-token antes de aplicar.');
      return;
    }
    try {
      const result = await apply.mutateAsync(trimmed);
      if (result.ok) {
        setSuccessMsg(
          result.message ||
            'Token aplicado. El executor lo usará como CLAUDE_CODE_OAUTH_TOKEN.',
        );
        setToken('');
      } else {
        setErrorMsg(result.error || 'No se pudo guardar el token.');
      }
    } catch (e) {
      setErrorMsg(
        e instanceof Error ? e.message : 'Error aplicando el token.',
      );
    }
  };

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={5}>Claude (suscripción)</Title>
          {statusBadge(backend)}
        </Group>

        <Text size="sm" c="dimmed">
          Pega el token que te da <code>claude setup-token</code> en tu
          laptop para que Niwa ejecute tareas contra tu suscripción
          Claude Pro/Max. El token se guarda y el executor lo usa como{' '}
          <code>CLAUDE_CODE_OAUTH_TOKEN</code>.
        </Text>

        {viaSubscription && (
          <Alert color="teal" variant="light" icon={<IconCheck size={16} />}>
            Niwa está autenticado vía tu suscripción Claude. Pega un
            token nuevo solo si quieres rotarlo o si Claude empieza a
            fallar con 401.
          </Alert>
        )}

        <PasswordInput
          label="Setup Token"
          description="Formato: sk-ant-oat01-... (obtén uno con 'claude setup-token' en tu laptop)"
          placeholder="sk-ant-oat01-..."
          value={token}
          onChange={(e) => setToken(e.currentTarget.value)}
          autoComplete="off"
        />

        {errorMsg && (
          <Alert color="red" variant="light" icon={<IconX size={16} />}>
            {errorMsg}
          </Alert>
        )}
        {successMsg && (
          <Alert color="teal" variant="light" icon={<IconCheck size={16} />}>
            {successMsg}
          </Alert>
        )}

        <Group gap="xs">
          <Button
            size="xs"
            onClick={handleApply}
            loading={apply.isPending}
            disabled={apply.isPending}
          >
            Aplicar token
          </Button>
        </Group>

        <UnstyledButton onClick={() => setShowApiKeyHint((v) => !v)}>
          <Group gap={4}>
            <Text size="xs" c="dimmed">
              ¿Solo tienes API key?
            </Text>
            {showApiKeyHint ? (
              <IconChevronUp size={14} />
            ) : (
              <IconChevronDown size={14} />
            )}
          </Group>
        </UnstyledButton>
        <Collapse in={showApiKeyHint}>
          <Text size="xs" c="dimmed">
            Ve a la pestaña <Anchor component="span">Servicios</Anchor> →
            Anthropic, cambia el método de autenticación a &quot;API
            Key&quot; y pega la key. La suscripción es el camino
            recomendado porque no gasta tokens por uso.
          </Text>
        </Collapse>
      </Stack>
    </Card>
  );
}
