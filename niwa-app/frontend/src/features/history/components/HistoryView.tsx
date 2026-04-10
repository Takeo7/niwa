import { useState } from 'react';
import {
  Stack,
  Title,
  Paper,
  Table,
  Text,
  Badge,
  Group,
  Select,
  TextInput,
  Pagination,
  Loader,
  Center,
  SimpleGrid,
  ThemeIcon,
  Box,
} from '@mantine/core';
import {
  IconSearch,
  IconHistory,
  IconCheck,
  IconX,
  IconClock,
} from '@tabler/icons-react';
import { useHistory } from '../../../shared/api/queries';
import type { HistoryEntry } from '../../../shared/types';

const STATUS_COLORS: Record<string, string> = {
  hecha: 'green',
  completada: 'green',
  success: 'green',
  failed: 'red',
  fallida: 'red',
  error: 'red',
  pendiente: 'blue',
  en_progreso: 'cyan',
  bloqueada: 'orange',
};

function formatDuration(seconds?: number | null): string {
  if (!seconds) return '-';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function HistoryView() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('created_at');
  const [order, setOrder] = useState('desc');

  const { data, isLoading } = useHistory({
    page,
    per_page: 50,
    sort,
    order,
    status: status || undefined,
    search: search || undefined,
  });

  const items: HistoryEntry[] = data?.items ?? (Array.isArray(data) ? data as HistoryEntry[] : []);
  const total = data?.total ?? 0;
  const historyStats = data?.stats;
  const totalPages = Math.max(1, Math.ceil(total / 50));

  const handleSort = (col: string) => {
    if (sort === col) {
      setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      setSort(col);
      setOrder('desc');
    }
    setPage(1);
  };

  const sortIcon = (col: string) => {
    if (sort !== col) return '';
    return order === 'asc' ? ' ↑' : ' ↓';
  };

  return (
    <Stack gap="md">
      <Title order={3}>Historial</Title>

      {/* Stats */}
      {historyStats && (
        <SimpleGrid cols={{ base: 2, sm: 4 }}>
          <Paper p="sm" radius="md" withBorder>
            <Group gap="xs">
              <ThemeIcon variant="light" color="blue" size="md">
                <IconHistory size={16} />
              </ThemeIcon>
              <Box>
                <Text fw={700}>{historyStats.total}</Text>
                <Text size="xs" c="dimmed">Total</Text>
              </Box>
            </Group>
          </Paper>
          <Paper p="sm" radius="md" withBorder>
            <Group gap="xs">
              <ThemeIcon variant="light" color="green" size="md">
                <IconCheck size={16} />
              </ThemeIcon>
              <Box>
                <Text fw={700}>{historyStats.success}</Text>
                <Text size="xs" c="dimmed">Exitosas</Text>
              </Box>
            </Group>
          </Paper>
          <Paper p="sm" radius="md" withBorder>
            <Group gap="xs">
              <ThemeIcon variant="light" color="red" size="md">
                <IconX size={16} />
              </ThemeIcon>
              <Box>
                <Text fw={700}>{historyStats.failed}</Text>
                <Text size="xs" c="dimmed">Fallidas</Text>
              </Box>
            </Group>
          </Paper>
          <Paper p="sm" radius="md" withBorder>
            <Group gap="xs">
              <ThemeIcon variant="light" color="yellow" size="md">
                <IconClock size={16} />
              </ThemeIcon>
              <Box>
                <Text fw={700}>{formatDuration(historyStats.avg_duration)}</Text>
                <Text size="xs" c="dimmed">Duración prom.</Text>
              </Box>
            </Group>
          </Paper>
        </SimpleGrid>
      )}

      {/* Filters */}
      <Group>
        <TextInput
          placeholder="Buscar..."
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => { setSearch(e.currentTarget.value); setPage(1); }}
          style={{ flex: 1, maxWidth: 300 }}
        />
        <Select
          placeholder="Estado"
          data={[
            { value: 'hecha', label: 'Hecha' },
            { value: 'failed', label: 'Fallida' },
            { value: 'en_progreso', label: 'En progreso' },
          ]}
          value={status}
          onChange={(v) => { setStatus(v); setPage(1); }}
          clearable
          w={160}
        />
      </Group>

      {/* Table */}
      {isLoading ? (
        <Center py="xl"><Loader /></Center>
      ) : items.length === 0 ? (
        <Center py="xl">
          <Stack align="center" gap="sm">
            <IconHistory size={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">Sin historial</Text>
          </Stack>
        </Center>
      ) : (
        <Paper radius="md" withBorder style={{ overflow: 'auto' }}>
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ cursor: 'pointer' }} onClick={() => handleSort('title')}>
                  Tarea{sortIcon('title')}
                </Table.Th>
                <Table.Th style={{ cursor: 'pointer' }} onClick={() => handleSort('status')}>
                  Estado{sortIcon('status')}
                </Table.Th>
                <Table.Th>Agente</Table.Th>
                <Table.Th style={{ cursor: 'pointer' }} onClick={() => handleSort('duration')}>
                  Duración{sortIcon('duration')}
                </Table.Th>
                <Table.Th style={{ cursor: 'pointer' }} onClick={() => handleSort('created_at')}>
                  Fecha{sortIcon('created_at')}
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item) => (
                <Table.Tr key={item.id}>
                  <Table.Td>
                    <Text size="sm" lineClamp={1}>{item.title}</Text>
                    {item.project_name && (
                      <Text size="xs" c="dimmed">{item.project_name}</Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      size="sm"
                      color={STATUS_COLORS[item.status] || 'gray'}
                    >
                      {item.status}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{item.agent_name || '-'}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatDuration(item.duration)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">
                      {item.created_at
                        ? new Date(item.created_at).toLocaleString('es-ES')
                        : '-'}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}

      {totalPages > 1 && (
        <Group justify="center">
          <Pagination total={totalPages} value={page} onChange={setPage} />
        </Group>
      )}
    </Stack>
  );
}
