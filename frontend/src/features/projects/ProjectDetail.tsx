import { useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconAlertTriangle, IconPlus } from "@tabler/icons-react";

import { TaskCreateModal } from "../tasks/TaskCreateModal";
import { TaskList } from "../tasks/TaskList";
import { useProject } from "./api";

interface Props {
  slug: string;
}

export function ProjectDetail({ slug }: Props) {
  const query = useProject(slug);
  const [modalOpen, setModalOpen] = useState(false);

  if (query.isLoading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
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
        // Loud red banner: PR-V1-16 auto-merges PRs without review when
        // this flag is on, so the user must see it at a glance — the
        // small badge below is not enough on its own.
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
        <Text c="dimmed" size="sm">/{p.slug}</Text>
      </Group>

      <Divider my="xs" />

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

      <TaskCreateModal
        slug={slug}
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </Stack>
  );
}
