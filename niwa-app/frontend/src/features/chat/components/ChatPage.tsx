import { Box, Text, Title, Stack } from '@mantine/core';

/**
 * Chat web v0.2 sobre assistant_turn — scaffold mínimo.
 *
 * El contenido real se construye en commits siguientes de PR-10e
 * (useChat hook, MessageList, MessageInput, TurnView).
 */
export function ChatPage() {
  return (
    <Box p="md">
      <Stack gap="xs">
        <Title order={3}>Chat</Title>
        <Text c="dimmed" size="sm">
          El chat web v0.2 se construye sobre assistant_turn.
        </Text>
      </Stack>
    </Box>
  );
}
