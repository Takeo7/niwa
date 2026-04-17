import {
  Card,
  Stack,
  Group,
  Title,
  Text,
  Badge,
  Button,
  Code,
  Alert,
  Loader,
  CopyButton,
  ActionIcon,
  Tooltip,
  Divider,
} from '@mantine/core';
import {
  IconRefresh,
  IconAlertTriangle,
  IconCheck,
  IconCopy,
  IconArrowBackUp,
  IconInfoCircle,
  IconTerminal,
} from '@tabler/icons-react';
import { useVersion } from '../../../shared/api/queries';

/** POSIX shell quoting (PR final 3).
 *
 * Paths that contain spaces, quotes, or other metacharacters break
 * copy-paste if they aren't wrapped. This is the classic
 * "single-quote everything" escape: wrap in `'…'` and replace any
 * literal `'` with `'\\''`. Idempotent enough for the only case we
 * care about (last_backup_path). Not a general-purpose sanitiser —
 * we control both producer and consumer. */
export function shellQuote(s: string): string {
  if (s === '') return "''";
  if (/^[A-Za-z0-9_\-./:=@%+]+$/.test(s)) return s;
  return "'" + s.replace(/'/g, "'\\''") + "'";
}

/** PR-61: honest update dashboard.
 *
 * The UI does NOT execute the update (PR-58a decision — container
 * can't reach Docker socket or systemd safely). This panel surfaces
 * the state the operator needs to decide + runs the CLI command on
 * the host:
 *
 *   - current branch + commit + schema version,
 *   - latest remote commit (best-effort),
 *   - repo dirty flag,
 *   - last backup path + time,
 *   - last update result (success / reverted / failed) from the log.
 */
export function UpdatePanel() {
  const { data: v, isLoading, refetch, isFetching } = useVersion();

  if (isLoading || !v) {
    return (
      <Card withBorder>
        <Loader size="sm" />
      </Card>
    );
  }

  const needsUpdate = Boolean(v.needs_update);
  const repoDirty = Boolean(v.repo_dirty);
  const updateCmd = (v.update_command as string | undefined) || 'niwa update';
  const restoreCmdPrefix =
    (v.restore_command as string | undefined) || 'niwa restore --from=';
  const restoreSuggestion = v.last_backup_path
    ? `${restoreCmdPrefix}${shellQuote(v.last_backup_path)}`
    : `${restoreCmdPrefix}<path>`;
  const lastUpdate = (v as {
    last_update?: {
      timestamp?: string;
      success?: boolean;
      reverted?: boolean | null;
      branch?: string | null;
      before_commit?: string | null;
      after_commit?: string | null;
      backup_path?: string | null;
      errors?: string[];
      warnings?: string[];
      duration_seconds?: number;
    } | null;
  }).last_update ?? null;

  return (
    <Stack gap="md">
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Title order={4}>Estado del sistema</Title>
            <Button
              variant="subtle"
              size="compact-sm"
              leftSection={<IconRefresh size={14} />}
              onClick={() => refetch()}
              loading={isFetching}
            >
              Refrescar
            </Button>
          </Group>

          <Group gap="xs" wrap="wrap">
            <Badge variant="light" size="sm">
              versión {v.version}
            </Badge>
            {v.branch && (
              <Badge variant="light" color="blue" size="sm">
                rama {v.branch}
              </Badge>
            )}
            {v.commit_short && (
              <Badge variant="light" color="gray" size="sm">
                commit {v.commit_short}
              </Badge>
            )}
            {typeof v.schema_version === 'number' && (
              <Badge variant="light" color="grape" size="sm">
                schema {v.schema_version}
              </Badge>
            )}
          </Group>

          {repoDirty && (
            <Alert color="orange" icon={<IconAlertTriangle size={16} />}>
              El repositorio tiene cambios locales. <Code>niwa update</Code>{' '}
              abortará hasta que los resuelvas: <Code>git stash</Code>,{' '}
              <Code>git checkout .</Code> o <Code>git reset --hard</Code>.
            </Alert>
          )}

          <NeedsUpdateBanner
            needsUpdate={needsUpdate}
            branch={v.branch}
            currentShort={v.commit_short}
            latest={v.latest_remote_commit}
          />
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Title order={5}>Cómo actualizar</Title>
          <Alert color="blue" icon={<IconInfoCircle size={16} />} variant="light">
            La UI no ejecuta actualizaciones. Necesita{' '}
            <Code>docker compose build</Code> y{' '}
            <Code>systemctl restart</Code>, que solo corren en el host.
            Ejecuta el comando de abajo por SSH en el servidor.
          </Alert>
          <Group gap="xs">
            <Code style={{ flex: 1, padding: '8px 12px' }}>{updateCmd}</Code>
            <CopyButton value={updateCmd} timeout={1500}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? 'Copiado' : 'Copiar'} withArrow>
                  <ActionIcon variant="light" size="lg" onClick={copy}>
                    {copied ? (
                      <IconCheck size={16} />
                    ) : (
                      <IconCopy size={16} />
                    )}
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
          <Text size="xs" c="dimmed">
            El motor hace backup automático, aplica el update, y si el
            health-check post-update falla hace auto-revert al commit
            previo + restore de la DB (PR-58b2).
          </Text>
        </Stack>
      </Card>

      {(v.last_backup_path || v.last_backup_at) && (
        <Card withBorder>
          <Stack gap={4}>
            <Title order={5}>Último backup</Title>
            {v.last_backup_at && (
              <Text size="sm" c="dimmed">
                {new Date(v.last_backup_at).toLocaleString()}
              </Text>
            )}
            {v.last_backup_path && (
              <Code style={{ wordBreak: 'break-all' }}>
                {v.last_backup_path}
              </Code>
            )}
            <Divider my="xs" />
            <Group gap="xs">
              <Text size="xs" c="dimmed">
                Si algo fue mal:
              </Text>
              <Code style={{ flex: 1 }}>{restoreSuggestion}</Code>
              <CopyButton value={restoreSuggestion} timeout={1500}>
                {({ copied, copy }) => (
                  <Tooltip label={copied ? 'Copiado' : 'Copiar'} withArrow>
                    <ActionIcon variant="subtle" size="sm" onClick={copy}>
                      {copied ? (
                        <IconCheck size={12} />
                      ) : (
                        <IconCopy size={12} />
                      )}
                    </ActionIcon>
                  </Tooltip>
                )}
              </CopyButton>
            </Group>
          </Stack>
        </Card>
      )}

      {lastUpdate && <LastUpdateCard entry={lastUpdate} />}
    </Stack>
  );
}

