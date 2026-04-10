import { useEffect, useRef } from 'react';
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
  Menu,
} from '@mantine/core';
import {
  IconPlus,
  IconMessageCircle,
  IconDotsVertical,
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
  }, [messages]);

  const handleNewChat = async () => {
    const session = await createSession.mutateAsync({
      title: 'Nueva conversación',
    });
    setActiveChat(session.id);
  };

  const handleSend = (content: string) => {
    if (!activeChat) return;
    sendMessage.mutate({ session_id: activeChat, content });
  };

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
                    onClick={() => setActiveChat(s.id)}
                    variant="light"
                    style={{ flex: 1, borderRadius: 'var(--mantine-radius-md)' }}
                    styles={{ label: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                  />
                  <Menu shadow="md" width={160}>
                    <Menu.Target>
                      <ActionIcon variant="subtle" size="sm">
                        <IconDotsVertical size={14} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item
                        leftSection={<IconTrash size={14} />}
                        color="red"
                        onClick={() => handleDeleteSession(s.id)}
                      >
                        Eliminar
                      </Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                </Group>
              ))}
            </Stack>
          )}
        </ScrollArea>
      </Paper>

      {/* Chat area */}
      <Box style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {!activeChat ? (
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
      </Box>
    </Box>
  );
}
