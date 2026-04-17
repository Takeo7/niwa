/**
 * Tests for ``DeploymentsPanel`` (PR-47).
 *
 * The panel lists active deployments fetched from ``GET /api/deployments``
 * and exposes a "Despublicar" button per row that posts to
 * ``/api/projects/:id/undeploy``.
 *
 * These tests cover:
 *   - Empty state ("No hay ningún proyecto publicado…")
 *   - Rendered row shows slug, url (anchor), directory, status badge
 *   - Undeploy button fires a POST to the correct path
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { DeploymentsPanel } from './DeploymentsPanel';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        {ui}
      </MantineProvider>
    </QueryClientProvider>
  );
}

function mockFetch(responses: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    for (const [path, body] of Object.entries(responses)) {
      if (url.includes(path)) {
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    }
    return new Response('{}', { status: 200 });
  }) as unknown as typeof fetch;
}

describe('DeploymentsPanel', () => {
  afterEach(cleanup);

  it('muestra estado vacío cuando no hay deployments', async () => {
    mockFetch({ '/api/deployments': { deployments: [] } });
    render(wrap(<DeploymentsPanel />));
    await waitFor(() =>
      expect(screen.getByText(/No hay ningún proyecto publicado/i)).toBeTruthy(),
    );
  });

  it('renderiza un row por deployment con slug, url y directory', async () => {
    mockFetch({
      '/api/deployments': {
        deployments: [
          {
            id: 'd1',
            project_id: 'p1',
            slug: 'mi-sitio',
            directory: '/data/projects/mi-sitio',
            url: 'https://mi-sitio.example.com/',
            status: 'active',
            deployed_at: '2026-04-17T10:00:00Z',
            updated_at: '2026-04-17T10:00:00Z',
          },
        ],
      },
    });
    render(wrap(<DeploymentsPanel />));
    await waitFor(() => expect(screen.getByText('mi-sitio')).toBeTruthy());
    expect(screen.getByText(/\/data\/projects\/mi-sitio/)).toBeTruthy();
    const link = screen.getByRole('link') as HTMLAnchorElement;
    expect(link.href).toContain('mi-sitio.example.com');
    expect(link.target).toBe('_blank');
    expect(link.rel).toContain('noopener');
  });

  it('al pulsar "Despublicar" hace POST a /api/projects/:project_id/undeploy', async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/deployments')) {
        return new Response(
          JSON.stringify({
            deployments: [
              {
                id: 'd1',
                project_id: 'p1',
                slug: 'mi-sitio',
                directory: '/d',
                url: 'https://mi-sitio.example.com/',
                status: 'active',
                deployed_at: '2026-04-17T10:00:00Z',
                updated_at: '2026-04-17T10:00:00Z',
              },
            ],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      if (url.includes('/undeploy')) {
        calls.push(`${init?.method ?? 'GET'} ${url}`);
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('{}', { status: 200 });
    }) as unknown as typeof fetch;

    render(wrap(<DeploymentsPanel />));
    const btn = await screen.findByRole('button', { name: /despublicar/i });
    fireEvent.click(btn);
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0]).toContain('POST');
    expect(calls[0]).toContain('/api/projects/p1/undeploy');
  });
});
