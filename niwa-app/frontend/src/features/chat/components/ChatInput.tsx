import { useState, useRef } from 'react';
import { Group, Textarea, ActionIcon } from '@mantine/core';
import { IconSend } from '@tabler/icons-react';

interface Props {
  onSend: (message: string) => void;
  loading?: boolean;
}

export function ChatInput({ onSend, loading }: Props) {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue('');
    ref.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Group gap="xs" align="flex-end" wrap="nowrap">
      <Textarea
        ref={ref}
        placeholder="Escribe un mensaje..."
        value={value}
        onChange={(e) => setValue(e.currentTarget.value)}
        onKeyDown={handleKeyDown}
        autosize
        minRows={1}
        maxRows={6}
        style={{ flex: 1 }}
        disabled={loading}
      />
      <ActionIcon
        size="lg"
        variant="filled"
        onClick={handleSend}
        disabled={!value.trim() || loading}
        loading={loading}
      >
        <IconSend size={18} />
      </ActionIcon>
    </Group>
  );
}
