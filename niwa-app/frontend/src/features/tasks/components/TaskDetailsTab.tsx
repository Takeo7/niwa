import { useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import {
  Stack,
  Group,
  Text,
  Badge,
  Select,
  Button,
  Divider,
  TextInput,
  ActionIcon,
  Paper,
  Alert,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import {
  IconTrash,
  IconUpload,
  IconFile,
  IconDownload,
  IconX,
  IconPlus,
  IconPlayerStop,
  IconAlertTriangle,
} from '@tabler/icons-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  useUpdateTask,
  useDeleteTask,
  useRetryTask,
  useTaskAttachments,
  useUploadTaskAttachment,
  useDeleteTaskAttachment,
  useRejectTask,
  useTaskLabels,
  useAddTaskLabel,
  useRemoveTaskLabel,
} from '../hooks/useTasks';
import { notifications } from '@mantine/notifications';
import { TaskForm } from './TaskForm';
import type { Task } from '../../../shared/types';

const STATUS_OPTIONS = [
  { value: 'pendiente', label: 'Pendiente' },
  { value: 'en_progreso', label: 'En Progreso' },
  { value: 'bloqueada', label: 'Bloqueada' },
  { value: 'revision', label: 'Revisión' },
  { value: 'waiting_input', label: 'Esperando input' },
  { value: 'hecha', label: 'Hecha' },
  { value: 'archivada', label: 'Archivada' },
];

const PRIORITY_OPTIONS = [
  { value: 'baja', label: 'Baja' },
  { value: 'media', label: 'Media' },
  { value: 'alta', label: 'Alta' },
  { value: 'critica', label: 'Crítica' },
];

export function TaskDetailsTab() {
  const { task } = useOutletContext<{ task: Task }>();
  const navigate = useNavigate();
  const updateTask = useUpdateTask();
  const deleteTask = useDeleteTask();
  const retryTask = useRetryTask();
  const { data: attachments } = useTaskAttachments(task.id);
  const uploadAttachment = useUploadTaskAttachment();
  const deleteAttachment = useDeleteTaskAttachment();
  const rejectTask = useRejectTask();
  const { data: labelsData } = useTaskLabels(task.id);
  const addTaskLabel = useAddTaskLabel();
  const removeTaskLabel = useRemoveTaskLabel();
  const [newLabel, setNewLabel] = useState('');
  const [replyFormOpen, setReplyFormOpen] = useState(false);

  const handleStatusChange = (status: string | null) => {
    if (!status) return;
    updateTask.mutate({ id: task.id, status });
  };

  const handlePriorityChange = (priority: string | null) => {
    if (!priority) return;
    updateTask.mutate({ id: task.id, priority });
  };

  const handleDelete = async () => {
    await deleteTask.mutateAsync(task.id);
    notifications.show({
      title: 'Tarea eliminada',
      message: `"${task.title}" ha sido eliminada`,
      color: 'red',
    });
    navigate('/tasks');
  };

  const handleReject = async () => {
    const reason = window.prompt('Razón del rechazo:');
    if (reason === null) return;
    await rejectTask.mutateAsync({ id: task.id, reason: reason || '' });
    notifications.show({
      title: 'Tarea rechazada',
      message: `"${task.title}" ha sido rechazada`,
      color: 'orange',
    });
  };

  const labels = labelsData ?? [];

  const addLabel = () => {
    if (!newLabel.trim()) return;
    addTaskLabel.mutate({ taskId: task.id, label: newLabel.trim() });
    setNewLabel('');
  };

  const removeLabel = (label: string) => {
    removeTaskLabel.mutate({ taskId: task.id, label });
  };

  const handleUpload = (files: File[]) => {
    for (const file of files) {
      uploadAttachment.mutate({ taskId: task.id, file });
    }
  };

  const handleDeleteAttachment = (filename: string) => {
    deleteAttachment.mutate({ taskId: task.id, filename });
  };

  // PR-39: show a red banner when the latest run failed, except on
  // terminal states — 'hecha' means a fallback rescued it, 'archivada'
  // means the user moved past it. Alarming on those is misleading or
  // noisy. Blocked/waiting tasks DO benefit from the banner (the
  // failure is often exactly why they're blocked).
  const lastRun = task.last_run ?? null;
  const terminalStatuses = new Set(['hecha', 'archivada']);
  const showFailureBanner =
    lastRun !== null
    && (lastRun.outcome === 'failure' || Boolean(lastRun.error_code))
    && !terminalStatuses.has(task.status);

  const navigateToRuns = () => navigate(`/tasks/${task.id}/runs`);

  return (
    <Stack gap="md">
      {showFailureBanner && lastRun && (
        <Alert
          variant="light"
          color="red"
          icon={<IconAlertTriangle size={18} />}
          title="La última ejecución falló"
        >
          <Stack gap={4}>
            <Text size="sm">
              {lastRun.backend_profile_display_name
                ? `${lastRun.backend_profile_display_name} falló con`
                : 'Falló con'}
              {' '}
              <Text span fw={600} c="red">
                {lastRun.error_code ?? lastRun.outcome ?? 'error desconocido'}
              </Text>
              {lastRun.relation_type === 'fallback' && ' (intento de fallback)'}
              .
            </Text>
            <Group gap="xs">
              <Button
                size="xs"
                variant="light"
                color="red"
                onClick={navigateToRuns}
              >
                Ver runs
              </Button>
              <Button
                size="xs"
                variant="filled"
                color="red"
                loading={retryTask.isPending}
                onClick={async () => {
                  try {
                    await retryTask.mutateAsync(task.id);
                    notifications.show({
                      title: 'Tarea reencolada',
                      message: 'El executor la recogerá en el próximo ciclo.',
                      color: 'green',
                    });
                  } catch (err) {
                    notifications.show({
                      title: 'Error al reintentar',
                      message:
                        err instanceof Error ? err.message : 'Fallo desconocido',
                      color: 'red',
                    });
                  }
                }}
              >
                Reintentar
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}

      {task.description && (
        <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
          {task.description}
        </Text>
      )}

      {task.executor_output && (
        <>
          <Divider />
          <Text size="sm" fw={500}>Resultado</Text>
          <Paper p="sm" radius="sm" withBorder>
            <div style={{ fontSize: 'var(--mantine-font-size-sm)' }}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ node: _node, ...props }) => (
                    <a {...props} target="_blank" rel="noopener noreferrer" />
                  ),
                }}
              >
                {task.executor_output}
              </ReactMarkdown>
            </div>
          </Paper>
        </>
      )}

      <Group grow>
        <Select
          label="Estado"
          data={STATUS_OPTIONS}
          value={task.status}
          onChange={handleStatusChange}
        />
        <Select
          label="Prioridad"
          data={PRIORITY_OPTIONS}
          value={task.priority}
          onChange={handlePriorityChange}
        />
      </Group>

      {/* Pipeline phase */}
      {task.agent_status && (
        <Paper p="xs" radius="sm" withBorder>
          <Group gap="xs">
            <Text size="sm" fw={500}>Fase:</Text>
            <Badge
              color={
                task.agent_status === 'running' ? 'cyan' :
                task.agent_status === 'completed' ? 'green' :
                task.agent_status === 'failed' ? 'red' : 'gray'
              }
            >
              {task.agent_status}
            </Badge>
            {task.agent_name && (
              <Text size="xs" c="dimmed">Agente: {task.agent_name}</Text>
            )}
          </Group>
        </Paper>
      )}

      <Group gap="xs">
        <Text size="xs" c="dimmed">
          Creada: {new Date(task.created_at).toLocaleString('es-ES')}
        </Text>
        <Text size="xs" c="dimmed">
          Actualizada: {new Date(task.updated_at).toLocaleString('es-ES')}
        </Text>
      </Group>

      {task.due_at && (
        <Text size="sm">
          Fecha límite:{' '}
          {new Date(task.due_at).toLocaleDateString('es-ES')}
        </Text>
      )}

      {task.notes && (
        <>
          <Divider />
          <Text size="sm" fw={500}>Notas</Text>
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {task.notes}
          </Text>
        </>
      )}

      {/* Labels */}
      <Divider />
      <Stack gap="xs">
        <Text size="sm" fw={500}>Etiquetas</Text>
        <Group gap={4}>
          {labels.map((label) => (
            <Badge
              key={label}
              variant="light"
              rightSection={
                <ActionIcon
                  size="xs"
                  variant="transparent"
                  onClick={() => removeLabel(label)}
                >
                  <IconX size={10} />
                </ActionIcon>
              }
            >
              {label}
            </Badge>
          ))}
          <Group gap={4}>
            <TextInput
              size="xs"
              placeholder="Nueva etiqueta"
              value={newLabel}
              onChange={(e) => setNewLabel(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') addLabel(); }}
              w={120}
            />
            <ActionIcon
              size="sm"
              variant="light"
              onClick={addLabel}
              disabled={!newLabel.trim()}
            >
              <IconPlus size={14} />
            </ActionIcon>
          </Group>
        </Group>
      </Stack>

      {/* Attachments */}
      <Divider />
      <Text size="sm" fw={500}>Adjuntos</Text>
      <Dropzone
        onDrop={handleUpload}
        loading={uploadAttachment.isPending}
        maxSize={10 * 1024 * 1024}
      >
        <Group justify="center" gap="xs" p="xs" style={{ pointerEvents: 'none' }}>
          <IconUpload size={20} />
          <Text size="sm" c="dimmed">
            Arrastra archivos o haz clic para subir
          </Text>
        </Group>
      </Dropzone>
      {attachments && attachments.length > 0 && (
        <Stack gap={4}>
          {attachments.map((att) => (
            <Paper key={att.filename} p="xs" radius="sm" withBorder>
              <Group justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
                  <IconFile size={16} />
                  <Text size="sm" lineClamp={1}>{att.filename}</Text>
                </Group>
                <Group gap={4} wrap="nowrap">
                  <ActionIcon
                    size="sm"
                    variant="light"
                    component="a"
                    href={`/api/tasks/${task.id}/attachments/${encodeURIComponent(att.filename)}`}
                    target="_blank"
                  >
                    <IconDownload size={14} />
                  </ActionIcon>
                  <ActionIcon
                    size="sm"
                    variant="light"
                    color="red"
                    onClick={() => handleDeleteAttachment(att.filename)}
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Group>
              </Group>
            </Paper>
          ))}
        </Stack>
      )}

      <Divider />
      <Group justify="flex-end">
        {(task.status === 'waiting_input' || task.status === 'hecha' || Boolean(task.executor_output)) && (
          <Button
            variant="light"
            leftSection={<IconPlus size={16} />}
            onClick={() => setReplyFormOpen(true)}
          >
            Responder
          </Button>
        )}
        {(task.status === 'en_progreso' || task.status === 'hecha') && (
          <Button
            color="orange"
            variant="light"
            leftSection={<IconPlayerStop size={16} />}
            onClick={handleReject}
            loading={rejectTask.isPending}
          >
            Rechazar
          </Button>
        )}
        <Button
          color="red"
          variant="light"
          leftSection={<IconTrash size={16} />}
          onClick={handleDelete}
          loading={deleteTask.isPending}
        >
          Eliminar tarea
        </Button>
      </Group>

      <TaskForm
        opened={replyFormOpen}
        onClose={() => setReplyFormOpen(false)}
        initialParentTaskId={task.id}
        initialProjectId={task.project_id ?? null}
        initialTitle={`Responder: ${task.title}`}
        initialDescription={
          task.executor_output
            ? `Respuesta al run anterior.\n\n---\nContexto (output de la tarea "${task.title}"):\n\n${task.executor_output.slice(0, 500)}\n---\n\nTu respuesta:\n`
            : `Respuesta a la tarea "${task.title}".\n\n`
        }
      />
    </Stack>
  );
}
