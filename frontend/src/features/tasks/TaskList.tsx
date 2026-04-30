import { useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Chip,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertCircle,
  IconCircleCheck,
  IconPlayerStop,
  IconRefresh,
  IconThumbUp,
  IconTrash,
} from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";

import {
  ApiError,
  isTaskCancellable,
  isTaskRetryable,
  type Task,
  type TaskStatus,
} from "../../api";
import { useApprovePlan, useCancelTask, useDeleteTask, useRetryTask, useTasks } from "./api";

interface Props {
  slug: string;
}

const STATUS_COLOR: Record<TaskStatus, string> = {
  inbox: "gray",
  queued: "blue",
  running: "cyan",
  planning: "indigo",
  waiting_approval: "orange",
  reviewing: "violet",
  waiting_input: "yellow",
  done: "green",
  failed: "red",
  cancelled: "gray",
};

const FILTER_OPTIONS: Array<{ value: TaskStatus | "all"; label: string }> = [
  { value: "all", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "waiting_input", label: "Waiting input" },
  { value: "waiting_approval", label: "Waiting approval" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function TaskList({ slug }: Props) {
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const query = useTasks(slug);
  const deleteMutation = useDeleteTask(slug);
  const cancelMutation = useCancelTask(slug);
  const retryMutation = useRetryTask(slug);
  const approveMutation = useApprovePlan(slug);
  const navigate = useNavigate();

  const handleDelete = (task: Task) => {
    deleteMutation.mutate(task.id, {
      onError: (err) => {
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

  const handleCancel = (task: Task, e: React.MouseEvent) => {
    e.stopPropagation();
    cancelMutation.mutate(task.id, {
      onError: (err) => {
        notifications.show({
          title: "No se pudo cancelar",
          message: err instanceof ApiError ? err.message : "Error desconocido",
          color: "red",
        });
      },
    });
  };

  const handleRetry = (task: Task, e: React.MouseEvent) => {
    e.stopPropagation();
    retryMutation.mutate(task.id, {
      onError: (err) => {
        notifications.show({
          title: "No se pudo reintentar",
          message: err instanceof ApiError ? err.message : "Error desconocido",
          color: "red",
        });
      },
    });
  };

  const handleApprove = (task: Task, e: React.MouseEvent) => {
    e.stopPropagation();
    approveMutation.mutate(task.id, {
      onError: (err) => {
        notifications.show({
          title: "No se pudo aprobar el plan",
          message: err instanceof ApiError ? err.message : "Error desconocido",
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

  const allTasks = query.data ?? [];
  const tasks = filter === "all" ? allTasks : allTasks.filter((t) => t.status === filter);

  // Count by status for filter chips
  const counts = allTasks.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <Stack gap="sm">
      {allTasks.length > 0 && (
        <Chip.Group value={filter} onChange={(v) => setFilter((v as TaskStatus | "all") ?? "all")}>
          <Group gap="xs" wrap="wrap">
            {FILTER_OPTIONS.filter(
              (o) => o.value === "all" || (counts[o.value] ?? 0) > 0
            ).map((o) => (
              <Chip key={o.value} value={o.value} size="xs" variant="light">
                {o.label}
                {o.value !== "all" && counts[o.value] != null
                  ? ` (${counts[o.value]})`
                  : ""}
              </Chip>
            ))}
          </Group>
        </Chip.Group>
      )}

      {tasks.length === 0 ? (
        <Text c="dimmed" py="md" ta="center">
          {allTasks.length === 0 ? "No tasks yet" : "No tasks match the filter"}
        </Text>
      ) : (
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
              const cancellable = isTaskCancellable(task);
              const retryable = isTaskRetryable(task);
              const needsApproval = task.status === "waiting_approval";
              const isDone = task.status === "done" || task.status === "cancelled";
              return (
                <Table.Tr
                  key={task.id}
                  onClick={() => navigate(`/projects/${slug}/tasks/${task.id}`)}
                  style={{ cursor: "pointer" }}
                >
                  <Table.Td>
                    <Stack gap={2}>
                      <Text size="sm">{task.title}</Text>
                      {task.parent_task_id && (
                        <Text size="xs" c="dimmed">Subtask #{task.parent_task_id}</Text>
                      )}
                    </Stack>
                  </Table.Td>
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
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      {needsApproval && (
                        <Tooltip label="Aprobar plan">
                          <ActionIcon
                            variant="subtle"
                            color="orange"
                            aria-label={`Aprobar plan de ${task.title}`}
                            onClick={(e) => handleApprove(task, e)}
                            loading={approveMutation.isPending && approveMutation.variables === task.id}
                          >
                            <IconThumbUp size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {retryable && (
                        <Tooltip label="Reintentar">
                          <ActionIcon
                            variant="subtle"
                            color="blue"
                            aria-label={`Reintentar tarea ${task.title}`}
                            onClick={(e) => handleRetry(task, e)}
                            loading={retryMutation.isPending && retryMutation.variables === task.id}
                          >
                            <IconRefresh size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {cancellable && (
                        <Tooltip label="Cancelar">
                          <ActionIcon
                            variant="subtle"
                            color="orange"
                            aria-label={`Cancelar tarea ${task.title}`}
                            onClick={(e) => handleCancel(task, e)}
                            loading={cancelMutation.isPending && cancelMutation.variables === task.id}
                          >
                            <IconPlayerStop size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {isDone && !retryable && (
                        <Tooltip label="Completado">
                          <ActionIcon variant="subtle" color="green" disabled aria-label="Completado">
                            <IconCircleCheck size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {!cancellable && !retryable && !needsApproval && task.status !== "done" && (
                        <Tooltip label="Borrar tarea">
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={`Borrar tarea ${task.title}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(task);
                            }}
                            loading={deleteMutation.isPending && deleteMutation.variables === task.id}
                          >
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
