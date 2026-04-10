import { useNavigate } from 'react-router-dom';
import {
  Title,
  SimpleGrid,
  Card,
  Text,
  Badge,
  Group,
  Stack,
  Loader,
  Center,
} from '@mantine/core';
import { IconFolders } from '@tabler/icons-react';
import { useProjects } from '../hooks/useProjects';

export function ProjectList() {
  const { data: projects, isLoading } = useProjects();
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  return (
    <Stack gap="md">
      <Title order={3}>Proyectos</Title>

      {!projects?.length ? (
        <Center py="xl">
          <Stack align="center" gap="sm">
            <IconFolders size={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">No hay proyectos</Text>
          </Stack>
        </Center>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          {projects.map((p) => (
            <Card
              key={p.id}
              shadow="sm"
              padding="lg"
              radius="md"
              withBorder
              style={{ cursor: 'pointer' }}
              onClick={() => navigate(`/projects/${p.slug}`)}
            >
              <Group justify="space-between" mb="xs">
                <Text fw={600} lineClamp={1}>
                  {p.name}
                </Text>
                <Badge
                  color={p.open_tasks > 0 ? 'blue' : 'green'}
                  variant="light"
                  size="sm"
                >
                  {p.open_tasks} abiertas
                </Badge>
              </Group>
              <Text size="sm" c="dimmed" lineClamp={2} mb="sm">
                {p.description || 'Sin descripción'}
              </Text>
              <Group gap="xs">
                <Badge size="xs" variant="outline">
                  {p.total_tasks} tareas
                </Badge>
                <Badge size="xs" color="green" variant="outline">
                  {p.done_tasks} hechas
                </Badge>
              </Group>
            </Card>
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
