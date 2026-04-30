import { Group, Paper, Stack, Text } from "@mantine/core";
import { useSummary } from "../features/projects/api";
import { ProjectList } from "../features/projects/ProjectList";

function SummaryBar() {
  const { data } = useSummary();
  if (!data || data.total_tasks === 0) return null;

  const stats: Array<{ label: string; value: number; color: string }> = [
    { label: "Queued", value: data.queued, color: "blue" },
    { label: "Running", value: data.running, color: "cyan" },
    { label: "Waiting input", value: data.waiting_input, color: "yellow" },
    { label: "Waiting approval", value: data.waiting_approval, color: "orange" },
    { label: "Done", value: data.done, color: "green" },
    { label: "Failed", value: data.failed, color: "red" },
  ].filter((s) => s.value > 0);

  if (stats.length === 0) return null;

  return (
    <Paper withBorder p="xs" mb="md">
      <Group gap="lg" wrap="wrap">
        {stats.map((s) => (
          <Stack key={s.label} gap={0} align="center">
            <Text fw={700} size="lg" c={s.color}>{s.value}</Text>
            <Text size="xs" c="dimmed">{s.label}</Text>
          </Stack>
        ))}
      </Group>
    </Paper>
  );
}

export function ProjectsRoute() {
  return (
    <Stack gap={0}>
      <SummaryBar />
      <ProjectList />
    </Stack>
  );
}
