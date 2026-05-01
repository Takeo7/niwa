import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertCircle, IconBan, IconRefresh, IconSearch, IconTrash } from "@tabler/icons-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, isTaskActive, type Task, type TaskStatus } from "../../api";
import { useCancelTask, useDeleteTask, useRetryTask, useTasks } from "./api";

interface Props {
  slug: string;
}

// Muted -> highlighted color scale matches the semantic of the state.
// Kept here (and not in api.ts) because it's purely a rendering concern.
const STATUS_COLOR: Record<TaskStatus, string> = {
  inbox: "gray",
  queued: "blue",
  triaging: "cyan",
  planning: "indigo",
  waiting_approval: "yellow",
  executing: "cyan",
  verifying: "violet",
  reviewing: "grape",
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

const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  ...Object.keys(STATUS_COLOR).map((status) => ({ value: status, label: status })),
];

const CANCELLABLE: readonly TaskStatus[] = ["inbox", "queued", "waiting_input"];
const RETRYABLE: readonly TaskStatus[] = ["failed", "cancelled"];

function visibleRows(tasks: Task[], allTasks: Task[]): Array<{ task: Task; depth: number }> {
  const byParent = new Map<number | null, Task[]>();
  const byId = new Map(allTasks.map((task) => [task.id, task]));
  for (const task of tasks) {
    const siblings = byParent.get(task.parent_task_id) ?? [];
    siblings.push(task);
    byParent.set(task.parent_task_id, siblings);
  }
  const rows: Array<{ task: Task; depth: number }> = [];
  const seen = new Set<number>();
  const pushChildren = (parentId: number | null, depth: number) => {
    for (const task of byParent.get(parentId) ?? []) {
      rows.push({ task, depth });
      seen.add(task.id);
      pushChildren(task.id, depth + 1);
    }
  };
  pushChildren(null, 0);
  for (const task of tasks) {
    if (!seen.has(task.id)) {
      let depth = 0;
      let parent = task.parent_task_id ? byId.get(task.parent_task_id) : null;
      while (parent) {
        depth += 1;
        parent = parent.parent_task_id ? byId.get(parent.parent_task_id) : null;
      }
      rows.push({ task, depth });
    }
  }
  return rows;
}

export function TaskList({ slug }: Props) {
  const query = useTasks(slug);
  const deleteMutation = useDeleteTask(slug);
  const cancelMutation = useCancelTask(slug);
  const retryMutation = useRetryTask(slug);
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

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
  const normalizedSearch = search.trim().toLowerCase();
  const filteredTasks = tasks.filter((task) => {
    const matchesStatus = statusFilter === "all" || task.status === statusFilter;
    const haystack = `${task.title}\n${task.description ?? ""}`.toLowerCase();
    const matchesSearch = !normalizedSearch || haystack.includes(normalizedSearch);
    return matchesStatus && matchesSearch;
  });
  if (tasks.length === 0) {
    return (
      <Text c="dimmed" py="md" ta="center">
        No tasks yet
      </Text>
    );
  }

  return (
    <Stack gap="xs">
      <Group align="end" gap="sm">
        <TextInput
          leftSection={<IconSearch size={16} />}
          placeholder="Search backlog"
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Select
          data={STATUS_OPTIONS}
          value={statusFilter}
          onChange={(value) => setStatusFilter(value ?? "all")}
          w={180}
        />
      </Group>
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
          {visibleRows(filteredTasks, tasks).map(({ task, depth }) => {
            const active = isTaskActive(task);
            const canCancel = CANCELLABLE.includes(task.status);
            const canRetry = RETRYABLE.includes(task.status);
            return (
              <Table.Tr
                key={task.id}
                onClick={() => navigate(`/projects/${slug}/tasks/${task.id}`)}
                style={{ cursor: "pointer" }}
              >
                <Table.Td>
                  <Text fw={depth === 0 ? 500 : 400} pl={depth * 20}>
                    {depth > 0 ? "-- " : null}
                    {task.title}
                  </Text>
                  {task.description ? (
                    <Text size="xs" c="dimmed" pl={depth * 20} lineClamp={1}>
                      {task.description}
                    </Text>
                  ) : null}
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
                <Table.Td align="right">
                  <Group gap={4} justify="flex-end">
                    {canCancel ? (
                      <Tooltip label="Cancelar tarea">
                        <ActionIcon
                          variant="subtle"
                          color="orange"
                          aria-label={`Cancelar tarea ${task.title}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            cancelMutation.mutate(task.id, {
                              onError: (err) => {
                                notifications.show({
                                  title: "No se pudo cancelar la tarea",
                                  message: err.message,
                                  color: "red",
                                });
                              },
                            });
                          }}
                          loading={
                            cancelMutation.isPending &&
                            cancelMutation.variables === task.id
                          }
                        >
                          <IconBan size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                    {canRetry ? (
                      <Tooltip label="Reintentar tarea">
                        <ActionIcon
                          variant="subtle"
                          color="blue"
                          aria-label={`Reintentar tarea ${task.title}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            retryMutation.mutate(task.id, {
                              onError: (err) => {
                                notifications.show({
                                  title: "No se pudo reintentar la tarea",
                                  message: err.message,
                                  color: "red",
                                });
                              },
                            });
                          }}
                          loading={
                            retryMutation.isPending &&
                            retryMutation.variables === task.id
                          }
                        >
                          <IconRefresh size={16} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
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
                  </Group>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
