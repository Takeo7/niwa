import { useState } from "react";
import {
  Alert, Badge, Button, Divider, Group, Loader, Stack, Switch, Tabs, Text, Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconAlertCircle, IconAlertTriangle, IconGitPullRequest,
  IconListCheck, IconPlus, IconSettings,
} from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch, type Project } from "../../api";
import { TaskCreateModal } from "../tasks/TaskCreateModal";
import { TaskList } from "../tasks/TaskList";
import { useProject } from "./api";
import { PullsTab } from "./PullsTab";

interface Props { slug: string }

type TabValue = "tasks" | "pulls" | "settings";

function SettingsTab({ project }: { project: Project }) {
  const qc = useQueryClient();
  const patchMutation = useMutation({
    mutationFn: (patch: Partial<Pick<Project, "require_plan_approval" | "auto_review" | "max_review_iterations">>) =>
      apiFetch<Project>(`/projects/${project.slug}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", project.slug] });
      notifications.show({ message: "Settings saved", color: "green" });
    },
    onError: () => {
      notifications.show({ message: "Failed to save settings", color: "red" });
    },
  });

  return (
    <Stack gap="md" maw={480}>
      <Title order={4}>Project settings</Title>

      <Stack gap="xs">
        <Text fw={500} size="sm">Phase 2 pipeline</Text>
        <Switch
          label="Require plan approval before execution"
          description="The executor will pause and wait for you to approve the plan."
          checked={project.require_plan_approval}
          onChange={(e) => patchMutation.mutate({ require_plan_approval: e.currentTarget.checked })}
          disabled={patchMutation.isPending}
        />
        <Switch
          label="Auto-review after execution"
          description="Claude reviews the diff after each run and can request changes."
          checked={project.auto_review}
          onChange={(e) => patchMutation.mutate({ auto_review: e.currentTarget.checked })}
          disabled={patchMutation.isPending}
        />
      </Stack>

      <Stack gap="xs">
        <Text fw={500} size="sm">General</Text>
        <Text size="sm" c="dimmed">Local path: <code>{project.local_path}</code></Text>
        <Text size="sm" c="dimmed">Kind: {project.kind}</Text>
        {project.git_remote && <Text size="sm" c="dimmed">Remote: {project.git_remote}</Text>}
        {project.deploy_port && <Text size="sm" c="dimmed">Deploy port: {project.deploy_port}</Text>}
      </Stack>
    </Stack>
  );
}

export function ProjectDetail({ slug }: Props) {
  const query = useProject(slug);
  const [modalOpen, setModalOpen] = useState(false);
  const [tab, setTab] = useState<TabValue>("tasks");

  if (query.isLoading) {
    return <Group justify="center" py="xl"><Loader /></Group>;
  }
  if (query.isError || !query.data) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} color="red" title="Error">
        No se pudo cargar el proyecto.
      </Alert>
    );
  }

  const p = query.data;
  return (
    <Stack gap="md">
      {p.autonomy_mode === "dangerous" && (
        <Alert
          color="red"
          variant="filled"
          title="Dangerous mode"
          icon={<IconAlertTriangle size={18} />}
        >
          Runs auto-merge PRs without review. Review carefully before enabling.
        </Alert>
      )}
      <Title order={2}>{p.name}</Title>
      <Group gap="xs">
        <Badge variant="light">{p.kind}</Badge>
        <Badge
          variant="light"
          color={p.autonomy_mode === "dangerous" ? "red" : "green"}
        >
          {p.autonomy_mode}
        </Badge>
        {p.require_plan_approval && <Badge variant="outline" color="orange">plan approval</Badge>}
        {p.auto_review && <Badge variant="outline" color="violet">auto-review</Badge>}
        <Text c="dimmed" size="sm">/{p.slug}</Text>
      </Group>

      <Divider my="xs" />

      <Tabs
        value={tab}
        onChange={(v) => setTab((v as TabValue) ?? "tasks")}
        keepMounted={false}
      >
        <Tabs.List>
          <Tabs.Tab value="tasks" leftSection={<IconListCheck size={14} />}>
            Tareas
          </Tabs.Tab>
          <Tabs.Tab value="pulls" leftSection={<IconGitPullRequest size={14} />}>
            Pull requests
          </Tabs.Tab>
          <Tabs.Tab value="settings" leftSection={<IconSettings size={14} />}>
            Settings
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="tasks" pt="md">
          <Stack gap="md">
            <Group justify="space-between" align="center">
              <Title order={4}>Tareas</Title>
              <Button
                leftSection={<IconPlus size={16} />}
                onClick={() => setModalOpen(true)}
              >
                Nueva tarea
              </Button>
            </Group>
            <TaskList slug={slug} />
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="pulls" pt="md">
          <PullsTab projectSlug={slug} active={tab === "pulls"} />
        </Tabs.Panel>

        <Tabs.Panel value="settings" pt="md">
          <SettingsTab project={p} />
        </Tabs.Panel>
      </Tabs>

      <TaskCreateModal
        slug={slug}
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </Stack>
  );
}
