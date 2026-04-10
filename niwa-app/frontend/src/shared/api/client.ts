export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  if (
    options?.body &&
    typeof options.body === 'string' &&
    !options.headers
  ) {
    headers['Content-Type'] = 'application/json';
  }
  if (options?.headers) {
    Object.assign(headers, options.headers);
  }

  const res = await fetch(`/api/${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: Object.keys(headers).length > 0 ? headers : undefined,
  });

  if (res.status === 401 || res.status === 302) {
    window.location.href = '/login';
    throw new ApiError('No autenticado', res.status);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      (body as Record<string, string>).error || `Error ${res.status}`,
      res.status,
    );
  }

  const text = await res.text();
  if (!text) return {} as T;
  return JSON.parse(text) as T;
}

export async function apiPost<T>(path: string, data: unknown): Promise<T> {
  return api<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function apiPatch<T>(path: string, data: unknown): Promise<T> {
  return api<T>(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return api<T>(path, { method: 'DELETE' });
}

export async function login(
  username: string,
  password: string,
): Promise<boolean> {
  const body = new URLSearchParams({ username, password });
  const res = await fetch('/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
    credentials: 'same-origin',
    redirect: 'manual',
  });
  // A 302 redirect to / means success
  if (res.status === 200 && res.redirected) return true;
  if (res.type === 'opaqueredirect' || res.status === 0) return true;
  if (res.status === 302 || res.status === 303) return true;
  return false;
}

export async function checkAuth(): Promise<boolean> {
  try {
    const res = await fetch('/auth/check', { credentials: 'same-origin' });
    if (res.ok) {
      const data = await res.json();
      return data.authenticated === true;
    }
    return false;
  } catch {
    return false;
  }
}
