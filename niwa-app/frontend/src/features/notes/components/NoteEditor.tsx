import { useState, useEffect } from 'react';
import {
  Modal,
  TextInput,
  Textarea,
  Select,
  Button,
  Stack,
  Group,
  SegmentedControl,
  Box,
  Text,
} from '@mantine/core';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useCreateNote, useUpdateNote, useProjects } from '../../../shared/api/queries';
import type { Note } from '../../../shared/types';

interface Props {
  opened: boolean;
  onClose: () => void;
  note?: Note | null;
}

export function NoteEditor({ opened, onClose, note }: Props) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [tags, setTags] = useState('');
  const [view, setView] = useState('edit');
  const createNote = useCreateNote();
  const updateNote = useUpdateNote();
  const { data: projects } = useProjects();
  const isEditing = !!note;

  const projectOptions = (projects || []).map((p) => ({
    value: String(p.id),
    label: p.name,
  }));

  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setContent(note.content || '');
      setProjectId(note.project_id ? String(note.project_id) : null);
      setTags(note.tags || '');
    } else {
      setTitle('');
      setContent('');
      setProjectId(null);
      setTags('');
    }
    setView('edit');
  }, [note, opened]);

  const handleSave = async () => {
    const data = {
      title,
      content,
      project_id: projectId,
      tags: tags || null,
    };
    if (isEditing) {
      await updateNote.mutateAsync({ id: note.id, ...data });
    } else {
      await createNote.mutateAsync(data);
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

        <Group grow>
          <Select
            label="Proyecto"
            data={projectOptions}
            value={projectId}
            onChange={setProjectId}
            clearable
            placeholder="Sin proyecto"
          />
          <TextInput
            label="Etiquetas"
            value={tags}
            onChange={(e) => setTags(e.currentTarget.value)}
            placeholder="tag1, tag2, tag3"
          />
        </Group>

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
