/**
 * Tests for ``GithubPanel`` (PR-49).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { GithubPanel } from './GithubPanel';

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

function statusEmpty() {
  return {
    connected: false,
    username: null,
    scopes: [],
    updated_at: null,
  };
}

function statusConnected() {
  return {
    connected: true,
    username: 'takeo7',
    scopes: ['repo', 'workflow'],
    updated_at: '2026-04-17T12:00:00Z',
  };
}

describe('GithubPanel', () => {
  afterEach(cleanup);

  it('muestra el formulario cuando no está conectado', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/github/status')) {
        return new Response(JSON.stringify(statusEmpty()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('{}', { status: 200 });
    }) as unknown as typeof fetch;

    render(wrap(<GithubPanel />));
    await waitFor(() =>
      expect(screen.getByText(/Integración con GitHub/i)).toBeTruthy(),
    );
    expect(screen.getByText(/sin conectar/i)).toBeTruthy();
    expect(screen.getByPlaceholderText('ghp_...')).toBeTruthy();
  });

  it('muestra el estado conectado con username y scopes', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/github/status')) {
        return new Response(JSON.stringify(statusConnected()), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('{}', { status: 200 });
    }) as unknown as typeof fetch;

    render(wrap(<GithubPanel />));
    await waitFor(() => expect(screen.getByText(/@takeo7/)).toBeTruthy());
    expect(screen.getAllByText('repo').length).toBeGreaterThan(0);
    expect(screen.getAllByText('workflow').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /desconectar/i })).toBeTruthy();
  });

  it('al guardar token hace POST con el token en el body', async () => {
    const posted: Array<{ body: unknown }> = [];
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/github/status')) {
          return new Response(JSON.stringify(statusEmpty()), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/api/github/token') && init?.method === 'POST') {
          posted.push({ body: init.body ? JSON.parse(init.body as string) : {} });
          return new Response(
            JSON.stringify({ ok: true, ...statusConnected() }),
            {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            },
          );
        }
        return new Response('{}', { status: 200 });
      },
    ) as unknown as typeof fetch;

    render(wrap(<GithubPanel />));
    const input = await screen.findByPlaceholderText('ghp_...');
    fireEvent.change(input, { target: { value: 'ghp_abc123' } });
    const btn = screen.getByRole('button', { name: /validar y guardar/i });
    fireEvent.click(btn);
    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0].body).toEqual({ token: 'ghp_abc123' });
  });

  it('al desconectar hace DELETE /api/github/token', async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/github/status')) {
          return new Response(JSON.stringify(statusConnected()), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/api/github/token')) {
          calls.push(`${init?.method ?? 'GET'} ${url}`);
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('{}', { status: 200 });
      },
    ) as unknown as typeof fetch;

    render(wrap(<GithubPanel />));
    const btn = await screen.findByRole('button', { name: /desconectar/i });
    fireEvent.click(btn);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    expect(calls[0]).toContain('DELETE');
    expect(calls[0]).toContain('/api/github/token');
  });
});
