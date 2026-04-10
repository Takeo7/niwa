import { useNavigate } from 'react-router-dom';
import {
  Stack,
  Title,
  SimpleGrid,
  Paper,
  Text,
  Group,
  Badge,
  Progress,
  Card,
  Loader,
  Center,
  ThemeIcon,
  Box,
} from '@mantine/core';
import { BarChart } from '@mantine/charts';
import {
  IconChecklist,
  IconClock,
  IconAlertTriangle,
  IconPlayerPlay,
  IconActivity,
} from '@tabler/icons-react';
import { useDashboard, useActivity, useProjects, useStats } from '../../../shared/api/queries';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/es';

dayjs.extend(relativeTime);
dayjs.locale('es');

const ACTIVITY_COLORS: Record<string, string> = {
  created: 'blue',
  completed: 'green',
  failed: 'red',
  blocked: 'orange',
  updated: 'yellow',
  started: 'cyan',
};

export function DashboardView() {
  const { data: dashboard, isLoading: dashLoading } = useDashboard();
  const { data: stats } = useStats();
  const { data: activity, isLoading: actLoading } = useActivity(8);
  const { data: projects } = useProjects();
  const navigate = useNavigate();

  if (dashLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const doneToday = dashboard?.done_today ?? stats?.done_today ?? 0;
  const pending = dashboard?.pending ?? 0;
  const blocked = dashboard?.blocked ?? 0;
  const inProgress = dashboard?.in_progress ?? 0;

  const velocity = dashboard?.velocity ?? stats?.completions_by_day ?? [];
  const attention = dashboard?.attention ?? [];

  return (
    <Stack gap="md">
      <Title order={3}>Panel de control</Title>

      {/* KPI Cards */}
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Paper p="md" radius="md" withBorder>
          <Group gap="xs">
            <ThemeIcon variant="light" color="green" size="lg">
              <IconChecklist size={20} />
            </ThemeIcon>
            <Box>
              <Text size="xl" fw={700}>{doneToday}</Text>
              <Text size="xs" c="dimmed">Hechas hoy</Text>
            </Box>
          </Group>
        </Paper>
        <Paper p="md" radius="md" withBorder>
          <Group gap="xs">
            <ThemeIcon variant="light" color="blue" size="lg">
              <IconClock size={20} />
            </ThemeIcon>
            <Box>
              <Text size="xl" fw={700}>{pending}</Text>
              <Text size="xs" c="dimmed">Pendientes</Text>
            </Box>
          </Group>
        </Paper>
        <Paper p="md" radius="md" withBorder>
          <Group gap="xs">
            <ThemeIcon variant="light" color="orange" size="lg">
              <IconAlertTriangle size={20} />
            </ThemeIcon>
            <Box>
              <Text size="xl" fw={700}>{blocked}</Text>
              <Text size="xs" c="dimmed">Bloqueadas</Text>
            </Box>
          </Group>
        </Paper>
        <Paper p="md" radius="md" withBorder>
          <Group gap="xs">
            <ThemeIcon variant="light" color="cyan" size="lg">
              <IconPlayerPlay size={20} />
            </ThemeIcon>
            <Box>
              <Text size="xl" fw={700}>{inProgress}</Text>
              <Text size="xs" c="dimmed">En progreso</Text>
            </Box>
          </Group>
        </Paper>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {/* Velocity Chart */}
        <Paper p="md" radius="md" withBorder>
          <Text fw={600} mb="sm">Velocidad (7 días)</Text>
          {velocity.length > 0 ? (
            <BarChart
              h={200}
              data={velocity.map((v) => ({
                day: typeof v.day === 'string' ? v.day.slice(5) : String(v.day),
                Completadas: v.count,
              }))}
              dataKey="day"
              series={[{ name: 'Completadas', color: 'brand.5' }]}
            />
          ) : (
            <Center h={200}>
              <Text c="dimmed" size="sm">Sin datos de velocidad</Text>
            </Center>
          )}
        </Paper>

        {/* Attention Items */}
        <Paper p="md" radius="md" withBorder>
          <Text fw={600} mb="sm">Requieren atención</Text>
          {attention.length === 0 ? (
            <Center h={200}>
              <Text c="dimmed" size="sm">Sin tareas que requieran atención</Text>
            </Center>
          ) : (
            <Stack gap="xs">
              {attention.slice(0, 8).map((item) => (
                <Paper
                  key={item.id}
                  p="xs"
                  radius="sm"
                  withBorder
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate('/tasks')}
                >
                  <Group justify="space-between" wrap="nowrap">
                    <Text size="sm" lineClamp={1} style={{ flex: 1 }}>
                      {item.title}
                    </Text>
                    <Group gap={4}>
                      <Badge size="xs" color={
                        item.status === 'bloqueada' ? 'orange' :
                        item.status === 'revision' ? 'yellow' : 'red'
                      }>
                        {item.status}
                      </Badge>
                      {item.project_name && (
                        <Badge size="xs" variant="outline">{item.project_name}</Badge>
                      )}
                    </Group>
                  </Group>
                </Paper>
              ))}
            </Stack>
          )}
        </Paper>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {/* Projects Overview */}
        <Paper p="md" radius="md" withBorder>
          <Text fw={600} mb="sm">Proyectos</Text>
          {!projects?.length ? (
            <Center h={150}>
              <Text c="dimmed" size="sm">Sin proyectos</Text>
            </Center>
          ) : (
            <Stack gap="xs">
              {projects.slice(0, 6).map((p) => {
                const pct = p.total_tasks > 0
                  ? Math.round((p.done_tasks / p.total_tasks) * 100)
                  : 0;
                return (
                  <Card
                    key={p.id}
                    p="xs"
                    radius="sm"
                    withBorder
                    style={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/projects/${p.slug}`)}
                  >
                    <Group justify="space-between" mb={4}>
                      <Text size="sm" fw={500} lineClamp={1}>{p.name}</Text>
                      <Text size="xs" c="dimmed">{p.done_tasks}/{p.total_tasks}</Text>
                    </Group>
                    <Progress value={pct} size="sm" color="brand" />
                  </Card>
                );
              })}
            </Stack>
          )}
        </Paper>

        {/* Activity Feed */}
        <Paper p="md" radius="md" withBorder>
          <Group gap="xs" mb="sm">
            <IconActivity size={18} />
            <Text fw={600}>Actividad reciente</Text>
          </Group>
          {actLoading ? (
            <Center h={150}>
              <Loader size="sm" />
            </Center>
          ) : !activity?.length ? (
            <Center h={150}>
              <Text c="dimmed" size="sm">Sin actividad reciente</Text>
            </Center>
          ) : (
            <Stack gap="xs">
              {activity.map((a) => (
                <Group key={a.id} gap="xs" wrap="nowrap">
                  <Badge
                    size="xs"
                    color={ACTIVITY_COLORS[a.type] || 'gray'}
                    variant="light"
                    w={80}
                    styles={{ root: { flexShrink: 0 } }}
                  >
                    {a.type}
                  </Badge>
                  <Text size="xs" lineClamp={1} style={{ flex: 1 }}>
                    {a.task_title || a.description}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
                    {dayjs(a.created_at).fromNow()}
                  </Text>
                </Group>
              ))}
            </Stack>
          )}
        </Paper>
      </SimpleGrid>
    </Stack>
  );
}
