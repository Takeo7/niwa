import { useState } from "react";
import {
  Alert, Anchor, Badge, Button, Code, Divider, Group, Loader, Stack, Text,
  Textarea, Title,
} from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";

import { ApiError, type TaskStatus } from "../../api";
import { TaskEventStream } from "./TaskEventStream";
import { useLatestRun, useRespondTask, useTask } from "./api";

interface Props { taskId: number }

// Mirrors TaskList.STATUS_COLOR; cancelled also gets a strikethrough title.
const TASK_STATUS_COLOR: Record<TaskStatus, string> = {
  inbox: "gray", queued: "blue", running: "cyan", waiting_input: "yellow",
  done: "green", failed: "red", cancelled: "gray",
};

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export function TaskDetail({ taskId }: Props) {
  const taskQuery = useTask(taskId);
  const runQuery = useLatestRun(taskId);
  const respondMutation = useRespondTask(taskId);
  const [response, setResponse] = useState("");

  if (taskQuery.isLoading) {
    return <Group justify="center" py="xl"><Loader /></Group>;
  }
  if (taskQuery.isError) {
    const notFound =
      taskQuery.error instanceof ApiError && taskQuery.error.status === 404;
    return (
      <Alert icon={<IconAlertCircle size={16} />} color="red"
        title={notFound ? "Task no encontrada" : "Error"}>
        {notFound
          ? "El id no corresponde a ninguna tarea."
          : "No se pudo cargar la tarea."}
      </Alert>
    );
  }

  const task = taskQuery.data!;
  const cancelled = task.status === "cancelled";
  const waitingInput = task.status === "waiting_input" && task.pending_question;

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Title order={2}
          style={cancelled ? { textDecoration: "line-through" } : undefined}>
          {task.title}
        </Title>
        <Group gap="xs">
          <Badge color={TASK_STATUS_COLOR[task.status]}
            variant={task.status === "running" ? "filled" : "light"}>
            {task.status}
          </Badge>
          {task.branch_name ? <Code>{task.branch_name}</Code> : null}
          {task.pr_url ? (
            <Anchor href={task.pr_url} target="_blank" rel="noreferrer" size="sm">
              PR
            </Anchor>
          ) : null}
        </Group>
        <Text c="dimmed" size="xs">
          Creado {formatDate(task.created_at)}
          {task.completed_at
            ? ` · Completado ${formatDate(task.completed_at)}`
            : null}
        </Text>
      </Stack>

      {task.description ? (
        <Text style={{ whiteSpace: "pre-wrap" }}>{task.description}</Text>
      ) : null}

      {waitingInput ? (
        <Alert color="yellow" title="Niwa necesita tu respuesta">
          <Text mb="sm" style={{ whiteSpace: "pre-wrap" }}>
            {task.pending_question}
          </Text>
          <Textarea
            value={response}
            onChange={(e) => setResponse(e.currentTarget.value)}
            minRows={3}
            placeholder="Escribe tu respuesta…"
          />
          <Button
            mt="sm"
            onClick={() => {
              respondMutation.mutate(
                { response },
                { onSuccess: () => setResponse("") },
              );
            }}
            disabled={!response.trim() || respondMutation.isPending}
            loading={respondMutation.isPending}
          >
            Responder
          </Button>
        </Alert>
      ) : null}

      <Divider my="xs" />

      <Title order={4}>Stream</Title>
      {runQuery.isLoading ? (
        <Group justify="center" py="sm"><Loader size="sm" /></Group>
      ) : (
        <TaskEventStream runId={runQuery.data?.id ?? null} />
      )}
    </Stack>
  );
}
