import { useEffect, useState } from 'react';
import { SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useParams } from 'react-router-dom';
import { RunList } from './RunList';
import { RunTimeline } from './RunTimeline';
import { ArtifactList } from './ArtifactList';
import { useTaskRuns } from '../hooks/useRuns';

/** /tasks/:taskId/runs route — list of backend_runs for the task +
 *  granular event timeline of the selected run + the artifacts that
 *  the run produced.
 *
 *  PR-10c extends PR-10a's two-pane layout with a third section: a
 *  table of artifacts scoped to the selected run, rendered below the
 *  grid so timeline + list stay side-by-side on wider viewports. */
export function RunsTab() {
  const { taskId } = useParams<{ taskId: string }>();
  const { data: runs, isLoading } = useTaskRuns(taskId);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Default to the most recent run whenever the list changes and the
  // current selection is no longer valid (empty list or the selected
  // id was filtered out).  Uses the last element because
  // ``list_runs_for_task`` returns oldest first.
  useEffect(() => {
    if (!runs || runs.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    const stillThere = selectedId
      ? runs.some((r) => r.id === selectedId)
      : false;
    if (!stillThere) {
      setSelectedId(runs[runs.length - 1].id);
    }
  }, [runs, selectedId]);

  return (
    <Stack gap="md">
      <div>
        <Title order={5}>Runs</Title>
        <Text size="xs" c="dimmed">
          Histórico de ejecuciones del backend para esta tarea. Cada
          fila es un <code>backend_run</code>; el timeline detalla los
          eventos granulares del run seleccionado.
        </Text>
      </div>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        <RunList
          runs={runs ?? []}
          selectedId={selectedId}
          onSelect={setSelectedId}
          isLoading={isLoading}
        />
        <RunTimeline runId={selectedId} />
      </SimpleGrid>
      <ArtifactList runId={selectedId} />
    </Stack>
  );
}
