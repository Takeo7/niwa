import { useEffect, useRef } from 'react';
import { Box, Stack, Text } from '@mantine/core';
import type { Turn } from '../types';
import { TurnView } from './TurnView';

interface Props {
  turns: Turn[];
  /** Si true, muestra un placeholder "cargando historial…" en lugar
   *  del vacío. */
  historyLoading?: boolean;
}

/**
 * Lista vertical de turns.  Scroll contenedor externo (ChatPage) —
 * este componente sólo se encarga del layout interno y del auto-scroll
 * cuando llega un turn nuevo.
 */
export function MessageList({ turns, historyLoading }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, turns[turns.length - 1]?.assistant_message]);

  if (historyLoading && turns.length === 0) {
    return (
      <Box py="md">
        <Text size="sm" c="dimmed">Cargando historial…</Text>
      </Box>
    );
  }

  if (turns.length === 0) {
    return (
      <Box py="md">
        <Text size="sm" c="dimmed">
          Sin mensajes aún. Escribe algo para empezar.
        </Text>
      </Box>
    );
  }

  return (
    <Stack gap="md" py="xs">
      {turns.map((t) => (
        <TurnView key={t.id} turn={t} />
      ))}
      <div ref={bottomRef} />
    </Stack>
  );
}
