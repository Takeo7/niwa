import { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Code,
  Divider,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconAlertCircle,
  IconDeviceFloppy,
  IconRestore,
  IconShield,
} from '@tabler/icons-react';
import {
  useProjectCapabilityProfile,
  useUpdateCapabilityProfile,
} from '../../../shared/api/queries';
import { ApiError } from '../../../shared/api/client';
import type {
  CapabilityProfile,
  CapabilityProfilePatch,
  NetworkMode,
  RepoMode,
  ShellMode,
  WebMode,
} from '../../../shared/types';

interface Props {
  projectKey: string;
}

// Mirror of the canonical values in ``capability_service.py``.
// If backend adds a value, update both here and the TS union type.
const REPO_MODES: RepoMode[] = ['none', 'read-only', 'read-write'];
const SHELL_MODES: ShellMode[] = ['disabled', 'whitelist', 'free'];
const WEB_MODES: WebMode[] = ['off', 'on'];
const NETWORK_MODES: NetworkMode[] = ['off', 'on', 'restricted'];

/** CapabilitiesTab — edición del ``project_capability_profile``.
 *
 *  Si el proyecto no tiene fila persistida (is_default=true), muestra
 *  un banner y un botón que crea la fila via PUT con payload vacío
 *  (PR-05 Dec 4: el endpoint materializa desde DEFAULT).
 *
 *  Para los JSON complejos se usa ``Textarea`` monospace con
 *  validación ligera en cliente (JSON.parse). La validación de
 *  forma vive en el backend (``validate_capability_input``).
 */
export function CapabilitiesTab({ projectKey }: Props) {
  const { data, isLoading, isError } = useProjectCapabilityProfile(projectKey);
  const update = useUpdateCapabilityProfile(projectKey);

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader size="sm" />
      </Center>
    );
  }

  if (isError || !data) {
    return (
      <Alert color="red" icon={<IconAlertCircle size={16} />}>
        No se pudo cargar el perfil de capacidades.
      </Alert>
    );
  }

  return (
    <CapabilitiesTabInner
      key={`${projectKey}:${data.is_default ? 'default' : 'persisted'}`}
      projectKey={projectKey}
      isDefault={data.is_default}
      profile={data.profile}
      saving={update.isPending}
      onSave={async (patch) => {
        try {
          await update.mutateAsync(patch);
          notifications.show({
            title: 'Perfil guardado',
            message: 'Capabilities actualizadas para el proyecto.',
            color: 'green',
          });
        } catch (e) {
          const msg =
            e instanceof ApiError
              ? e.message
              : 'Error al guardar el perfil';
          notifications.show({
            title: 'No se pudo guardar',
            message: msg,
            color: 'red',
          });
        }
      }}
      onMaterialize={async () => {
        try {
          await update.mutateAsync({});
          notifications.show({
            title: 'Perfil creado',
            message: 'Fila inicializada desde los defaults.',
            color: 'green',
          });
        } catch (e) {
          const msg =
            e instanceof ApiError
              ? e.message
              : 'Error al crear el perfil';
          notifications.show({
            title: 'No se pudo crear',
            message: msg,
            color: 'red',
          });
        }
      }}
    />
  );
}

// ── Inner form ─────────────────────────────────────────────────

interface InnerProps {
  projectKey: string;
  isDefault: boolean;
  profile: CapabilityProfile;
  saving: boolean;
  onSave: (patch: CapabilityProfilePatch) => Promise<void>;
  onMaterialize: () => Promise<void>;
}

type JsonFieldKey =
  | 'shell_whitelist_json'
  | 'filesystem_scope_json'
  | 'secrets_scope_json'
  | 'resource_budget_json';

const JSON_FIELDS: { key: JsonFieldKey; label: string; hint: string }[] = [
  {
    key: 'shell_whitelist_json',
    label: 'shell_whitelist_json',
    hint: 'Array JSON de comandos base permitidos cuando shell_mode=whitelist.',
  },
  {
    key: 'filesystem_scope_json',
    label: 'filesystem_scope_json',
    hint:
      'Objeto JSON con allow y deny. El token <workspace> se resuelve ' +
      'al directorio del proyecto.',
  },
  {
    key: 'secrets_scope_json',
    label: 'secrets_scope_json',
    hint:
      'Lista allow de secretos. v0.2 persiste el campo pero la ' +
      'detección en runtime es no-op (PR-05 Dec 2).',
  },
  {
    key: 'resource_budget_json',
    label: 'resource_budget_json',
    hint:
      'max_cost_usd y max_duration_ms. Usado por el approval gate ' +
      'pre-ejecución.',
  },
];

