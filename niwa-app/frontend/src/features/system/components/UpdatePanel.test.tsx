/**
 * Tests for UpdatePanel (PR-61).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import {
  render,
  screen,
  cleanup,
  waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { UpdatePanel, shellQuote } from './UpdatePanel';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        {ui}
      </MantineProvider>
    </QueryClientProvider>
  );
}

function mockVersion(payload: Record<string, unknown>) {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch;
}

describe('UpdatePanel', () => {
  afterEach(cleanup);

  it('muestra badges de versión / rama / commit / schema', async () => {
    mockVersion({
      version: '0.1.0',
      name: 'Niwa',
      branch: 'v0.2',
      commit: 'abcdef1234567890',
      commit_short: 'abcdef123456',
      schema_version: 14,
      needs_update: false,
      repo_dirty: false,
      last_backup_path: null,
      last_backup_at: null,
      last_update: null,
    });
    render(wrap(<UpdatePanel />));
    await waitFor(() => expect(screen.getByText(/versión 0\.1\.0/i)).toBeTruthy());
    expect(screen.getByText(/rama v0\.2/i)).toBeTruthy();
    expect(screen.getByText(/commit abcdef123456/i)).toBeTruthy();
    expect(screen.getByText(/schema 14/i)).toBeTruthy();
  });

  it('banner "Hay commits nuevos" cuando needs_update=true', async () => {
    mockVersion({
      version: '0.1.0',
      branch: 'v0.2',
      commit_short: 'aaaa',
      latest_remote_commit: 'bbbbbbbbbbbbbbbb',
      needs_update: true,
      repo_dirty: false,
      schema_version: 14,
      last_update: null,
    });
    render(wrap(<UpdatePanel />));
    await waitFor(() =>
      expect(screen.getByText(/commits nuevos/i)).toBeTruthy(),
    );
  });

  it('aviso repo_dirty cuando el repo tiene cambios locales', async () => {
    mockVersion({
      version: '0.1.0',
      branch: 'v0.2',
      commit_short: 'aaaa',
      needs_update: false,
      repo_dirty: true,
      schema_version: 14,
      last_update: null,
    });
    render(wrap(<UpdatePanel />));
    await waitFor(() =>
      expect(screen.getByText(/cambios locales/i)).toBeTruthy(),
    );
  });

  it('renderiza última actualización con estado reverted', async () => {
    mockVersion({
      version: '0.1.0',
      branch: 'v0.2',
      commit_short: 'aaaa',
      needs_update: false,
      repo_dirty: false,
      schema_version: 14,
      last_backup_path: '/data/backups/niwa-20260417.sqlite3',
      last_backup_at: '2026-04-17T12:00:00Z',
      last_update: {
        timestamp: '20260417-120000',
        success: false,
        reverted: true,
        branch: 'v0.2',
        before_commit: 'aaaaaaaaaaaaaaaa',
        after_commit: 'bbbbbbbbbbbbbbbb',
        backup_path: '/data/backups/niwa-20260417.sqlite3',
        errors: [],
        warnings: ['health-check post-update falló'],
        duration_seconds: 42.5,
      },
    });
    render(wrap(<UpdatePanel />));
    await waitFor(() =>
      expect(screen.getByText(/Última actualización/i)).toBeTruthy(),
    );
    expect(screen.getByText('Revertida')).toBeTruthy();
    expect(screen.getAllByText(/health-check/i).length).toBeGreaterThan(0);
  });

  it('muestra comando niwa update con botón copiar', async () => {
    mockVersion({
      version: '0.1.0',
      branch: 'v0.2',
      commit_short: 'aaaa',
      needs_update: false,
      repo_dirty: false,
      schema_version: 14,
      last_update: null,
    });
    render(wrap(<UpdatePanel />));
    await waitFor(() =>
      expect(screen.getByText(/Cómo actualizar/i)).toBeTruthy(),
    );
    expect(screen.getByText('niwa update')).toBeTruthy();
  });
});

describe('shellQuote (PR final 3)', () => {
  it('deja paths limpios sin quotes', () => {
    expect(shellQuote('/usr/local/bin/niwa')).toBe('/usr/local/bin/niwa');
    expect(shellQuote('niwa')).toBe('niwa');
    expect(shellQuote('a.sqlite3')).toBe('a.sqlite3');
  });

  it('cuota paths con espacios', () => {
    expect(shellQuote('/data backups/niwa.sqlite3')).toBe(
      "'/data backups/niwa.sqlite3'",
    );
  });

  it('escapa single quotes literales', () => {
    // La fórmula clásica: '...' + '\'' + '...'.
    expect(shellQuote("a'b")).toBe("'a'\\''b'");
  });

  it('empty string queda como dos single quotes', () => {
    expect(shellQuote('')).toBe("''");
  });

  it('restore suggestion con espacios round-trip compatible con shell', () => {
    // Simula lo que UpdatePanel concatena:
    //   restore_command + shellQuote(last_backup_path)
    const prefix = "'/repo path/niwa' restore --from=";
    const bkp = '/data backups/niwa 2026.sqlite3';
    const suggestion = prefix + shellQuote(bkp);
    // Forma final esperada: 'precmd' restore --from='path con espacios'
    expect(suggestion).toBe(
      "'/repo path/niwa' restore --from='/data backups/niwa 2026.sqlite3'",
    );
  });
});
