import { Box, Group, Stack, Text } from '@mantine/core';
import { RelativeTime } from '../../../shared/components/RelativeTime';
import type { Turn } from '../types';
import { ActionChips } from './ActionChips';

interface Props {
  turn: Turn;
}

/**
 * Un turn = mensaje del usuario + respuesta del assistant.  Registro
 * editorial: sin burbujas, sin avatares, texto plano, border-hairline
 * como separador.  Ver DECISIONS-LOG PR-10e Dec 7.
 */
export function TurnView({ turn }: Props) {
  return (
    <Box
      style={{
        borderTop: '1px solid var(--mantine-color-default-border)',
        paddingTop: 12,
      }}
    >
      <Stack gap={10}>
        <Group gap="xs" align="baseline" wrap="nowrap">
          <Text
            size="xs"
            c="dimmed"
            fw={600}
            style={{ minWidth: 40 }}
          >
            Tú
          </Text>
          <RelativeTime iso={turn.user_created_at} />
        </Group>
        <Text
          size="sm"
          style={{
            whiteSpace: 'pre-wrap',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {turn.user_message}
        </Text>

        <Group gap="xs" align="baseline" wrap="nowrap" mt={4}>
          <Text
            size="xs"
            c="dimmed"
            fw={600}
            style={{ minWidth: 40 }}
          >
            Niwa
          </Text>
          {turn.assistant_created_at ? (
            <RelativeTime iso={turn.assistant_created_at} />
          ) : turn.in_flight ? (
            <Text size="xs" c="dimmed">pensando…</Text>
          ) : null}
        </Group>
        {turn.in_flight ? (
          <AssistantSkeleton />
        ) : turn.error ? (
          <Text
            size="sm"
            c="red"
            style={{ whiteSpace: 'pre-wrap' }}
          >
            {turn.error_message || turn.error}
          </Text>
        ) : (
          <Text
            size="sm"
            style={{
              whiteSpace: 'pre-wrap',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {turn.assistant_message || (
              <Text span c="dimmed" size="sm">(sin respuesta)</Text>
            )}
          </Text>
        )}

        <ActionChips turn={turn} />
      </Stack>
    </Box>
  );
}

/**
 * Indicador sutil mientras el turn está en vuelo.  No es un spinner
 * centrado (el prompt lo prohíbe) — es una línea dimmed con tres
 * puntos animados vía CSS.
 */
function AssistantSkeleton() {
  return (
    <Box
      style={{
        height: 18,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Text size="sm" c="dimmed" style={{ letterSpacing: 2 }}>
        · · ·
      </Text>
    </Box>
  );
}
