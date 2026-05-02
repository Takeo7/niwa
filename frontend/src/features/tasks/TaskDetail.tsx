import { useState } from "react";
import {
  ActionIcon,
  Alert, Anchor, Badge, Button, Code, Divider, Group, Loader, Stack, Text,
  Textarea, Title,
} from "@mantine/core";
import { IconAlertCircle, IconFile, IconX } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, listDeployments, type Deployment, type Run, type TaskPlan, type TaskReview, type TaskStatus } from "../../api";
import { TaskEventStream } from "./TaskEventStream";
import {
  useDeleteAttachment,
  useApprovePlan,
  useLatestRun,
  useRespondTask,
  useTask,
  useTaskAttachments,
  useTaskPlan,
  useTaskReview,
} from "./api";

interface Props {
  taskId: number;
  projectSlug?: string;
}

// Mirrors TaskList.STATUS_COLOR; cancelled also gets a strikethrough title.
const TASK_STATUS_COLOR: Record<TaskStatus, string> = {
  inbox: "gray", queued: "blue", running: "cyan", waiting_input: "yellow",
  triaging: "cyan", planning: "indigo", waiting_approval: "yellow",
  executing: "cyan", verifying: "violet", reviewing: "grape",
  done: "green", failed: "red", cancelled: "gray",
};

// Statuses where the task is still mutable enough to accept attachment
// edits (mirrors backend gate: see services/attachments.create_attachment).
const ATTACHMENT_EDITABLE: readonly TaskStatus[] = ["inbox", "queued"];

