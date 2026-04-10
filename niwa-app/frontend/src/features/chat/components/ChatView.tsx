import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Box,
  Stack,
  Title,
  Text,
  Paper,
  ScrollArea,
  NavLink,
  ActionIcon,
  Group,
  Loader,
  Center,
  Divider,
} from '@mantine/core';
import {
  IconPlus,
  IconMessageCircle,
  IconTrash,
} from '@tabler/icons-react';
import { useAppStore } from '../../../shared/stores/app';
import {
  useChatSessions,
  useChatMessages,
  useCreateChatSession,
  useSendChatMessage,
  useDeleteChatSession,
} from '../hooks/useChat';
import { MessageBubble } from './MessageBubble';
import { ChatInput } from './ChatInput';

export function ChatView() {
  const { activeChat, setActiveChat } = useAppStore();
  const { data: sessions, isLoading: sessionsLoading } = useChatSessions();
  const { data: messages, isLoading: messagesLoading } = useChatMessages(activeChat);
  const createSession = useCreateChatSession();
  const sendMessage = useSendChatMessage();
  const deleteSession = useDeleteChatSession();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [idleTicks, setIdleTicks] = useState(0);
  const lastMsgCount = useRef(0);

  // Auto-select first session
  useEffect(() => {
    if (!activeChat && sessions?.length) {
      setActiveChat(sessions[0].id);
    }
  }, [sessions, activeChat, setActiveChat]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({
        top: scrollRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
    // Idle timeout: reset when new messages arrive
    const count = messages?.length ?? 0;
    if (count !== lastMsgCount.current) {
      lastMsgCount.current = count;
      setIdleTicks(0);
    }
  }, [messages]);

  // Idle timeout: increment ticks every 3s (polling interval)
  useEffect(() => {
    if (!activeChat) return;
    const interval = setInterval(() => {
      setIdleTicks((t) => t + 1);
    }, 3000);
    return () => clearInterval(interval);
  }, [activeChat]);

  // Stop polling after ~2 min idle (40 ticks * 3s = 120s)
  const isIdle = idleTicks > 40;

  const handleNewChat = async () => {
    const session = await createSession.mutateAsync({
      title: 'Nueva conversación',
    });
    setActiveChat(session.id);
    setIdleTicks(0);
  };

  const handleSend = useCallback(async (content: string) => {
    setIdleTicks(0);
    // Auto-create session if none exist
    if (!activeChat) {
      const session = await createSession.mutateAsync({
        title: content.slice(0, 50),
      });
      setActiveChat(session.id);
      sendMessage.mutate({ session_id: session.id, content });
      return;
    }
    sendMessage.mutate({ session_id: activeChat, content });
  }, [activeChat, createSession, sendMessage, setActiveChat]);

  const handleDeleteSession = (id: string) => {
    deleteSession.mutate(id);
    if (activeChat === id) {
      setActiveChat(null);
    }
  };

  return (
    <Box style={{ display: 'flex', height: 'calc(100vh - 50px - 32px)', gap: 0 }}>
      {/* Sessions sidebar */}
      <Paper
        w={260}
        p="xs"
        radius={0}
        style={{
          borderRight: '1px solid var(--mantine-color-dark-4)',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
        }}
      >
        <Group justify="space-between" mb="xs" px="xs">
          <Title order={5}>Conversaciones</Title>
          <ActionIcon
            variant="light"
            size="sm"
            onClick={handleNewChat}
            loading={createSession.isPending}
          >
            <IconPlus size={16} />
          </ActionIcon>
        </Group>
        <Divider mb="xs" />
        <ScrollArea style={{ flex: 1 }}>
          {sessionsLoading ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : sessions?.length === 0 ? (
            <Text size="sm" c="dimmed" ta="center" py="md">
              Sin conversaciones
            </Text>
          ) : (
            <Stack gap={2}>
              {sessions?.map((s) => (
                <Group key={s.id} gap={0} wrap="nowrap">
                  <NavLink
                    label={s.title}
                    description={new Date(s.updated_at).toLocaleDateString('es-ES')}
                    leftSection={<IconMessageCircle size={16} />}
                    active={activeChat === s.id}
                    onClick={() => { setActiveChat(s.id); setIdleTicks(0); }}
                    variant="light"
                    style={{ flex: 1, borderRadius: 'var(--mantine-radius-md)' }}
                    styles={{ label: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                  />
                  <ActionIcon
                    variant="subtle"
                    size="sm"
                    color="red"
                    onClick={() => handleDeleteSession(s.id)}
                    title="Eliminar"
                  >
                    <IconTrash size={14} />
                  </ActionIcon>
                </Group>
              ))}
            </Stack>
          )}
        </ScrollArea>
        {isIdle && activeChat && (
          <Text size="xs" c="dimmed" ta="center" py={4}>
            Sondeo pausado por inactividad
          </Text>
        )}
      </Paper>

      {/* Chat area */}
      <Box style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {!activeChat && !sessions?.length ? (
          <Center style={{ flex: 1 }}>
            <Stack align="center" gap="sm">
              <IconMessageCircle size={48} color="var(--mantine-color-dimmed)" />
              <Text c="dimmed">
                Escribe un mensaje para iniciar una conversación
              </Text>
            </Stack>
          </Center>
        ) : !activeChat ? (
          <Center style={{ flex: 1 }}>
            <Stack align="center" gap="sm">
              <IconMessageCircle size={48} color="var(--mantine-color-dimmed)" />
              <Text c="dimmed">
                Selecciona una conversación o crea una nueva
              </Text>
            </Stack>
          </Center>
        ) : (
          <>
            <ScrollArea
              style={{ flex: 1 }}
              viewportRef={scrollRef}
              p="md"
            >
              {messagesLoading ? (
                <Center py="xl">
                  <Loader />
                </Center>
              ) : messages?.length === 0 ? (
                <Center py="xl">
                  <Text c="dimmed">Sin mensajes aún. Escribe algo para comenzar.</Text>
                </Center>
              ) : (
                <Stack gap={4}>
                  {messages?.map((msg) => (
                    <MessageBubble key={msg.id} message={msg} />
                  ))}
                </Stack>
              )}
            </ScrollArea>
            <Box p="md" pt="xs">
              <ChatInput
                onSend={handleSend}
                loading={sendMessage.isPending}
              />
            </Box>
          </>
        )}
        {/* Send even without activeChat */}
        {!activeChat && (
          <Box p="md" pt="xs">
            <ChatInput
              onSend={handleSend}
              loading={sendMessage.isPending || createSession.isPending}
            />
          </Box>
        )}
      </Box>
    </Box>
  );
}