function NeedsUpdateBanner({
  needsUpdate,
  branch,
  currentShort,
  latest,
}: {
  needsUpdate: boolean;
  branch?: string | null;
  currentShort?: string | null;
  latest?: string | null;
}) {
  if (!needsUpdate) {
    return (
      <Alert color="green" variant="light" icon={<IconCheck size={16} />}>
        Al día con <Code>origin/{branch ?? 'HEAD'}</Code>.
      </Alert>
    );
  }
  return (
    <Alert color="blue" icon={<IconTerminal size={16} />}>
      Hay commits nuevos en <Code>origin/{branch}</Code>.
      {' '}Tienes <Code>{currentShort ?? '?'}</Code>, remoto está en{' '}
      <Code>{(latest ?? '').slice(0, 12)}</Code>.
    </Alert>
  );
}

function LastUpdateCard({
  entry,
}: {
  entry: NonNullable<
    {
      last_update?: {
        timestamp?: string;
        success?: boolean;
        reverted?: boolean | null;
        branch?: string | null;
        before_commit?: string | null;
        after_commit?: string | null;
        backup_path?: string | null;
        errors?: string[];
        warnings?: string[];
        duration_seconds?: number;
      } | null;
    }['last_update']
  >;
}) {
  const status = entry.reverted
    ? { color: 'orange', label: 'Revertida', icon: <IconArrowBackUp size={16} /> }
    : entry.success
      ? { color: 'green', label: 'OK', icon: <IconCheck size={16} /> }
      : { color: 'red', label: 'Falló', icon: <IconAlertTriangle size={16} /> };

  return (
    <Card withBorder>
      <Stack gap="xs">
        <Group justify="space-between">
          <Title order={5}>Última actualización</Title>
          <Badge color={status.color} leftSection={status.icon}>
            {status.label}
          </Badge>
        </Group>
        <Group gap="xs" wrap="wrap">
          {entry.timestamp && (
            <Badge variant="light" size="sm">
              {entry.timestamp}
            </Badge>
          )}
          {entry.branch && (
            <Badge variant="light" color="blue" size="sm">
              {entry.branch}
            </Badge>
          )}
          {typeof entry.duration_seconds === 'number' && (
            <Badge variant="light" color="gray" size="sm">
              {entry.duration_seconds.toFixed(1)}s
            </Badge>
          )}
        </Group>
        {entry.before_commit && entry.after_commit && (
          <Text size="xs" c="dimmed">
            <Code>{entry.before_commit.slice(0, 12)}</Code>
            {' → '}
            <Code>{entry.after_commit.slice(0, 12)}</Code>
          </Text>
        )}
        {entry.backup_path && (
          <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all' }}>
            Backup: <Code>{entry.backup_path}</Code>
          </Text>
        )}
        {entry.errors && entry.errors.length > 0 && (
          <Alert color="red" icon={<IconAlertTriangle size={14} />} variant="light">
            {entry.errors.map((e, i) => (
              <Text size="xs" key={i}>
                • {e}
              </Text>
            ))}
          </Alert>
        )}
        {entry.warnings && entry.warnings.length > 0 && (
          <Alert color="yellow" variant="light">
            {entry.warnings.map((w, i) => (
              <Text size="xs" key={i}>
                • {w}
              </Text>
            ))}
          </Alert>
        )}
      </Stack>
    </Card>
  );
}
