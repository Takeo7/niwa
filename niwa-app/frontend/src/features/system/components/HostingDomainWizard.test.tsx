/**
 * Tests for ``HostingDomainWizard`` (PR-48).
 *
 * The wizard consumes ``GET /api/hosting/status`` and saves the domain
 * via ``POST /api/services/hosting``. These tests mock fetch and
 * exercise the happy path + a couple of degraded states.
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
import { HostingDomainWizard } from './HostingDomainWizard';

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

function emptyStatus() {
  return {
    domain: '',
    port: 8880,
    public_ip: null,
    caddy_listening: false,
    dns: { host: '', ips: [] },
    wildcard: { host: '', ips: [] },
    http: { tried: [], ok: false, status: null, url: null, error: null },
    suggested_records: [],
  };
}

function happyStatus() {
  return {
    domain: 'example.com',
    port: 8880,
    public_ip: '203.0.113.10',
    caddy_listening: true,
    dns: { host: 'example.com', ips: ['203.0.113.10'] },
    wildcard: {
      host: 'niwa-probe.example.com',
      ips: ['203.0.113.10'],
    },
    http: {
      tried: ['https://example.com/'],
      ok: true,
      status: 200,
      url: 'https://example.com/',
      error: null,
    },
    suggested_records: [
      { type: 'A', name: '@', value: '203.0.113.10', proxied: true },
      { type: 'A', name: '*', value: '203.0.113.10', proxied: true },
    ],
  };
}

function mockFetch(statusResponse: unknown, onPostHosting?: () => unknown) {
  globalThis.fetch = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/hosting/status')) {
        return new Response(JSON.stringify(statusResponse), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.includes('/api/services/hosting') && init?.method === 'POST') {
        const body = onPostHosting ? onPostHosting() : { ok: true, saved: ['svc.hosting.domain'] };
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('{}', { status: 200 });
    },
  ) as unknown as typeof fetch;
}

describe('HostingDomainWizard', () => {
  afterEach(cleanup);

  it('muestra instrucciones Cloudflare con la IP pública detectada', async () => {
    mockFetch({ ...emptyStatus(), public_ip: '203.0.113.10' });
    render(wrap(<HostingDomainWizard />));
    await waitFor(() =>
      expect(screen.getAllByText('203.0.113.10').length).toBeGreaterThan(0),
    );
    expect(screen.getByText(/Cloudflare con el proxy naranja ON/i)).toBeTruthy();
    // Before saving a domain, step 4 asks the user to save one first.
    expect(
      screen.getByText(/Guarda un dominio en el paso 3/i),
    ).toBeTruthy();
  });

  it('degrada si public_ip es null', async () => {
    mockFetch({ ...emptyStatus(), public_ip: null });
    render(wrap(<HostingDomainWizard />));
    await waitFor(() =>
      expect(
        screen.getByText(/No pude detectar la IP pública/i),
      ).toBeTruthy(),
    );
  });

  it('el botón Guardar llama POST /api/services/hosting con el dominio', async () => {
    const posted: Array<{ url: string; body: unknown }> = [];
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === 'string' ? input : input.toString();
        if (url.includes('/api/hosting/status')) {
          return new Response(JSON.stringify(emptyStatus()), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        if (url.includes('/api/services/hosting') && init?.method === 'POST') {
          const parsed = init.body ? JSON.parse(init.body as string) : {};
          posted.push({ url, body: parsed });
          return new Response(JSON.stringify({ ok: true, saved: [] }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('{}', { status: 200 });
      },
    ) as unknown as typeof fetch;

    render(wrap(<HostingDomainWizard />));
    const input = await screen.findByPlaceholderText('midominio.com');
    fireEvent.change(input, { target: { value: 'misitio.com' } });
    const saveBtn = screen.getByRole('button', { name: /^guardar$/i });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(posted.length).toBe(1));
    expect(posted[0].url).toContain('/api/services/hosting');
    expect(posted[0].body).toEqual({ 'svc.hosting.domain': 'misitio.com' });
  });

  it('con todo OK, muestra el mensaje "¡Listo!"', async () => {
    mockFetch(happyStatus());
    render(wrap(<HostingDomainWizard />));
    await waitFor(() => expect(screen.getByText(/¡Listo!/i)).toBeTruthy());
    expect(screen.getByText(/https:\/\/<slug>\.example\.com\//)).toBeTruthy();
  });
});
