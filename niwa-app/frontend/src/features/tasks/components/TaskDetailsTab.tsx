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
} from '@tabler/icons-react';
import {
  useUpdateTask,
  useDeleteTask,
  useTaskAttachments,
  useUploadTaskAttachment,
  useDeleteTaskAttachment,
  useRejectTask,
  useTaskLabels,
  useAddTaskLabel,
  useRemoveTaskLabel,
} from '../hooks/useTasks';
import { notifications } from '@mantine/notifications';
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
  const { data: attachments } = useTaskAttachments(task.id);
  const uploadAttachment = useUploadTaskAttachment();
  const deleteAttachment = useDeleteTaskAttachment();
  const rejectTask = useRejectTask();
  const { data: labelsData } = useTaskLabels(task.id);
  const addTaskLabel = useAddTaskLabel();
  const removeTaskLabel = useRemoveTaskLabel();
  const [newLabel, setNewLabel] = useState('');

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

  return (
    <Stack gap="md">
      {task.description && (
        <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
          {task.description}
        </Text>
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
    </Stack>
  );
}
