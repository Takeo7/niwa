import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IconAlertCircle, IconPlayerStop, IconRocket } from "@tabler/icons-react";

import { ApiError, apiFetch } from "../../api";


export interface Deployment {
  id: number;
  project_id: number;
  task_id: number | null;
  commit_sha: string | null;
  deploy_type: string;
  status: string;
  artifact_path: string | null;
  port: number | null;
  url_local: string | null;
  healthcheck_path: string;
  build_log: string | null;
  error: string | null;
  pid: number | null;
  started_at: string | null;
  finished_at: string | null;
  last_health_check: string | null;
  created_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  queued: "gray",
  building: "cyan",
  starting: "blue",
  healthy: "green",
  unhealthy: "orange",
  failed: "red",
  stopped: "gray",
  rolled_back: "violet",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

interface Props {
  slug: string;
  active: boolean;
}

export function DeploysTab({ slug, active }: Props) {
  const qc = useQueryClient();

  const query = useQuery<Deployment[]>({
    queryKey: ["deployments", slug],
    queryFn: () => apiFetch<Deployment[]>(`/projects/${slug}/deployments`),
    enabled: active,
    refetchInterval: active ? 5000 : false,
  });

  const triggerMutation = useMutation<Deployment, Error, void>({
    mutationFn: () =>
      apiFetch<Deployment>(`/projects/${slug}/deployments`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deployments", slug] });
    },
    onError: (err) => {
      notifications.show({
        title: "Deploy failed",
        message: err instanceof ApiError ? err.message : "Unknown error",
        color: "red",
      });
    },
  });

  const stopMutation = useMutation<Deployment, Error, number>({
    mutationFn: (deployId) =>
      apiFetch<Deployment>(`/deployments/${deployId}/stop`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deployments", slug] });
    },
  });

  const rollbackMutation = useMutation<Deployment, Error, number>({
    mutationFn: (deployId) =>
      apiFetch<Deployment>(`/deployments/${deployId}/rollback`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deployments", slug] });
      notifications.show({ message: "Rollback triggered", color: "blue" });
    },
  });

  if (query.isLoading) {
    return <Group justify="center" py="md"><Loader size="sm" /></Group>;
  }
  if (query.isError) {
    return (
      <Alert icon={<IconAlertCircle size={16} />} color="red" title="Error">
        No se pudieron cargar los deploys.
      </Alert>
    );
  }

  const deployments = query.data ?? [];

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={500}>Deployments</Text>
        <Button
          leftSection={<IconRocket size={16} />}
          size="sm"
          onClick={() => triggerMutation.mutate()}
          loading={triggerMutation.isPending}
        >
          Deploy
        </Button>
      </Group>

      {deployments.length === 0 ? (
        <Text c="dimmed" ta="center">No deployments yet</Text>
      ) : (
        <Table withRowBorders verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>#</Table.Th>
              <Table.Th>Commit</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>URL</Table.Th>
              <Table.Th>Created</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {deployments.map((d) => (
              <Table.Tr key={d.id}>
                <Table.Td>{d.id}</Table.Td>
                <Table.Td>
                  <Text size="xs" ff="monospace">{d.commit_sha ?? "—"}</Text>
                </Table.Td>
                <Table.Td>
                  <Badge variant="outline" size="xs">{d.deploy_type}</Badge>
                </Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLOR[d.status] ?? "gray"} variant="light" size="sm">
                    {d.status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {d.url_local ? (
                    <Text size="xs" component="a" href={d.url_local} target="_blank" rel="noopener">
                      {d.url_local}
                    </Text>
                  ) : "—"}
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">{formatDate(d.created_at)}</Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end">
                    {d.status === "healthy" && (
                      <Tooltip label="Stop">
                        <Button
                          variant="subtle"
                          color="red"
                          size="xs"
                          leftSection={<IconPlayerStop size={12} />}
                          onClick={() => stopMutation.mutate(d.id)}
                          loading={stopMutation.isPending && stopMutation.variables === d.id}
                        >
                          Stop
                        </Button>
                      </Tooltip>
                    )}
                    {(d.status === "stopped" || d.status === "failed") && d.artifact_path && (
                      <Button
                        variant="subtle"
                        color="blue"
                        size="xs"
                        onClick={() => rollbackMutation.mutate(d.id)}
                        loading={rollbackMutation.isPending && rollbackMutation.variables === d.id}
                      >
                        Rollback
                      </Button>
                    )}
                    {d.error && (
                      <Tooltip label={d.error}>
                        <Text size="xs" c="red" style={{ cursor: "help" }}>⚠</Text>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
