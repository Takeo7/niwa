import { useEffect, useRef } from 'react';
import {
  Stack,
  Paper,
  Text,
  Group,
  Select,
  Button,
  ScrollArea,
  Loader,
  Center,
  Code,
  Box,
} from '@mantine/core';
import { IconRefresh, IconFileText } from '@tabler/icons-react';
import { useState } from 'react';
import { useLogs } from '../../../shared/api/queries';

const LOG_SOURCES = [
  { value: 'app', label: 'App' },
  { value: 'executor', label: 'Executor' },
  { value: 'mcp', label: 'MCP' },
  { value: 'gateway', label: 'Gateway' },
  { value: 'sync', label: 'Sync' },
];

function getLogLevel(line: string): string {
  const upper = line.toUpperCase();
  if (upper.includes('ERROR') || upper.includes('CRITICAL')) return 'error';
  if (upper.includes('WARNING') || upper.includes('WARN')) return 'warning';
  if (upper.includes('INFO')) return 'info';
  if (upper.includes('DEBUG')) return 'debug';
  return 'default';
}

const LEVEL_COLORS: Record<string, string> = {
  error: 'var(--mantine-color-red-6)',
  warning: 'var(--mantine-color-yellow-6)',
  info: 'var(--mantine-color-green-6)',
  debug: 'var(--mantine-color-gray-6)',
  default: 'var(--mantine-color-text)',
};

export function LogsPanel() {
  const [source, setSource] = useState('app');
  const { data, isLoading, refetch } = useLogs(source, 200);
  const scrollRef = useRef<HTMLDivElement>(null);

  const lines: string[] = data?.lines ?? [];

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, [lines]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Group gap="xs">
          <IconFileText size={20} />
          <Text fw={600} size="lg">Registros</Text>
        </Group>
        <Group gap="xs">
          <Select
            data={LOG_SOURCES}
            value={source}
            onChange={(v) => setSource(v || 'app')}
            w={140}
            size="sm"
          />
          <Button
            variant="light"
            leftSection={<IconRefresh size={16} />}
            onClick={() => refetch()}
            size="sm"
          >
            Actualizar
          </Button>
        </Group>
      </Group>

      <Paper
        radius="md"
        withBorder
        style={{ backgroundColor: 'var(--mantine-color-dark-8)' }}
      >
        {isLoading ? (
          <Center py="xl"><Loader /></Center>
        ) : lines.length === 0 ? (
          <Center py="xl">
            <Text c="dimmed">Sin registros disponibles</Text>
          </Center>
        ) : (
          <ScrollArea h={500} viewportRef={scrollRef} p="xs">
            <Code block style={{ backgroundColor: 'transparent', fontSize: 12 }}>
              {lines.map((line, i) => {
                const rawLine = typeof line === 'string' ? line : String(line);
                const level = getLogLevel(rawLine);
                return (
                  <Box
                    key={i}
                    component="div"
                    style={{
                      color: LEVEL_COLORS[level],
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                      lineHeight: 1.5,
                    }}
                  >
                    {rawLine}
                  </Box>
                );
              })}
            </Code>
          </ScrollArea>
        )}
      </Paper>
    </Stack>
  );
}
