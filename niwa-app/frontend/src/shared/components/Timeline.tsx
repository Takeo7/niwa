import { type ReactNode } from 'react';
import { Box, Group, Paper, Stack, Text } from '@mantine/core';
import { RelativeTime } from './RelativeTime';

export interface TimelineItem {
  id: string;
  /** Semantic label (e.g. ``tool_use``, ``assistant_message``). */
  kind: string;
  /** Displayed next to the dot in the header row. */
  title?: ReactNode;
  timestamp?: string | null;
  /** Main body content.  Raw strings render as dimmed paragraphs;
   * ReactNode passes through unchanged. */
  body?: ReactNode;
  /** Optional pre-formatted JSON or raw payload block. */
  payload?: string | null;
}

// Dot palette per event kind.  Mirrors the event_types the Claude
// adapter emits in PR-04 (Decision 7).  Unknown kinds fall back to
// neutral grey.
const KIND_COLORS: Record<string, string> = {
  system_init: 'var(--mantine-color-gray-6)',
  assistant_message: 'var(--mantine-color-blue-6)',
  tool_use: 'var(--mantine-color-violet-6)',
  tool_result: 'var(--mantine-color-violet-4)',
  result: 'var(--mantine-color-teal-6)',
  error: 'var(--mantine-color-red-6)',
  fallback_escalation: 'var(--mantine-color-orange-6)',
  raw_output: 'var(--mantine-color-gray-5)',
};

interface Props {
  items: TimelineItem[];
  empty?: ReactNode;
}

export function Timeline({ items, empty }: Props) {
  if (!items.length) {
    return (
      <Box py="md">
        <Text size="sm" c="dimmed" ta="center">
          {empty ?? 'Sin eventos'}
        </Text>
      </Box>
    );
  }
  return (
    <Stack gap={0} style={{ position: 'relative' }}>
      {items.map((item, idx) => (
        <Box key={item.id} style={{ position: 'relative' }}>
          {/* Continuous rail */}
          {idx < items.length - 1 && (
            <Box
              style={{
                position: 'absolute',
                left: 5,
                top: 14,
                bottom: -10,
                width: 1,
                background: 'var(--mantine-color-default-border)',
              }}
            />
          )}
          <Group
            align="flex-start"
            gap="sm"
            wrap="nowrap"
            py={6}
            style={{ position: 'relative' }}
          >
            <Box
              style={{
                width: 11,
                height: 11,
                borderRadius: '50%',
                background: KIND_COLORS[item.kind] ??
                  'var(--mantine-color-gray-5)',
                flexShrink: 0,
                marginTop: 6,
                outline: '2px solid var(--mantine-color-body)',
              }}
            />
            <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
              <Group gap="xs" justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
                  <Text
                    size="xs"
                    fw={600}
                    c="dimmed"
                    tt="uppercase"
                    style={{ letterSpacing: '0.04em' }}
                  >
                    {item.kind}
                  </Text>
                  {item.title && (
                    <Text size="sm" lineClamp={1}>
                      {item.title}
                    </Text>
                  )}
                </Group>
                {item.timestamp && (
                  <RelativeTime iso={item.timestamp} />
                )}
              </Group>
              {item.body && (
                <Text
                  size="sm"
                  c="dimmed"
                  style={{ whiteSpace: 'pre-wrap' }}
                >
                  {item.body}
                </Text>
              )}
              {item.payload && (
                <Paper
                  withBorder
                  radius="sm"
                  p={6}
                  bg="var(--mantine-color-default-hover)"
                >
                  <Text
                    size="xs"
                    ff="monospace"
                    style={{
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                    }}
                  >
                    {item.payload}
                  </Text>
                </Paper>
              )}
            </Stack>
          </Group>
        </Box>
      ))}
    </Stack>
  );
}
