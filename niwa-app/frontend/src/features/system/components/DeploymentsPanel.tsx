import {
  Stack,
  Text,
  Card,
  Group,
  Badge,
  Button,
  Loader,
  Center,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconExternalLink, IconRefresh } from '@tabler/icons-react';
import {
  useDeployments,
  useUndeployProject,
} from '../../../shared/api/queries';
import type { Deployment } from '../../../shared/types';
import { HostingDomainWizard } from './HostingDomainWizard';

export function DeploymentsPanel() {
  const { data, isLoading, refetch, isFetching } = useDeployments();
  const undeploy = useUndeployProject();

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const deployments: Deployment[] = data?.deployments ?? [];

  return (
    <Stack gap="md">
      <HostingDomainWizard />
      <Group justify="space-between">
        <Title order={4}>Sitios desplegados</Title>
        <Button
          variant="subtle"
          size="compact-sm"
          leftSection={<IconRefresh size={14} />}
          onClick={() => refetch()}
          loading={isFetching}
        >
          Refrescar
        </Button>
      </Group>
      {deployments.length === 0 ? (
        <Text c="dimmed" size="sm">
          No hay ningún proyecto publicado todavía. Usa el botón "Deploy" en un
          proyecto para crear uno.
        </Text>
      ) : (
        <Stack gap="sm">
          {deployments.map((d) => (
            <DeploymentRow
              key={d.id}
              deployment={d}
              onUndeploy={async () => {
                try {
                  await undeploy.mutateAsync(d.project_id);
                  notifications.show({
                    title: 'Proyecto despublicado',
                    message: d.slug,
                    color: 'yellow',
                  });
                } catch (err) {
                  notifications.show({
                    title: 'Error',
                    message:
                      err instanceof Error ? err.message : 'Falló el undeploy',
                    color: 'red',
                  });
                }
              }}
              undeployPending={undeploy.isPending}
            />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

function DeploymentRow({
  deployment,
  onUndeploy,
  undeployPending,
}: {
  deployment: Deployment;
  onUndeploy: () => void;
  undeployPending: boolean;
}) {
  return (
    <Card withBorder>
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs">
            <Text fw={500}>{deployment.slug}</Text>
            <Badge
              color={deployment.status === 'active' ? 'green' : 'gray'}
              variant="light"
              size="sm"
            >
              {deployment.status}
            </Badge>
          </Group>
          {deployment.url ? (
            <Text
              component="a"
              href={deployment.url}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              c="brand"
              style={{ wordBreak: 'break-all' }}
            >
              {deployment.url} <IconExternalLink size={12} />
            </Text>
          ) : (
            <Text size="xs" c="dimmed">
              Sin URL asignada
            </Text>
          )}
          <Text size="xs" c="dimmed">
            {deployment.directory}
          </Text>
        </Stack>
        <Button
          variant="light"
          color="red"
          size="compact-sm"
          loading={undeployPending}
          onClick={onUndeploy}
        >
          Despublicar
        </Button>
      </Group>
    </Card>
  );
}
