import {
  Title,
  SimpleGrid,
  Card,
  Text,
  Stack,
  Group,
  Loader,
  Center,
  Badge,
  RingProgress,
  ThemeIcon,
} from '@mantine/core';
import { BarChart, LineChart } from '@mantine/charts';
import {
  IconCheck,
  IconX,
  IconClock,
  IconPlayerPlay,
} from '@tabler/icons-react';
import { useExecutorMetrics, useStats } from '../../../shared/api/queries';

function StatCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between">
        <Stack gap={0}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            {label}
          </Text>
          <Text size="xl" fw={700}>
            {value}
          </Text>
        </Stack>
        <ThemeIcon color={color} variant="light" size="xl" radius="md">
          {icon}
        </ThemeIcon>
      </Group>
    </Card>
  );
}

export function MetricsDashboard() {
  const { data: executor, isLoading: execLoading } = useExecutorMetrics();
  const { data: stats, isLoading: statsLoading } = useStats();

  if (execLoading || statsLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const statusData = stats?.by_status
    ? Object.entries(stats.by_status).map(([status, count]) => ({
        status,
        Tareas: count,
      }))
    : [];

  const completionsData = stats?.completions_by_day || [];

  const avgTimeFormatted = executor?.avg_execution_time_seconds
    ? executor.avg_execution_time_seconds >= 3600
      ? `${Math.round(executor.avg_execution_time_seconds / 3600)}h`
      : executor.avg_execution_time_seconds >= 60
        ? `${Math.round(executor.avg_execution_time_seconds / 60)}m`
        : `${Math.round(executor.avg_execution_time_seconds)}s`
    : '—';

  return (
    <Stack gap="md">
      <Title order={3}>Métricas</Title>

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
        <StatCard
          label="Completadas hoy"
          value={executor?.today.completed ?? 0}
          icon={<IconCheck size={24} />}
          color="green"
        />
        <StatCard
          label="Fallidas hoy"
          value={executor?.today.failed ?? 0}
          icon={<IconX size={24} />}
          color="red"
        />
        <StatCard
          label="Pendientes"
          value={executor?.today.pending ?? 0}
          icon={<IconClock size={24} />}
          color="yellow"
        />
        <StatCard
          label="En progreso"
          value={executor?.today.in_progress ?? 0}
          icon={<IconPlayerPlay size={24} />}
          color="blue"
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
        <Card withBorder radius="md" p="md">
          <Group justify="space-between" mb="md">
            <Text fw={500}>Resumen semanal</Text>
            <Badge color="brand" variant="light">
              Tasa de éxito: {executor?.success_rate ?? 0}%
            </Badge>
          </Group>
          <Group gap="xl" justify="center">
            <RingProgress
              size={120}
              thickness={12}
              roundCaps
              sections={[
                {
                  value: executor?.success_rate ?? 0,
                  color: 'green',
                },
              ]}
              label={
                <Text ta="center" size="sm" fw={700}>
                  {executor?.success_rate ?? 0}%
                </Text>
              }
            />
            <Stack gap="xs">
              <Group gap="xs">
                <Badge color="green" variant="dot" size="sm">
                  Completadas: {executor?.week.completed ?? 0}
                </Badge>
              </Group>
              <Group gap="xs">
                <Badge color="red" variant="dot" size="sm">
                  Fallidas: {executor?.week.failed ?? 0}
                </Badge>
              </Group>
              <Group gap="xs">
                <Badge color="blue" variant="dot" size="sm">
                  Tiempo medio: {avgTimeFormatted}
                </Badge>
              </Group>
            </Stack>
          </Group>
        </Card>

        <Card withBorder radius="md" p="md">
          <Text fw={500} mb="md">
            Tareas por estado
          </Text>
          {statusData.length > 0 ? (
            <BarChart
              h={200}
              data={statusData}
              dataKey="status"
              series={[{ name: 'Tareas', color: 'brand.5' }]}
            />
          ) : (
            <Center h={200}>
              <Text c="dimmed" size="sm">
                Sin datos
              </Text>
            </Center>
          )}
        </Card>
      </SimpleGrid>

      <Card withBorder radius="md" p="md">
        <Text fw={500} mb="md">
          Tareas completadas (últimos 14 días)
        </Text>
        {completionsData.length > 0 ? (
          <LineChart
            h={250}
            data={completionsData.map((d) => ({
              ...d,
              Completadas: d.count,
            }))}
            dataKey="day"
            series={[{ name: 'Completadas', color: 'brand.5' }]}
            curveType="natural"
          />
        ) : (
          <Center h={200}>
            <Text c="dimmed" size="sm">
              Sin datos de completados
            </Text>
          </Center>
        )}
      </Card>

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
        <Card withBorder radius="md" p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Total tareas
          </Text>
          <Text size="xl" fw={700}>
            {stats?.total ?? 0}
          </Text>
        </Card>
        <Card withBorder radius="md" p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Abiertas
          </Text>
          <Text size="xl" fw={700}>
            {stats?.open ?? 0}
          </Text>
        </Card>
        <Card withBorder radius="md" p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Hechas hoy
          </Text>
          <Text size="xl" fw={700}>
            {stats?.done_today ?? 0}
          </Text>
        </Card>
        <Card withBorder radius="md" p="md">
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Vencidas
          </Text>
          <Text size="xl" fw={700} c="red">
            {stats?.overdue ?? 0}
          </Text>
        </Card>
      </SimpleGrid>
    </Stack>
  );
}
