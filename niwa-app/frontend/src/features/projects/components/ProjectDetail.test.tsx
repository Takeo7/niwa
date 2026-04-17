/**
 * Tests for ``ProjectDetail`` (PR-53).
 *
 * The previous UI had no way to:
 *   - edit ``project.directory`` (the Edit modal in ``ProjectList`` only
 *     had name + description),
 *   - create a task that pre-selected the current project,
 *   - navigate from a task row in the project to the full task detail.
 *
 * These tests pin the new behaviour (buttons present, DeployCard falls
 * back to "Configurar directorio" when directory is empty, task rows
 * are focusable as links).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import {
  render,
  screen,
  cleanup,
  waitFor,
  fireEvent,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { ProjectDetail } from './ProjectDetail';

function wrap(ui: ReactNode, initialSlug = 'demo-proj') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <MemoryRouter initialEntries={[`/projects/${initialSlug}`]}>
          <Routes>
            <Route path="/projects/:slug" element={ui} />
            <Route path="/tasks/:taskId" element={<div>TASK PAGE {/* sentinel */}</div>} />
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>
  );
}

const EMPTY_CAPABILITY = {
  project_id: 'p-1',
  is_default: true,
  profile: {
    repo_mode: 'read',
    shell_mode: 'none',
    web_mode: 'none',
    network_mode: 'off',
    shell_whitelist_json: '[]',
    filesystem_scope_json: '[]',
    secrets_scope_json: '[]',
    resource_budget_json: '{}',
  },
};

function mockFetch(project: Record<string, unknown>, tasks: unknown[] = []) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/capability-profile')) {
      return new Response(JSON.stringify(EMPTY_CAPABILITY), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/uploads')) {
      return new Response(JSON.stringify({ files: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/tree')) {
      return new Response(JSON.stringify({ tree: [], root_file_count: 0, truncated: false }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/api/projects/demo-proj') || url.includes('/api/projects/p-1')) {
      return new Response(JSON.stringify(project), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/api/projects')) {
      return new Response(JSON.stringify([project]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/api/tasks')) {
      return new Response(JSON.stringify(tasks), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.includes('/api/deployments')) {
      return new Response(JSON.stringify({ deployments: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response('{}', { status: 200 });
  }) as unknown as typeof fetch;
}

const baseProject = {
  id: 'p-1',
  slug: 'demo-proj',
  name: 'Demo',
  description: '',
  area: 'proyecto',
  active: 1,
  open_tasks: 0,
  done_tasks: 0,
  total_tasks: 0,
  created_at: '2026-04-17T00:00:00Z',
  updated_at: '2026-04-17T00:00:00Z',
};

describe('ProjectDetail (PR-53)', () => {
  afterEach(cleanup);

  it('muestra el botón "Nueva tarea" y "Editar" en el header', async () => {
    mockFetch({ ...baseProject, directory: '/home/niwa/projects/demo' });
    render(wrap(<ProjectDetail />));
    await waitFor(() => expect(screen.getByText('Demo')).toBeTruthy());
    expect(screen.getByRole('button', { name: /nueva tarea/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^editar$/i })).toBeTruthy();
  });

  it('sin directory, el DeployCard muestra "Configurar directorio"', async () => {
    mockFetch({ ...baseProject, directory: '' });
    render(wrap(<ProjectDetail />));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /configurar directorio/i }),
      ).toBeTruthy(),
    );
  });

  it('TaskRow del tab Tareas es clickable y navega a /tasks/:id', async () => {
    mockFetch(
      { ...baseProject, directory: '/home/niwa/projects/demo', total_tasks: 1, open_tasks: 1 },
      [
        {
          id: 't-42',
          title: 'Mi tarea',
          status: 'pendiente',
          priority: 'media',
          project_id: 'p-1',
          project_name: 'Demo',
          project_slug: 'demo-proj',
          urgent: 0,
          created_at: '2026-04-17',
          updated_at: '2026-04-17',
        },
      ],
    );
    render(wrap(<ProjectDetail />));
    await waitFor(() => expect(screen.getByText('Demo')).toBeTruthy());
    // Switch to Tasks tab.
    fireEvent.click(screen.getByRole('tab', { name: /tareas/i }));
    const row = await screen.findByRole('link', { name: /abrir tarea mi tarea/i });
    fireEvent.click(row);
    await waitFor(() =>
      expect(screen.getByText(/TASK PAGE/i)).toBeTruthy(),
    );
  });
});
