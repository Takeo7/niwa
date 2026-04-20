import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconTrash } from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";

import { ApiError, isTaskActive, type Task, type TaskStatus } from "../../api";
import { useDeleteTask, useTasks } from "./api";

interface Props {
  slug: string;
}

// Muted -> highlighted color scale matches the semantic of the state.
// Kept here (and not in api.ts) because it's purely a rendering concern.
const STATUS_COLOR: Record<TaskStatus, string> = {
  inbox: "gray",
  queued: "blue",
  running: "cyan",
  waiting_input: "yellow",
  done: "green",
  failed: "red",
  cancelled: "gray",
};

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function TaskList({ slug }: Props) {
  const query = useTasks(slug);
  const deleteMutation = useDeleteTask(slug);
  const navigate = useNavigate();

  const handleDelete = (task: Task) => {
    deleteMutation.mutate(task.id, {
      onError: (err) => {
        // 409 = backend refused delete because task is active now; the
        // button only hides the common case, so surface a legible toast
        // and rely on onSettled invalidation to refresh the row.
        const detail =
          err instanceof ApiError && err.status === 409
            ? "La tarea está en curso; no se puede borrar"
            : err instanceof ApiError && err.status === 404
              ? "La tarea ya no existe"
              : err.message;
        notifications.show({
          title: "No se pudo borrar la tarea",
          message: detail,
          color: "red",
        });
      },
    });
  };

  if (query.isLoading) {
    return (
      <Group justify="center" py="md">
        <Loader size="sm" />
      </Group>
    );
  }
  if (query.isError) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} color="red" title="Error">
        No se pudieron cargar las tareas.
      </Alert>
    );
  }

  const tasks = query.data ?? [];
  if (tasks.length === 0) {
    return (
      <Text c="dimmed" py="md" ta="center">
        No tasks yet
      </Text>
    );
  }

  return (
    <Stack gap="xs">
      <Table withRowBorders verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Title</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Created</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {tasks.map((task) => {
            const active = isTaskActive(task);
            return (
              <Table.Tr
                key={task.id}
                onClick={() => navigate(`/projects/${slug}/tasks/${task.id}`)}
                style={{ cursor: "pointer" }}
              >
                <Table.Td>{task.title}</Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLOR[task.status]} variant="light">
                    {task.status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {formatDate(task.created_at)}
                  </Text>
                </Table.Td>
                <Table.Td align="right">
                  {active ? null : (
                    <Tooltip label="Borrar tarea">
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={`Borrar tarea ${task.title}`}
                        // stopPropagation so the row's navigate handler
                        // does not fire on delete-button clicks.
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(task);
                        }}
                        loading={
                          deleteMutation.isPending &&
                          deleteMutation.variables === task.id
                        }
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
