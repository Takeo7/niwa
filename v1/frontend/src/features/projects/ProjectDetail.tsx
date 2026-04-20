import { Alert, Badge, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconAlertCircle } from "@tabler/icons-react";

import { useProject } from "./api";

interface Props {
  slug: string;
}

export function ProjectDetail({ slug }: Props) {
  const query = useProject(slug);

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
      <Text c="dimmed">Tareas — próximamente en PR-V1-06b.</Text>
    </Stack>
  );
}