function CapabilitiesTabInner({
  isDefault,
  profile,
  saving,
  onSave,
  onMaterialize,
}: InnerProps) {
  const [repoMode, setRepoMode] = useState<RepoMode>(profile.repo_mode);
  const [shellMode, setShellMode] = useState<ShellMode>(profile.shell_mode);
  const [webMode, setWebMode] = useState<WebMode>(profile.web_mode);
  const [networkMode, setNetworkMode] = useState<NetworkMode>(
    profile.network_mode,
  );
  const [jsonFields, setJsonFields] = useState<Record<JsonFieldKey, string>>({
    shell_whitelist_json: prettyJson(profile.shell_whitelist_json),
    filesystem_scope_json: prettyJson(profile.filesystem_scope_json),
    secrets_scope_json: prettyJson(profile.secrets_scope_json),
    resource_budget_json: prettyJson(profile.resource_budget_json),
  });

  useEffect(() => {
    setRepoMode(profile.repo_mode);
    setShellMode(profile.shell_mode);
    setWebMode(profile.web_mode);
    setNetworkMode(profile.network_mode);
    setJsonFields({
      shell_whitelist_json: prettyJson(profile.shell_whitelist_json),
      filesystem_scope_json: prettyJson(profile.filesystem_scope_json),
      secrets_scope_json: prettyJson(profile.secrets_scope_json),
      resource_budget_json: prettyJson(profile.resource_budget_json),
    });
  }, [profile]);

  const jsonErrors: Partial<Record<JsonFieldKey, string>> = {};
  for (const { key } of JSON_FIELDS) {
    const err = validateJson(jsonFields[key]);
    if (err) jsonErrors[key] = err;
  }
  const hasJsonErrors = Object.keys(jsonErrors).length > 0;

  const handleReset = () => {
    setRepoMode(profile.repo_mode);
    setShellMode(profile.shell_mode);
    setWebMode(profile.web_mode);
    setNetworkMode(profile.network_mode);
    setJsonFields({
      shell_whitelist_json: prettyJson(profile.shell_whitelist_json),
      filesystem_scope_json: prettyJson(profile.filesystem_scope_json),
      secrets_scope_json: prettyJson(profile.secrets_scope_json),
      resource_budget_json: prettyJson(profile.resource_budget_json),
    });
  };

  const handleSave = async () => {
    if (hasJsonErrors) return;
    const patch: CapabilityProfilePatch = {};
    if (repoMode !== profile.repo_mode) patch.repo_mode = repoMode;
    if (shellMode !== profile.shell_mode) patch.shell_mode = shellMode;
    if (webMode !== profile.web_mode) patch.web_mode = webMode;
    if (networkMode !== profile.network_mode)
      patch.network_mode = networkMode;
    for (const { key } of JSON_FIELDS) {
      // Compare canonicalized JSON to avoid false positives from
      // whitespace.  profile[key] may be null if DB stored null.
      const current = canonicalize(profile[key] ?? '');
      const next = canonicalize(jsonFields[key]);
      if (current !== next) patch[key] = next;
    }
    if (Object.keys(patch).length === 0) {
      notifications.show({
        title: 'Sin cambios',
        message: 'No hay diferencias respecto al estado guardado.',
        color: 'gray',
      });
      return;
    }
    await onSave(patch);
  };

  if (isDefault) {
    return (
      <Stack gap="md">
        <Alert
          color="blue"
          variant="light"
          icon={<IconShield size={16} />}
          title="Usando perfil por defecto"
        >
          <Text size="sm" mb="sm">
            Este proyecto no tiene un <code>project_capability_profile</code>{' '}
            persistido. Se aplica <code>DEFAULT_CAPABILITY_PROFILE</code> a
            los nuevos runs. Para personalizarlo, crea una fila partiendo de
            los defaults.
          </Text>
          <Button
            size="compact-sm"
            onClick={onMaterialize}
            loading={saving}
          >
            Personalizar para este proyecto
          </Button>
        </Alert>

        <Divider label="Defaults actuales" labelPosition="left" />

        <ReadOnlyPreview profile={profile} />
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={5}>Capabilities</Title>
          <Text size="xs" c="dimmed">
            Política de ejecución del proyecto. Los runs activos no
            cambian — usan el <code>capability_snapshot_json</code> de
            cuando arrancaron.
          </Text>
        </div>
        <Badge variant="light" color="green">
          Persistido
        </Badge>
      </Group>

      <Card withBorder padding="md">
        <Stack gap="sm">
          <Group grow wrap="wrap">
            <Select
              label="repo_mode"
              description="Acceso al repositorio del proyecto."
              value={repoMode}
              onChange={(v) => v && setRepoMode(v as RepoMode)}
              data={REPO_MODES.map((m) => ({ value: m, label: m }))}
              allowDeselect={false}
            />
            <Select
              label="shell_mode"
              description="Política de ejecución de comandos shell."
              value={shellMode}
              onChange={(v) => v && setShellMode(v as ShellMode)}
              data={SHELL_MODES.map((m) => ({ value: m, label: m }))}
              allowDeselect={false}
            />
          </Group>
          <Group grow wrap="wrap">
            <Select
              label="web_mode"
              description="Habilita WebFetch/WebSearch."
              value={webMode}
              onChange={(v) => v && setWebMode(v as WebMode)}
              data={WEB_MODES.map((m) => ({ value: m, label: m }))}
              allowDeselect={false}
            />
            <Select
              label="network_mode"
              description="Comandos de red (curl, ssh, etc.)."
              value={networkMode}
              onChange={(v) => v && setNetworkMode(v as NetworkMode)}
              data={NETWORK_MODES.map((m) => ({ value: m, label: m }))}
              allowDeselect={false}
            />
          </Group>
        </Stack>
      </Card>

      <Stack gap="sm">
        {JSON_FIELDS.map(({ key, label, hint }) => (
          <Textarea
            key={key}
            label={<Code>{label}</Code>}
            description={hint}
            minRows={4}
            autosize
            value={jsonFields[key]}
            onChange={(e) =>
              setJsonFields((prev) => ({
                ...prev,
                [key]: e.currentTarget.value,
              }))
            }
            error={jsonErrors[key]}
            styles={{
              input: {
                fontFamily: 'var(--mantine-font-family-monospace)',
                fontSize: 12,
                fontVariantNumeric: 'tabular-nums',
              },
            }}
          />
        ))}
      </Stack>

      {hasJsonErrors && (
        <Alert color="red" icon={<IconAlertCircle size={16} />}>
          <Text size="xs">
            Arregla los JSON inválidos antes de guardar.
          </Text>
        </Alert>
      )}

      <Group justify="flex-end" gap="xs">
        <Button
          variant="subtle"
          leftSection={<IconRestore size={14} />}
          onClick={handleReset}
          disabled={saving}
        >
          Descartar cambios
        </Button>
        <Button
          leftSection={<IconDeviceFloppy size={14} />}
          onClick={handleSave}
          loading={saving}
          disabled={hasJsonErrors}
        >
          Guardar
        </Button>
      </Group>
    </Stack>
  );
}

function ReadOnlyPreview({ profile }: { profile: CapabilityProfile }) {
  return (
    <Stack gap="xs">
      <Group gap="md" wrap="wrap">
        <FieldPreview label="repo_mode" value={profile.repo_mode} />
        <FieldPreview label="shell_mode" value={profile.shell_mode} />
        <FieldPreview label="web_mode" value={profile.web_mode} />
        <FieldPreview label="network_mode" value={profile.network_mode} />
      </Group>
      {JSON_FIELDS.map(({ key, label }) => (
        <div key={key}>
          <Text size="xs" c="dimmed" mb={2}>
            {label}
          </Text>
          <Code
            block
            style={{
              fontSize: 12,
              fontFamily: 'var(--mantine-font-family-monospace)',
              maxHeight: 200,
              overflow: 'auto',
            }}
          >
            {prettyJson(profile[key] ?? '')}
          </Code>
        </div>
      ))}
    </Stack>
  );
}

function FieldPreview({ label, value }: { label: string; value: string }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text
        size="sm"
        style={{
          fontFamily: 'var(--mantine-font-family-monospace)',
        }}
      >
        {value}
      </Text>
    </Stack>
  );
}

// ── Helpers ─────────────────────────────────────────────────────

function prettyJson(raw: string | null | undefined): string {
  if (!raw) return '';
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function canonicalize(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  try {
    return JSON.stringify(JSON.parse(trimmed));
  } catch {
    return trimmed;
  }
}

function validateJson(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return 'Valor vacío — usa al menos {} o [].';
  try {
    JSON.parse(trimmed);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : 'JSON no válido';
  }
}
