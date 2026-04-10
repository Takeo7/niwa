import { useState, useEffect } from 'react';
import {
  Modal,
  TextInput,
  Textarea,
  Button,
  Stack,
  Group,
  SegmentedControl,
  Box,
  Text,
} from '@mantine/core';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useCreateNote, useUpdateNote } from '../../../shared/api/queries';
import type { Note } from '../../../shared/types';

interface Props {
  opened: boolean;
  onClose: () => void;
  note?: Note | null;
}

export function NoteEditor({ opened, onClose, note }: Props) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [view, setView] = useState('edit');
  const createNote = useCreateNote();
  const updateNote = useUpdateNote();
  const isEditing = !!note;

  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setContent(note.content || '');
    } else {
      setTitle('');
      setContent('');
    }
    setView('edit');
  }, [note, opened]);

  const handleSave = async () => {
    if (isEditing) {
      await updateNote.mutateAsync({ id: note.id, title, content });
    } else {
      await createNote.mutateAsync({ title, content });
    }
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={isEditing ? 'Editar nota' : 'Nueva nota'}
      size="xl"
    >
      <Stack gap="sm">
        <TextInput
          label="Título"
          value={title}
          onChange={(e) => setTitle(e.currentTarget.value)}
          placeholder="Título de la nota"
          required
        />

        <SegmentedControl
          data={[
            { label: 'Editar', value: 'edit' },
            { label: 'Vista previa', value: 'preview' },
          ]}
          value={view}
          onChange={setView}
          size="xs"
        />

        {view === 'edit' ? (
          <Textarea
            label="Contenido (Markdown)"
            value={content}
            onChange={(e) => setContent(e.currentTarget.value)}
            minRows={12}
            maxRows={24}
            autosize
            placeholder="Escribe en Markdown..."
            styles={{
              input: { fontFamily: 'monospace' },
            }}
          />
        ) : (
          <Box
            p="md"
            style={{
              border: '1px solid var(--mantine-color-dark-4)',
              borderRadius: 'var(--mantine-radius-md)',
              minHeight: 200,
            }}
          >
            {content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            ) : (
              <Text c="dimmed" size="sm">
                Sin contenido
              </Text>
            )}
          </Box>
        )}

        <Group justify="flex-end" mt="sm">
          <Button variant="subtle" onClick={onClose}>
            Cancelar
          </Button>
          <Button
            onClick={handleSave}
            loading={createNote.isPending || updateNote.isPending}
            disabled={!title.trim()}
          >
            {isEditing ? 'Guardar' : 'Crear nota'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
