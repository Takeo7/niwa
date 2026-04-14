import { useEffect, useRef, useState } from 'react';
import { Box, Group, Textarea, Button, Text } from '@mantine/core';
import { IconSend } from '@tabler/icons-react';

interface Props {
  onSend: (message: string) => void | Promise<void>;
  loading: boolean;
  disabled?: boolean;
  /** Texto mostrado cuando disabled (p.ej. falta seleccionar proyecto). */
  disabledReason?: string;
}

/**
 * Input del chat.  Textarea auto-expand (Mantine autosize), envío con
 * Ctrl+Enter o Cmd+Enter (Enter solo inserta newline, como en editores
 * técnicos — Linear, Raycast).  Shift+Enter también inserta newline.
 */
export function MessageInput({
  onSend, loading, disabled, disabledReason,
}: Props) {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);

  // Autofocus al mount y cada vez que vuelve a estar habilitado.
  useEffect(() => {
    if (!disabled && !loading) {
      ref.current?.focus();
    }
  }, [disabled, loading]);

  const trimmed = value.trim();
  const canSend = !disabled && !loading && trimmed.length > 0;

  const submit = async () => {
    if (!canSend) return;
    const toSend = trimmed;
    setValue('');
    await onSend(toSend);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+Enter o Cmd+Enter envía.  Shift+Enter o Enter solo mete
    // salto de línea (comportamiento default de textarea).
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <Box
      style={{
        borderTop: '1px solid var(--mantine-color-default-border)',
        paddingTop: 10,
      }}
    >
      <Group gap="xs" align="flex-end" wrap="nowrap">
        <Textarea
          ref={ref}
          placeholder={
            disabled
              ? (disabledReason ?? 'Chat deshabilitado')
              : 'Escribe un mensaje.  Ctrl+Enter para enviar.'
          }
          value={value}
          onChange={(e) => setValue(e.currentTarget.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || loading}
          autosize
          minRows={1}
          maxRows={8}
          style={{ flex: 1 }}
          aria-label="Mensaje"
        />
        <Button
          variant="filled"
          size="sm"
          leftSection={<IconSend size={14} />}
          onClick={() => void submit()}
          loading={loading}
          disabled={!canSend}
        >
          Enviar
        </Button>
      </Group>
      <Text size="xs" c="dimmed" mt={4} style={{ textAlign: 'right' }}>
        Ctrl+Enter / ⌘+Enter para enviar
      </Text>
    </Box>
  );
}
