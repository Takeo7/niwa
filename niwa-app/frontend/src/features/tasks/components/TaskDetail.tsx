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
} from '@mantine/core';
import { IconTrash } from '@tabler/icons-react';
import { useTask, useUpdateTask, useDeleteTask } from '../hooks/useTasks';
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
          </Group>

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
              <Text size="sm" fw={500}>
                Notas
              </Text>
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {task.notes}
              </Text>
            </>
          )}

          <Divider />
          <Group justify="flex-end">
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
