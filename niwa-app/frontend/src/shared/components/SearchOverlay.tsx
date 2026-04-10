import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Spotlight } from '@mantine/spotlight';
import type { SpotlightActionData } from '@mantine/spotlight';
import {
  IconSearch,
  IconChecklist,
  IconFolders,
  IconNotebook,
} from '@tabler/icons-react';
import { useSearch } from '../api/queries';

const TYPE_ICONS: Record<string, React.ReactNode> = {
  task: <IconChecklist size={18} />,
  project: <IconFolders size={18} />,
  note: <IconNotebook size={18} />,
};

export function SearchOverlay() {
  const [query, setQuery] = useState('');
  const { data: results } = useSearch(query);
  const navigate = useNavigate();

  const actions: SpotlightActionData[] = [];

  if (results?.tasks?.length) {
    for (const t of results.tasks) {
      actions.push({
        id: `task-${t.id}`,
        label: t.title,
        description: `Tarea - ${t.status}`,
        leftSection: TYPE_ICONS.task,
        onClick: () => navigate('/tasks'),
      });
    }
  }

  if (results?.projects?.length) {
    for (const p of results.projects) {
      actions.push({
        id: `project-${p.id}`,
        label: p.name,
        description: 'Proyecto',
        leftSection: TYPE_ICONS.project,
        onClick: () => navigate(`/projects/${p.slug}`),
      });
    }
  }

  if (results?.notes?.length) {
    for (const n of results.notes) {
      actions.push({
        id: `note-${n.id}`,
        label: n.title,
        description: 'Nota',
        leftSection: TYPE_ICONS.note,
        onClick: () => navigate('/notes'),
      });
    }
  }

  return (
    <Spotlight
      actions={actions}
      nothingFound={query.length >= 2 ? 'Sin resultados' : 'Escribe para buscar...'}
      searchProps={{
        leftSection: <IconSearch size={20} />,
        placeholder: 'Buscar tareas, proyectos, notas...',
      }}
      query={query}
      onQueryChange={setQuery}
      shortcut="/"
    />
  );
}
