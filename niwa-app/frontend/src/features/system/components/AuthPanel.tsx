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
  IconBrandOpenai,
  IconCheck,
  IconChevronDown,
  IconChevronUp,
  IconX,
} from '@tabler/icons-react';
import {
  useApplyClaudeSetupToken,
  useOAuthStatus,
  useReadiness,
  useRevokeOAuth,
  useStartOAuth,
} from '../../../shared/api/queries';
import type { Readiness, ReadinessBackend } from '../../../shared/types';

const CLAUDE_SLUG = 'claude_code';

function findClaudeBackend(r: Readiness | undefined): ReadinessBackend | null {
  if (!r) return null;
  return r.backends.find((b) => b.slug === CLAUDE_SLUG) ?? null;
}

function statusBadge(backend: ReadinessBackend | null) {
  // FIX-20260419 (Bug 33): when the backend ships a live probe, let
  // it drive the badge — it knows if credentials actually work, not
  // just if they are configured. Fall back to the static signal for
  // older backends (and for tests that don't include claude_probe).
  const probe = backend?.claude_probe;
  if (probe) {
    if (probe.status === 'ok') {
      return (
        <Badge color="teal" leftSection={<IconCheck size={12} />}>
          Vía suscripción · activa
        </Badge>
      );
    }
    if (probe.status === 'credential_expired') {
      return (
        <Badge color="red" leftSection={<IconAlertTriangle size={12} />}>
          Credenciales caducadas
        </Badge>
      );
    }
    if (probe.status === 'credential_missing') {
      return (
        <Badge color="red" leftSection={<IconX size={12} />}>
          Sin credenciales
        </Badge>
      );
    }
    if (probe.status === 'no_cli') {
      return (
        <Badge color="yellow" leftSection={<IconAlertTriangle size={12} />}>
          CLI no encontrado
        </Badge>
      );
    }
    // ``error`` / ``credential_error`` fall through to the static
    // badge below so the user still sees something sensible.
  }

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
    <Stack gap="md">
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

      <OpenAIAuthSection />
    </Stack>
  );
}

function OpenAIAuthSection() {
  const { data: status, refetch } = useOAuthStatus('openai');
  const startOAuth = useStartOAuth();
  const revokeOAuth = useRevokeOAuth();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const authenticated = !!status?.authenticated;

  const handleConnect = async () => {
    setErrorMsg(null);
    try {
      const result = await startOAuth.mutateAsync('openai');
      if (result.error) {
        setErrorMsg(result.error);
        return;
      }
      if (!result.auth_url) {
        setErrorMsg(
          'El backend no devolvió una URL de autorización. Revisa los logs.',
        );
        return;
      }
      // Poll status until the popup completes the flow (max 2 min).
      const interval = window.setInterval(() => {
        refetch().then((r) => {
          if (r.data?.authenticated) {
            window.clearInterval(interval);
          }
        });
      }, 3000);
      window.setTimeout(() => window.clearInterval(interval), 120000);
    } catch (e) {
      setErrorMsg(
        e instanceof Error ? e.message : 'Error iniciando sesión con ChatGPT.',
      );
    }
  };

  const handleRevoke = async () => {
    setErrorMsg(null);
    try {
      await revokeOAuth.mutateAsync('openai');
      await refetch();
    } catch (e) {
      setErrorMsg(
        e instanceof Error ? e.message : 'Error al desconectar ChatGPT.',
      );
    }
  };

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={5}>ChatGPT (suscripción)</Title>
          {authenticated ? (
            <Badge color="teal" leftSection={<IconCheck size={12} />}>
              Conectado
            </Badge>
          ) : (
            <Badge color="red" leftSection={<IconX size={12} />}>
              No conectado
            </Badge>
          )}
        </Group>

        <Text size="sm" c="dimmed">
          Conecta tu suscripción ChatGPT Plus/Pro para que Codex ejecute
          tareas contra tu cuenta. Niwa abre una ventana con el login de
          OpenAI y guarda los tokens para refrescarlos automáticamente.
        </Text>

        {authenticated && status?.email && (
          <Text size="sm">
            Conectado como <code>{status.email}</code>.
          </Text>
        )}

        {errorMsg && (
          <Alert color="red" variant="light" icon={<IconX size={16} />}>
            {errorMsg}
          </Alert>
        )}

        <Group gap="xs">
          {authenticated ? (
            <Button
              size="xs"
              color="red"
              variant="light"
              onClick={handleRevoke}
              loading={revokeOAuth.isPending}
              disabled={revokeOAuth.isPending}
            >
              Desconectar
            </Button>
          ) : (
            <Button
              size="xs"
              leftSection={<IconBrandOpenai size={14} />}
              onClick={handleConnect}
              loading={startOAuth.isPending}
              disabled={startOAuth.isPending}
            >
              Conectar con ChatGPT
            </Button>
          )}
        </Group>

        {!authenticated && (
          <Text size="xs" c="dimmed">
            Si no se abre la ventana de OpenAI, tu navegador puede haber
            bloqueado el popup. Permite popups para este dominio e
            inténtalo de nuevo.
          </Text>
        )}
      </Stack>
    </Card>
  );
}
