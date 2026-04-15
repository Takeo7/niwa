/**
 * Tests for the shared api() 401 handler.
 *
 * Regression guard for the infinite reload loop observed on first install:
 *
 *   1. Browser hits http://localhost:8080/ → backend 302 → /login.
 *   2. React mounts at /login. ``useCustomTheme`` (in ``main.tsx``'s
 *      ``ThemedApp``) calls ``useSettings`` unconditionally, which fires
 *      GET /api/settings before any cookie has been set.
 *   3. Backend returns 401.
 *   4. The pre-fix ``api()`` handler unconditionally set
 *      ``window.location.href = '/login'`` → full page reload → React
 *      re-mounts → step 2 → step 3 → step 4 → infinite loop. The user
 *      can't even type their password because the page reloads faster
 *      than they can.
 *
 * The fix: when already on ``/login``, don't reload — the LoginPage
 * doesn't depend on any protected API data, so we just surface the
 * error and let React Query hold it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './client';

type LocationStub = { pathname: string; href: string };

function stubLocation(initial: Partial<LocationStub>): LocationStub {
  const stub: LocationStub = {
    pathname: initial.pathname ?? '/',
    href: initial.href ?? 'http://localhost/',
  };
  // jsdom's ``window.location`` is not writable on modern jsdom; swap
  // the whole object so the api() handler's assignment to ``href`` is
  // observable without triggering a real navigation.
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: stub,
  });
  return stub;
}

function mockFetch401() {
  return vi.fn(
    async () =>
      new Response(JSON.stringify({ error: 'unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
}

describe('api() 401 handler — reload-loop guard', () => {
  const originalLocation = window.location;
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = mockFetch401() as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: originalLocation,
    });
    vi.restoreAllMocks();
  });

  it('redirects to /login on 401 when on an authenticated page', async () => {
    const loc = stubLocation({
      pathname: '/dashboard',
      href: 'http://localhost/dashboard',
    });

    await expect(api('stats')).rejects.toBeInstanceOf(ApiError);

    expect(loc.href).toBe('/login');
  });

  it('does NOT redirect when already on /login (avoids infinite reload loop)', async () => {
    const loc = stubLocation({
      pathname: '/login',
      href: 'http://localhost/login',
    });

    // Query fired from the root of the tree (e.g. useSettings) while on
    // the login page must fail gracefully, not trigger a reload.
    await expect(api('settings')).rejects.toBeInstanceOf(ApiError);

    expect(loc.href).toBe('http://localhost/login');
  });

  it('still throws an ApiError with the 401 status', async () => {
    stubLocation({ pathname: '/login', href: 'http://localhost/login' });

    const err = await api('settings').catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
  });
});
