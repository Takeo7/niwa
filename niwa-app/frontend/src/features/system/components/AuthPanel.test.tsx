/**
 * Tests for ``AuthPanel`` (PR-A6).
 *
 * Covers the subscription-first Claude auth UI: it reads the
 * ``claude_code`` backend entry from ``/api/readiness`` to decide
 * whether the user is authenticated and, if not, exposes an input
 * that POSTs ``/api/settings/llm/setup-token`` to persist the token.
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
import { AuthPanel } from './AuthPanel';

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

function readinessWithClaude(opts: {
  has_credential: boolean;
  auth_mode?: 'api_key' | 'setup_token' | 'oauth';
}) {
  return {
    docker_ok: true,
    db_ok: true,
    admin_ok: true,
    admin_detail: 'admin user: admin',
    backends: [
      {
        slug: 'claude_code',
        display_name: 'Claude Code',
        enabled: true,
        has_credential: opts.has_credential,
        auth_mode: opts.auth_mode ?? 'api_key',
        model_present: true,
        default_model: 'claude-sonnet-4-6',
        reachable: opts.has_credential,
      },
    ],
    hosting_ok: true,
    hosting_detail: '',
    checked_at: '2026-04-19T00:00:00Z',
  };
}

describe('AuthPanel', () => {
  afterEach(cleanup);

  it('muestra el input de token y el badge "No autenticado" cuando no hay credencial', async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/readiness')) {
        return new Response(
          JSON.stringify(readinessWithClaude({ has_credential: false })),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return new Response('{}', { status: 200 });
    }) as unknown as typeof fetch;

    render(wrap(<AuthPanel />));

    await waitFor(() =>
      expect(screen.getByText(/Claude \(suscripción\)/i)).toBeTruthy(),
    );
    expect(screen.getByText(/No autenticado/i)).toBeTruthy();
    expect(screen.getByPlaceholderText(/sk-ant-oat01/i)).toBeTruthy();
    expect(
      screen.getByRole('button', { name: /aplicar token/i }),
    ).toBeTruthy();
  });

  it('al aplicar el token, hace POST /api/settings/llm/setup-token y refresca readiness', async () => {
    const posted: Array<{ url: string; body: unknown }> = [];
    let readinessCalls = 0;
    let tokenSaved = false;

    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/readiness')) {
          readinessCalls += 1;
          return new Response(
            JSON.stringify(
              readinessWithClaude({
                has_credential: tokenSaved,
                auth_mode: tokenSaved ? 'setup_token' : 'api_key',
              }),
            ),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (
          url.includes('/api/settings/llm/setup-token') &&
          init?.method === 'POST'
        ) {
          const body = init.body ? JSON.parse(init.body as string) : {};
          posted.push({ url, body });
          tokenSaved = true;
          return new Response(
            JSON.stringify({ ok: true, message: 'Token saved' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200 });
      },
    ) as unknown as typeof fetch;

    render(wrap(<AuthPanel />));

    const input = await screen.findByPlaceholderText(/sk-ant-oat01/i);
    fireEvent.change(input, {
      target: { value: 'sk-ant-oat01-abc123' },
    });
    fireEvent.click(
      screen.getByRole('button', { name: /aplicar token/i }),
    );

    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0].body).toEqual({ token: 'sk-ant-oat01-abc123' });

    // readiness was refetched (at least initial + post-mutation)
    const callsAfterMutation = readinessCalls;
    await waitFor(() => expect(readinessCalls).toBeGreaterThan(1));
    expect(callsAfterMutation).toBeGreaterThanOrEqual(1);

    // badge flips to "Autenticado vía suscripción" once readiness
    // reports has_credential=true + auth_mode=setup_token.
    await waitFor(() =>
      expect(screen.getByText(/autenticado vía suscripción/i)).toBeTruthy(),
    );
  });

  it('muestra el error del backend cuando el token es inválido', async () => {
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/readiness')) {
          return new Response(
            JSON.stringify(readinessWithClaude({ has_credential: false })),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        if (
          url.includes('/api/settings/llm/setup-token') &&
          init?.method === 'POST'
        ) {
          return new Response(
            JSON.stringify({
              ok: false,
              error:
                'Invalid token format — should start with sk-ant-oat01-',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200 });
      },
    ) as unknown as typeof fetch;

    render(wrap(<AuthPanel />));

    const input = await screen.findByPlaceholderText(/sk-ant-oat01/i);
    fireEvent.change(input, { target: { value: 'garbage' } });
    fireEvent.click(
      screen.getByRole('button', { name: /aplicar token/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Invalid token format/i),
      ).toBeTruthy(),
    );
    // the button is active again after the error
    expect(
      (screen.getByRole('button', {
        name: /aplicar token/i,
      }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});
