import { useState } from 'react';
import {
  Modal,
  Stack,
  Group,
  Title,
  Text,
  Badge,
  Select,
  Button,
  Divider,
  Loader,
  Center,
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
  useTask,
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

interface Props {
  taskId: string | null;
  opened: boolean;
  onClose: () => void;
}

const STATUS_OPTIONS = [
  { value: 'pendiente', label: 'Pendiente' },
  { value: 'en_progreso', label: 'En Progreso' },
  { value: 'bloqueada', label: 'Bloqueada' },
  { value: 'revision', label: 'Revisión' },
  { value: 'hecha', label: 'Hecha' },
  { value: 'archivada', label: 'Archivada' },
];

const PRIORITY_OPTIONS = [
  { value: 'baja', label: 'Baja' },
  { value: 'media', label: 'Media' },
  { value: 'alta', label: 'Alta' },
  { value: 'critica', label: 'Crítica' },
];

const PRIORITY_COLORS: Record<string, string> = {
  baja: 'blue',
  media: 'yellow',
  alta: 'orange',
  critica: 'red',
};

export function TaskDetail({ taskId, opened, onClose }: Props) {
  const { data: task, isLoading } = useTask(taskId);
  const updateTask = useUpdateTask();
  const deleteTask = useDeleteTask();
  const { data: attachments } = useTaskAttachments(taskId);
  const uploadAttachment = useUploadTaskAttachment();
  const deleteAttachment = useDeleteTaskAttachment();
  const rejectTask = useRejectTask();
  const { data: labelsData } = useTaskLabels(taskId);
  const addTaskLabel = useAddTaskLabel();
  const removeTaskLabel = useRemoveTaskLabel();
  const [newLabel, setNewLabel] = useState('');

  const handleStatusChange = (status: string | null) => {
    if (!task || !status) return;
    updateTask.mutate({ id: task.id, status });
  };

  const handlePriorityChange = (priority: string | null) => {
    if (!task || !priority) return;
    updateTask.mutate({ id: task.id, priority });
  };

  const handleDelete = async () => {
    if (!task) return;
    await deleteTask.mutateAsync(task.id);
    notifications.show({
      title: 'Tarea eliminada',
      message: `"${task.title}" ha sido eliminada`,
      color: 'red',
    });
    onClose();
  };

  const handleReject = async () => {
    if (!task) return;
    const reason = window.prompt('Razón del rechazo:');
    if (reason === null) return;
    await rejectTask.mutateAsync({ id: task.id, reason: reason || '' });
    notifications.show({
      title: 'Tarea rechazada',
      message: `"${task.title}" ha sido rechazada`,
      color: 'orange',
    });
  };

  // Labels (from task_labels API)
  const labels = labelsData ?? [];

  const addLabel = () => {
    if (!task || !newLabel.trim()) return;
    addTaskLabel.mutate({ taskId: task.id, label: newLabel.trim() });
    setNewLabel('');
  };

  const removeLabel = (label: string) => {
    if (!task) return;
    removeTaskLabel.mutate({ taskId: task.id, label });
  };

  // Attachments
  const handleUpload = (files: File[]) => {
    if (!task) return;
    for (const file of files) {
      uploadAttachment.mutate({ taskId: task.id, file });
    }
  };

  const handleDeleteAttachment = (filename: string) => {
    if (!task) return;
    deleteAttachment.mutate({ taskId: task.id, filename });
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Detalle de tarea"
      size="lg"
    >
      {isLoading ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : !task ? (
        <Text c="dimmed" ta="center" py="xl">
          Tarea no encontrada
        </Text>
      ) : (
        <Stack gap="md">
          <Title order={4}>{task.title}</Title>

          {task.description && (
            <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
              {task.description}
            </Text>
          )}

          <Group gap="xs">
            <Badge color={PRIORITY_COLORS[task.priority] || 'gray'}>
              {task.priority}
            </Badge>
            {task.project_name && (
              <Badge variant="outline">{task.project_name}</Badge>
            )}
            {task.urgent === 1 && <Badge color="red">Urgente</Badge>}
            {task.area && (
              <Badge variant="dot">{task.area}</Badge>
            )}
          </Group>

          {/* Labels */}
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
                <ActionIcon size="sm" variant="light" onClick={addLabel} disabled={!newLabel.trim()}>
                  <IconPlus size={14} />
                </ActionIcon>
              </Group>
            </Group>
          </Stack>

          <Divider />

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
      )}
    </Modal>
  );
}
