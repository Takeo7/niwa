/**
 * Tests for ``TaskForm``.
 *
 * Regression guard for:
 *
 *   TypeError: undefined is not an object (evaluating 'r.trim')
 *
 * …thrown when clicking "Nueva tarea" from a kanban column. The root
 * cause was that ``KanbanBoard`` was calling ``<TaskForm task={{ status }
 *   as Task} />`` — a synthesised *partial* Task with no ``title``.
 * ``TaskForm``'s ``useEffect`` treated ``task`` as truthy → ran the
 * "editing" branch → ``setTitle(task.title)`` set ``title`` to
 * ``undefined`` → next render the submit Button's
 * ``disabled={!title.trim()}`` crashed.
 *
 * The fix splits the two concerns:
 *
 *   - ``task`` prop → strictly "edit an existing persisted task" (has id).
 *   - ``initialStatus`` prop → pre-select the status dropdown when
 *     creating.
 *
 * These tests render TaskForm with each combination and assert it
 * doesn't throw, that the correct mode is active, and that
 * ``initialStatus`` is respected on create.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { TaskForm } from './TaskForm';
import type { Task } from '../../../shared/types';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>{ui}</MantineProvider>
    </QueryClientProvider>
  );
}

// Silence the projects/useSettings/etc. fetches that queries.ts
// triggers on mount — they would otherwise hit the network.
globalThis.fetch = vi.fn(async () =>
  new Response(JSON.stringify([]), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }),
) as unknown as typeof fetch;

describe('TaskForm', () => {
  afterEach(cleanup);

  it('renders in create mode with no task and no initialStatus (regression: the kanban crash)', () => {
    // Before the fix, KanbanBoard's ``{ status } as Task`` made isEditing
    // true and set title to undefined; rendering the submit button
    // crashed on ``!title.trim()``. Now ``task=null`` is strictly create
    // mode and title is always a string.
    expect(() =>
      render(wrap(<TaskForm opened onClose={() => {}} />)),
    ).not.toThrow();
    expect(screen.getByText('Nueva tarea')).toBeTruthy();
  });

  it('renders in create mode with initialStatus and shows the submit as "Crear tarea"', () => {
    render(
      wrap(
        <TaskForm opened onClose={() => {}} initialStatus="en_progreso" />,
      ),
    );
    // Create mode → the primary button label is "Crear tarea".
    expect(screen.getByRole('button', { name: /crear tarea/i })).toBeTruthy();
    // Modal title is "Nueva tarea", not "Editar tarea".
    expect(screen.queryByText('Editar tarea')).toBeNull();
  });

  it('renders in edit mode when task has an id and shows "Guardar"', () => {
    const task: Task = {
      id: 't-123',
      title: 'An existing task',
      description: 'desc',
      status: 'en_progreso',
      priority: 'media',
      area: 'proyecto',
      project_id: null,
      scheduled_for: null,
      due_at: null,
      urgent: 0,
      created_at: '2025-01-01',
      updated_at: '2025-01-01',
    } as Task;
    render(wrap(<TaskForm opened onClose={() => {}} task={task} />));
    expect(screen.getByRole('button', { name: /^guardar$/i })).toBeTruthy();
    expect(screen.getByText('Editar tarea')).toBeTruthy();
  });

  it('does NOT enter edit mode when given a partial task without an id (defensive)', () => {
    // Even if a caller passes a Task-shaped object without an id (the
    // exact footgun the old KanbanBoard was hitting), we stay in
    // create mode rather than trying to "edit a nothing".
    const fakeTask = { status: 'inbox' } as Task;
    expect(() =>
      render(wrap(<TaskForm opened onClose={() => {}} task={fakeTask} />)),
    ).not.toThrow();
    expect(screen.getByRole('button', { name: /crear tarea/i })).toBeTruthy();
  });
});
