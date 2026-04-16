/**
 * Tests for TaskDetailsTab.
 *
 * - PR-37 Resultado markdown: Claude's stdout is markdown; without
 *   react-markdown + remark-gfm, bold/tables/headers would render
 *   literal.
 * - PR-39 failure banner: when the latest backend_run failed and the
 *   task isn't 'hecha', show a red Alert with the error_code + backend
 *   display_name + a button to the runs tab. Suppressed on 'hecha'
 *   because a fallback rescued it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Outlet } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { TaskDetailsTab } from './TaskDetailsTab';
import type { Task } from '../../../shared/types';

function makeTask(overrides: Partial<Task> & Record<string, unknown> = {}): Task {
  return {
    id: 't-1',
    title: 'A task',
    description: '',
    status: 'hecha',
    priority: 'media',
    area: 'proyecto',
    project_id: null,
    scheduled_for: null,
    due_at: null,
    urgent: 0,
    created_at: '2026-04-16T00:00:00Z',
    updated_at: '2026-04-16T00:00:00Z',
    ...overrides,
  } as Task;
}

function wrap(task: Task): ReactNode {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route element={<Outlet context={{ task }} />}>
              <Route index element={<TaskDetailsTab />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>
  );
}

// Silence the labels/attachments fetches that hooks fire on mount.
globalThis.fetch = vi.fn(async () =>
  new Response(JSON.stringify([]), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }),
) as unknown as typeof fetch;

describe('TaskDetailsTab — Resultado markdown', () => {
  afterEach(cleanup);

  it('renders **bold** as a <strong> element, not as literal asterisks', () => {
    const task = makeTask({ executor_output: 'hello **world** done' });
    render(wrap(task));
    // Header still visible.
    expect(screen.getByText('Resultado')).toBeTruthy();
    // The literal "**world**" must NOT survive: react-markdown turns it
    // into a <strong>.
    const strong = screen.getByText('world');
    expect(strong.tagName.toLowerCase()).toBe('strong');
  });

  it('renders GFM tables (executor_output is markdown, not text)', () => {
    const md = [
      '| col1 | col2 |',
      '| ---- | ---- |',
      '| a    | b    |',
    ].join('\n');
    const task = makeTask({ executor_output: md });
    const { container } = render(wrap(task));
    const table = container.querySelector('table');
    expect(table).not.toBeNull();
    // Header row + body row exist.
    expect(container.querySelectorAll('th').length).toBeGreaterThanOrEqual(2);
    expect(container.querySelectorAll('td').length).toBeGreaterThanOrEqual(2);
  });

  it('opens markdown links in a new tab with rel=noopener', () => {
    const task = makeTask({
      executor_output: 'See [docs](https://example.com) for details.',
    });
    const { container } = render(wrap(task));
    const link = container.querySelector('a[href="https://example.com"]');
    expect(link).not.toBeNull();
    expect(link?.getAttribute('target')).toBe('_blank');
    expect(link?.getAttribute('rel')).toContain('noopener');
  });

  it('does not render the Resultado section when executor_output is empty', () => {
    const task = makeTask({ executor_output: '' });
    render(wrap(task));
    expect(screen.queryByText('Resultado')).toBeNull();
  });

  it('shows failure banner when last_run failed and task is not hecha', () => {
    const task = makeTask({
      status: 'pendiente',
      last_run: {
        id: 'r-1',
        status: 'failed',
        outcome: 'failure',
        error_code: 'auth_required',
        finished_at: '2026-04-16T00:00:00Z',
        relation_type: null,
        backend_profile_slug: 'claude_code',
        backend_profile_display_name: 'Claude Code',
      },
    });
    render(wrap(task));
    // Banner title.
    expect(screen.getByText('La última ejecución falló')).toBeTruthy();
    // Error code is visible (not hidden behind a tooltip).
    expect(screen.getByText('auth_required')).toBeTruthy();
    // The backend display name appears so the user knows which one
    // failed — not just an opaque code.
    expect(screen.getByText(/Claude Code falló con/)).toBeTruthy();
    // Action button to jump to runs tab.
    expect(screen.getByRole('button', { name: /ver runs/i })).toBeTruthy();
  });

  it('suppresses failure banner when task.status is hecha (fallback rescued)', () => {
    // A task that ran failure → then fallback succeeded → status
    // ended as 'hecha' must NOT show the banner. Otherwise we're
    // alarming about an error that was already recovered from.
    const task = makeTask({
      status: 'hecha',
      last_run: {
        id: 'r-1',
        status: 'failed',
        outcome: 'failure',
        error_code: 'transient_network',
        finished_at: '2026-04-16T00:00:00Z',
        relation_type: null,
        backend_profile_slug: 'claude_code',
        backend_profile_display_name: 'Claude Code',
      },
    });
    render(wrap(task));
    expect(screen.queryByText('La última ejecución falló')).toBeNull();
  });

  it('does not show failure banner when last_run is null', () => {
    const task = makeTask({ last_run: null });
    render(wrap(task));
    expect(screen.queryByText('La última ejecución falló')).toBeNull();
  });

  it('suppresses failure banner on archived tasks (terminal state)', () => {
    // `archivada` is terminal like `hecha`: the user moved past this
    // task, so showing a red alert on it is noise, not signal.
    const task = makeTask({
      status: 'archivada',
      last_run: {
        id: 'r-1',
        status: 'failed',
        outcome: 'failure',
        error_code: 'timeout',
        finished_at: '2026-04-16T00:00:00Z',
        relation_type: null,
        backend_profile_slug: 'claude_code',
        backend_profile_display_name: 'Claude Code',
      },
    });
    render(wrap(task));
    expect(screen.queryByText('La última ejecución falló')).toBeNull();
  });

  it('shows failure banner on waiting_input (the failure may be why it waits)', () => {
    // A failure that transitions the task to waiting_input is the
    // canonical place where the banner IS useful — explains why the
    // task hasn't progressed.
    const task = makeTask({
      status: 'waiting_input',
      last_run: {
        id: 'r-1',
        status: 'failed',
        outcome: 'failure',
        error_code: 'approval_required',
        finished_at: '2026-04-16T00:00:00Z',
        relation_type: null,
        backend_profile_slug: 'claude_code',
        backend_profile_display_name: 'Claude Code',
      },
    });
    render(wrap(task));
    expect(screen.getByText('La última ejecución falló')).toBeTruthy();
  });

  it('does not show failure banner when last_run succeeded', () => {
    const task = makeTask({
      status: 'hecha',
      last_run: {
        id: 'r-1',
        status: 'succeeded',
        outcome: 'success',
        error_code: null,
        finished_at: '2026-04-16T00:00:00Z',
        relation_type: null,
        backend_profile_slug: 'claude_code',
        backend_profile_display_name: 'Claude Code',
      },
    });
    render(wrap(task));
    expect(screen.queryByText('La última ejecución falló')).toBeNull();
  });

  it('escapes raw HTML in markdown (no script injection)', () => {
    // react-markdown 9.x without rehype-raw must NOT inject raw HTML.
    // The <script> string should appear as literal text, never as a real
    // <script> element in the DOM.
    const task = makeTask({
      executor_output: 'Hi <script>window.__pwned=1</script> there',
    });
    const { container } = render(wrap(task));
    expect(container.querySelector('script')).toBeNull();
    // The literal characters survive as text content somewhere in the
    // result paper (escaped, not interpreted).
    expect(container.textContent).toContain('<script>');
  });
});
