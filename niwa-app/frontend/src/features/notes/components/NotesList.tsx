import { useState } from 'react';
import {
  Stack,
  Title,
  Group,
  Button,
  TextInput,
  Select,
  Card,
  Text,
  Badge,
  SimpleGrid,
  Loader,
  Center,
  Menu,
  ActionIcon,
} from '@mantine/core';
import {
  IconPlus,
  IconSearch,
  IconNotebook,
  IconDotsVertical,
  IconTrash,
  IconEdit,
} from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';
import { useNotes, useDeleteNote, useProjects } from '../../../shared/api/queries';
import { NoteEditor } from './NoteEditor';
import type { Note } from '../../../shared/types';

export function NotesList() {
  const [search, setSearch] = useState('');
  const [projectFilter, setProjectFilter] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingNote, setEditingNote] = useState<Note | null>(null);
  const { data: notes, isLoading } = useNotes(search || undefined);
  const { data: projects } = useProjects();
  const deleteNote = useDeleteNote();

  const projectOptions = (projects || []).map((p) => ({
    value: String(p.id),
    label: p.name,
  }));

  const filteredNotes = projectFilter
    ? notes?.filter((n) => String(n.project_id) === projectFilter)
    : notes;

  const handleEdit = (note: Note) => {
    setEditingNote(note);
    setEditorOpen(true);
  };

  const handleNew = () => {
    setEditingNote(null);
    setEditorOpen(true);
  };

  const handleDelete = async (note: Note) => {
    if (!window.confirm(`¿Eliminar la nota "${note.title}"?`)) return;
    await deleteNote.mutateAsync(note.id);
    notifications.show({
      title: 'Nota eliminada',
      message: `"${note.title}" ha sido eliminada`,
      color: 'red',
    });
  };

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={3}>Notas</Title>
        <Button leftSection={<IconPlus size={16} />} onClick={handleNew}>
          Nueva nota
        </Button>
      </Group>

      <Group gap="sm">
        <TextInput
          placeholder="Buscar notas..."
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(e) => setSearch(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <Select
          placeholder="Filtrar proyecto"
          data={projectOptions}
          value={projectFilter}
          onChange={setProjectFilter}
          clearable
          w={200}
        />
      </Group>

      {!filteredNotes?.length ? (
        <Center py="xl">
          <Stack align="center" gap="sm">
            <IconNotebook size={48} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed">
              {search || projectFilter ? 'Sin resultados' : 'Sin notas aún'}
            </Text>
          </Stack>
        </Center>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          {filteredNotes.map((note) => {
            const tags = note.tags
              ? note.tags.split(',').map((t) => t.trim()).filter(Boolean)
              : [];
            return (
              <Card
                key={note.id}
                withBorder
                radius="md"
                style={{ cursor: 'pointer' }}
                onClick={() => handleEdit(note)}
              >
                <Group justify="space-between" mb="xs" wrap="nowrap">
                  <Text fw={600} lineClamp={1} style={{ flex: 1 }}>
                    {note.title}
                  </Text>
                  <Menu shadow="md" width={160}>
                    <Menu.Target>
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <IconDotsVertical size={14} />
                      </ActionIcon>
                    </Menu.Target>
                    <Menu.Dropdown>
                      <Menu.Item
                        leftSection={<IconEdit size={14} />}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEdit(note);
                        }}
                      >
                        Editar
                      </Menu.Item>
                      <Menu.Item
                        leftSection={<IconTrash size={14} />}
                        color="red"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(note);
                        }}
                      >
                        Eliminar
                      </Menu.Item>
                    </Menu.Dropdown>
                  </Menu>
                </Group>
                <Text size="sm" c="dimmed" lineClamp={3}>
                  {note.content || 'Sin contenido'}
                </Text>
                {tags.length > 0 && (
                  <Group gap={4} mt="xs">
                    {tags.slice(0, 3).map((tag) => (
                      <Badge key={tag} size="xs" variant="light">
                        {tag}
                      </Badge>
                    ))}
                  </Group>
                )}
                <Group justify="space-between" mt="xs">
                  <Text size="xs" c="dimmed">
                    {new Date(note.updated_at).toLocaleDateString('es-ES')}
                  </Text>
                  {note.project_name && (
                    <Text size="xs" c="dimmed">
                      {note.project_name}
                    </Text>
                  )}
                </Group>
              </Card>
            );
          })}
        </SimpleGrid>
      )}

      <NoteEditor
        opened={editorOpen}
        onClose={() => setEditorOpen(false)}
        note={editingNote}
      />
    </Stack>
  );
}
