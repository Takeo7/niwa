// FIX-20260420: banner for tasks in ``waiting_input``.
//
// Replaces the read-only yellow alert that used to tell the user to
// "edit the task and relaunch". The new banner exposes a real
// conversational round-trip: the user reads Claude's question, types
// an answer, and presses "Reenviar con tu respuesta" — the backend
// creates a ``relation_type='resume'`` run that continues the
// original Claude session with the followup spliced in.

import { useState } from 'react';
import {
  Alert,
  Stack,
  Text,
  Paper,
  Textarea,
  Button,
  Group,
} from '@mantine/core';
import { IconHelp, IconSend } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import type { Task } from '../../../shared/types';
import { useRespondTask } from '../hooks/useTasks';

interface Props {
  task: Task;
}

export function WaitingInputBanner({ task }: Props) {
  const respondTask = useRespondTask();
  const [message, setMessage] = useState('');

  const lastRun = task.last_run ?? null;
  // Prefer the canonical ``result_text`` surfaced via
  // ``task.executor_output`` (what the adapter stored after the
  // clarification branch). Fall back to the run's error_code /
  // outcome if the output was somehow lost so the banner never
  // renders empty.
  const claudeQuestion =
    task.executor_output?.trim()
    || lastRun?.error_code
    || 'Claude respondió sin ejecutar ninguna acción.';

  const trimmed = message.trim();
  const canSubmit = trimmed.length > 0 && !respondTask.isPending;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      await respondTask.mutateAsync({ id: task.id, message: trimmed });
      setMessage('');
      notifications.show({
        title: 'Respuesta enviada',
        message: 'El executor la recogerá en el próximo ciclo.',
        color: 'green',
      });
    } catch (err) {
      notifications.show({
        title: 'No se pudo enviar la respuesta',
        message: err instanceof Error ? err.message : 'Fallo desconocido',
        color: 'red',
      });
    }
  };

  return (
    <Alert
      variant="light"
      color="yellow"
      icon={<IconHelp size={18} />}
      title="Claude necesita más información"
    >
      <Stack gap="xs">
        <Text size="sm">
          Responde con los detalles que te pide y Claude retomará la
          tarea desde donde la dejó.
        </Text>
        <Paper
          p="sm"
          radius="sm"
          withBorder
          bg="yellow.0"
          aria-label="Pregunta de Claude"
        >
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {claudeQuestion}
          </Text>
        </Paper>
        <Textarea
          autosize
          minRows={2}
          maxRows={8}
          placeholder="Escribe tu respuesta para Claude…"
          value={message}
          onChange={(event) => setMessage(event.currentTarget.value)}
          disabled={respondTask.isPending}
          aria-label="Respuesta para Claude"
        />
        <Group justify="flex-end" gap="xs">
          <Button
            size="xs"
            variant="filled"
            color="yellow"
            leftSection={<IconSend size={14} />}
            onClick={handleSubmit}
            loading={respondTask.isPending}
            disabled={!canSubmit}
          >
            Reenviar con tu respuesta
          </Button>
        </Group>
      </Stack>
    </Alert>
  );
}
