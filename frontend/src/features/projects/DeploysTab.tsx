import { Alert, Anchor, Badge, Button, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { IconAlertTriangle, IconRocket } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import {
  Deployment,
  DeploymentStatus,
  listDeployments,
  rollbackDeployment,
  stopDeployment,
  triggerDeployment,
} from "../../api";

interface Props {
  projectSlug: string;
  active: boolean;
}

const STATUS_COLORS: Record<DeploymentStatus, string> = {
  queued: "gray",
  building: "blue",
  starting: "blue",
  healthy: "green",
  unhealthy: "orange",
  failed: "red",
  stopped: "gray",
  rolled_back: "violet",
};

export function DeploysTab({ projectSlug, active }: Props) {
  const [deploys, setDeploys] = useState<Deployment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      setDeploys(await listDeployments(projectSlug));
      setError(null);
    } catch (e: unknown) {
      setError("No se pudo cargar la lista de deployments");
    }
  };

  useEffect(() => {
    if (active) {
      refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, projectSlug]);

  if (!active) return null;
  if (deploys === null) {
    return <Group justify="center" py="xl"><Loader /></Group>;
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Text fw={500}>Deployments</Text>
        <Button
          leftSection={<IconRocket size={16} />}
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await triggerDeployment(projectSlug);
              await refresh();
            } catch (e: unknown) {
              setError("Deploy falló");
            } finally {
              setBusy(false);
            }
          }}
        >
          Deploy
        </Button>
      </Group>

      {error && (
        <Alert color="red" icon={<IconAlertTriangle size={16} />}>
          {error}
        </Alert>
      )}

      {deploys.length === 0 ? (
        <Text c="dimmed">Aún no hay deployments. Haz clic en Deploy.</Text>
      ) : (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>ID</Table.Th>
              <Table.Th>Commit</Table.Th>
              <Table.Th>Tipo</Table.Th>
              <Table.Th>Estado</Table.Th>
              <Table.Th>URL</Table.Th>
              <Table.Th>Cuándo</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {deploys.map((d) => (
              <Table.Tr key={d.id}>
                <Table.Td>#{d.id}</Table.Td>
                <Table.Td>{d.commit_sha ?? "—"}</Table.Td>
                <Table.Td>{d.deploy_type}</Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLORS[d.status]} variant="light">
                    {d.status}
                  </Badge>
                  {d.error && <Text c="red" size="xs">{d.error}</Text>}
                </Table.Td>
                <Table.Td>
                  {d.url_local ? (
                    <Anchor href={d.url_local} target="_blank" rel="noreferrer">
                      {d.url_local}
                    </Anchor>
                  ) : (
                    "—"
                  )}
                </Table.Td>
                <Table.Td>{new Date(d.created_at).toLocaleString()}</Table.Td>
                <Table.Td>
                  <Group gap="xs">
                    {d.status === "healthy" && (
                      <Button
                        size="xs"
                        variant="subtle"
                        color="orange"
                        onClick={async () => {
                          await stopDeployment(d.id);
                          refresh();
                        }}
                      >
                        Stop
                      </Button>
                    )}
                    {d.status === "stopped" && d.artifact_path && (
                      <Button
                        size="xs"
                        variant="subtle"
                        onClick={async () => {
                          await rollbackDeployment(d.id);
                          refresh();
                        }}
                      >
                        Rollback
                      </Button>
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
