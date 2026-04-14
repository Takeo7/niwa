import {
  Stack,
  Group,
  Title,
  Text,
  Badge,
  Loader,
  Center,
  Button,
  Paper,
  Tabs,
} from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import {
  Outlet,
  useNavigate,
  useParams,
  useLocation,
  Link,
} from 'react-router-dom';
import { useTask } from '../hooks/useTasks';
import { StatusBadge } from '../../../shared/components/StatusBadge';
import { MonoId } from '../../../shared/components/MonoId';

const PRIORITY_COLORS: Record<string, string> = {
  baja: 'blue',
  media: 'yellow',
  alta: 'orange',
  critica: 'red',
};

/** Derive the active tab from the current URL.  Using the URL as the
 *  single source of truth means back/forward/deep-linking work
 *  without any extra state. */
function tabFromPath(pathname: string, taskId: string): string {
  if (pathname.endsWith(`/tasks/${taskId}/runs`)) return 'runs';
  if (pathname.endsWith(`/tasks/${taskId}/routing`)) return 'routing';
  return 'details';
}

export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: task, isLoading, isError } = useTask(taskId ?? null);

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (isError || !task) {
    return (
      <Stack gap="md" py="md">
        <Group>
          <Button
            variant="subtle"
            leftSection={<IconArrowLeft size={16} />}
            component={Link}
            to="/tasks"
          >
            Volver
          </Button>
        </Group>
        <Paper withBorder p="md" radius="sm">
          <Text ta="center" c="dimmed">
            Tarea no encontrada.
          </Text>
        </Paper>
      </Stack>
    );
  }

  const active = tabFromPath(location.pathname, task.id);

  const setTab = (value: string | null) => {
    if (!value) return;
    if (value === 'details') {
      navigate(`/tasks/${task.id}`);
    } else {
      navigate(`/tasks/${task.id}/${value}`);
    }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
          <Group gap="xs">
            <Button
              variant="subtle"
              size="compact-sm"
              leftSection={<IconArrowLeft size={14} />}
              component={Link}
              to="/tasks"
            >
              Tareas
            </Button>
            <MonoId id={task.id} chars={8} />
          </Group>
          <Title order={3}>{task.title}</Title>
          <Group gap="xs">
            <StatusBadge status={task.status} kind="task" />
            <Badge
              color={PRIORITY_COLORS[task.priority] || 'gray'}
              variant="light"
              radius="sm"
            >
              {task.priority}
            </Badge>
            {task.project_name && (
              <Badge variant="outline" radius="sm">
                {task.project_name}
              </Badge>
            )}
            {task.urgent === 1 && (
              <Badge color="red" radius="sm">Urgente</Badge>
            )}
            {task.area && (
              <Badge variant="dot" radius="sm">{task.area}</Badge>
            )}
          </Group>
        </Stack>
      </Group>

      <Tabs value={active} onChange={setTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="details">Detalles</Tabs.Tab>
          <Tabs.Tab value="runs">Runs</Tabs.Tab>
          <Tabs.Tab value="routing">Routing</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value={active} pt="md">
          <Outlet context={{ task }} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
