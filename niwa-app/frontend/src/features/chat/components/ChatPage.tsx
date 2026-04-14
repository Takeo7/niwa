import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Box,
  Group,
  Select,
  Text,
  Title,
  Stack,
  Button,
  Divider,
} from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useProjects } from '../../../shared/api/queries';
import { useChat } from '../hooks/useChat';
import { MonoId } from '../../../shared/components/MonoId';

/**
 * Chat web v0.2 sobre assistant_turn — layout mínimo estilo editorial.
 *
 * Ruta: /chat
 *
 * Composición:
 *  - Header: título + selector de proyecto obligatorio + botón Nueva
 *    conversación.
 *  - (Próximos commits) MessageList con TurnView para cada turn.
 *  - (Próximos commits) MessageInput al fondo.
 *
 * Pre-selección de proyecto (DECISIONS-LOG PR-10e Dec 5):
 *  1. query param ?project=<slug>
 *  2. localStorage niwa.chat.lastProjectId (gestionado en useChat)
 *  3. sin pre-selección (placeholder)
 */
export function ChatPage() {
  const [searchParams] = useSearchParams();
  const projectParam = searchParams.get('project');
  const { data: projects, isLoading: projectsLoading } = useProjects();

  // Resolver proyecto inicial desde query param si aplica.  El hook
  // fallback-ea a localStorage si initial es null/undefined.
  const initialProjectId = useMemo(() => {
    if (!projectParam || !projects) return undefined;
    const match = projects.find(
      (p) => p.slug === projectParam || p.id === projectParam,
    );
    return match?.id ?? undefined;
  }, [projectParam, projects]);

  const {
    sessionId,
    projectId,
    setProjectId,
    turns,
    loading,
    networkError,
    send,
    newConversation,
    historyLoading,
  } = useChat(initialProjectId);

  const projectOptions = useMemo(
    () =>
      (projects ?? []).map((p) => ({
        value: p.id,
        label: p.name,
      })),
    [projects],
  );

  return (
    <Box p="md" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Group justify="space-between" align="flex-end">
        <Stack gap={2}>
          <Title order={3}>Chat</Title>
          <Group gap="xs" align="baseline">
            <Text size="xs" c="dimmed">Sesión</Text>
            <MonoId id={sessionId} chars={8} />
          </Group>
        </Stack>
        <Group gap="xs">
          <Select
            placeholder={
              projectsLoading
                ? 'Cargando proyectos…'
                : 'Elige un proyecto para empezar'
            }
            data={projectOptions}
            value={projectId}
            onChange={(v) => setProjectId(v)}
            searchable
            disabled={projectsLoading}
            style={{ minWidth: 260 }}
            aria-label="Proyecto"
          />
          <Button
            variant="default"
            size="sm"
            leftSection={<IconPlus size={14} />}
            onClick={newConversation}
          >
            Nueva conversación
          </Button>
        </Group>
      </Group>
      <Divider />
      {/* Placeholder — MessageList + MessageInput se añaden en commits
          5 y 6 de PR-10e.  Mostramos el estado mínimo para que el
          scaffold compile y sea inspeccionable. */}
      <Stack gap="xs">
        {historyLoading ? (
          <Text size="sm" c="dimmed">Cargando historial…</Text>
        ) : null}
        {!projectId ? (
          <Text size="sm" c="dimmed">
            Elige un proyecto para empezar.
          </Text>
        ) : (
          <Text size="sm" c="dimmed">
            {turns.length} turn{turns.length === 1 ? '' : 's'}
            {loading ? ' — esperando respuesta…' : ''}
          </Text>
        )}
        {networkError ? (
          <Text size="xs" c="red">
            {networkError}
          </Text>
        ) : null}
        {/* Stub send button — reemplazado en commit 6 por MessageInput. */}
        <Group gap="xs">
          <Button
            size="xs"
            variant="light"
            disabled={!projectId || loading}
            onClick={() => send('ping')}
          >
            (scaffold) send "ping"
          </Button>
        </Group>
      </Stack>
    </Box>
  );
}