function formatDate(iso: string): string {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function prettyJson(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try { return JSON.stringify(JSON.parse(raw), null, 2); } catch { return raw; }
}

function Timeline({ plan, run, review, deployment }: {
  plan: TaskPlan | null | undefined;
  run: Run | null | undefined;
  review: TaskReview | null | undefined;
  deployment: Deployment | null | undefined;
}) {
  const rows = [
    plan && { label: "plan", detail: `${plan.status} by ${plan.planner}`, time: plan.created_at },
    run && { label: "run", detail: `${run.status}${run.outcome ? ` · ${run.outcome}` : ""}`, time: run.started_at },
    review && { label: "review", detail: `${review.decision} · iteration ${review.iteration}`, time: review.created_at },
    deployment && { label: "deploy", detail: `${deployment.status}${deployment.url_local ? ` · ${deployment.url_local}` : ""}`, time: deployment.created_at },
  ].filter(Boolean) as { label: string; detail: string; time: string }[];

  if (rows.length === 0) return null;
  return (
    <Stack gap="xs">
      <Title order={4}>Timeline</Title>
      {rows.map((row) => (
        <Group key={`${row.label}-${row.time}`} gap="xs" wrap="nowrap">
          <Badge variant="light">{row.label}</Badge>
          <Text size="sm" style={{ flex: 1 }}>{row.detail}</Text>
          <Text size="xs" c="dimmed">{formatDate(row.time)}</Text>
        </Group>
      ))}
    </Stack>
  );
}

export function TaskDetail({ taskId, projectSlug }: Props) {
  const taskQuery = useTask(taskId);
  const runQuery = useLatestRun(taskId);
  const planQuery = useTaskPlan(taskId);
  const reviewQuery = useTaskReview(taskId);
  const deploymentsQuery = useQuery({
    queryKey: ["project", projectSlug, "deployments"],
    queryFn: () => listDeployments(projectSlug!),
    enabled: Boolean(projectSlug),
  });
  const approvePlan = useApprovePlan(taskId);
  const respondMutation = useRespondTask(taskId);
  const attachmentsQuery = useTaskAttachments(taskId);
  const deleteAttachment = useDeleteAttachment(taskId);
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
  const attachments = attachmentsQuery.data ?? [];
  const canEditAttachments = ATTACHMENT_EDITABLE.includes(task.status);
  const latestRun = runQuery.data ?? null;
  const verificationJson = prettyJson(latestRun?.verification_json);
  const taskDeployment = deploymentsQuery.data?.find((d) => d.task_id === task.id) ?? null;

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

      {planQuery.data ? (
        <Stack gap="xs">
          <Title order={4}>Plan</Title>
          <Badge variant="light" w="fit-content">{planQuery.data.status}</Badge>
          <Text size="sm">{planQuery.data.summary}</Text>
          {planQuery.data.steps.map((step, index) => (
            <Text key={`${index}-${step}`} size="sm">
              {index + 1}. {step}
            </Text>
          ))}
          {task.status === "waiting_approval" && planQuery.data.status === "ready" ? (
            <Button
              w="fit-content"
              onClick={() => approvePlan.mutate()}
              loading={approvePlan.isPending}
            >
              Approve plan
            </Button>
          ) : null}
        </Stack>
      ) : null}

      {reviewQuery.data ? (
        <Stack gap="xs">
          <Title order={4}>Review</Title>
          <Group gap="xs">
            <Badge
              color={reviewQuery.data.decision === "approved" ? "green" : "orange"}
              variant="light"
            >
              {reviewQuery.data.decision}
            </Badge>
            <Badge variant="light">iteration {reviewQuery.data.iteration}</Badge>
            <Text size="sm">{reviewQuery.data.summary}</Text>
          </Group>
          {reviewQuery.data.findings.map((finding, index) => (
            <Text key={`${index}-${finding}`} size="sm">
              {finding}
            </Text>
          ))}
        </Stack>
      ) : null}

      <Timeline
        plan={planQuery.data}
        run={latestRun}
        review={reviewQuery.data}
        deployment={taskDeployment}
      />

      {latestRun ? (
        <Stack gap="xs">
          <Title order={4}>Latest run</Title>
          <Group gap="xs">
            <Badge variant="light">{latestRun.status}</Badge>
            <Badge variant="light">{latestRun.model}</Badge>
            {latestRun.outcome ? <Badge variant="light">{latestRun.outcome}</Badge> : null}
            {latestRun.pid ? <Text size="sm">pid {latestRun.pid}</Text> : null}
          </Group>
          <Text size="xs" c="dimmed" style={{ wordBreak: "break-all" }}>
            {latestRun.artifact_root}
          </Text>
          {verificationJson ? (
            <Code block style={{ maxHeight: 220, overflow: "auto" }}>
              {verificationJson}
            </Code>
          ) : null}
        </Stack>
      ) : null}

      {taskDeployment ? (
        <Stack gap="xs">
          <Title order={4}>Task deployment</Title>
          <Group gap="xs">
            <Badge variant="light">{taskDeployment.status}</Badge>
            <Badge variant="light">{taskDeployment.deploy_type}</Badge>
            {taskDeployment.url_local ? (
              <Anchor href={taskDeployment.url_local} target="_blank" rel="noreferrer" size="sm">
                {taskDeployment.url_local}
              </Anchor>
            ) : null}
          </Group>
        </Stack>
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

      {attachments.length > 0 ? (
        <Stack gap="xs">
          <Title order={4}>Attachments</Title>
          <Stack gap={4}>
            {attachments.map((a) => (
              <Group key={a.id} gap="xs" wrap="nowrap">
                <IconFile size={16} />
                <Text size="sm" style={{ flex: 1 }} truncate>
                  {a.filename}
                </Text>
                <Text size="xs" c="dimmed">
                  {formatSize(a.size_bytes)}
                </Text>
                {canEditAttachments ? (
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    aria-label={`Eliminar ${a.filename}`}
                    onClick={() => deleteAttachment.mutate(a.id)}
                    loading={deleteAttachment.isPending}
                  >
                    <IconX size={14} />
                  </ActionIcon>
                ) : null}
              </Group>
            ))}
          </Stack>
        </Stack>
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
