/**
 * Tests for TaskDetailsTab — Resultado section markdown rendering (PR-37).
 *
 * Bug 31 (docs/BUGS-FOUND.md): Claude's stdout is markdown but was being
 * rendered with `whiteSpace: 'pre-wrap'` — bold/tables/headers showed up as
 * literal `**bold**`, raw pipes, etc. Fix swaps in `react-markdown` +
 * `remark-gfm` (already used by NoteEditor; no new deps).
 *
 * These tests fail without the fix (the literal string would be a single
 * text node, no `<strong>` / `<table>` would be present).
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
