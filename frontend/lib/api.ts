'use client';

/**
 * Same-origin API client.
 *
 * The backend now serves this frontend itself, so every call is a relative
 * path — there is no BACKEND_URL to configure and no CORS to negotiate.
 *
 * API key handling: the backend only requires a key when API_KEY is set in its
 * environment. When it is, the browser cannot know it up front (a header cannot
 * be attached to the initial HTML request), so the UI asks for it once and
 * keeps it in localStorage. The backend reports whether a key is needed on
 * GET /config.
 */

const KEY_STORAGE = 'genjutsu-api-key';

export function getApiKey(): string {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(KEY_STORAGE) ?? '';
  } catch {
    return '';
  }
}

export function setApiKey(key: string): void {
  if (typeof window === 'undefined') return;
  try {
    if (key) window.localStorage.setItem(KEY_STORAGE, key);
    else window.localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* private mode — the key just will not persist */
  }
}

/** Headers for a normal fetch. Empty when no key is configured. */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = getApiKey();
  return key ? { ...extra, 'X-API-Key': key } : extra;
}

/** Build a same-origin URL, appending ?api_key= when one is stored. */
export function apiUrl(path: string): string {
  const key = getApiKey();
  if (!key) return path;
  return `${path}${path.includes('?') ? '&' : '?'}api_key=${encodeURIComponent(key)}`;
}

/** EventSource cannot send headers, so the key travels in the query string. */
export function streamUrl(jobId: string): string {
  return apiUrl(`/jobs/${jobId}/stream`);
}

export function videoUrl(jobId: string): string {
  return apiUrl(`/jobs/${jobId}/video`);
}

/** POST to the backend with auth applied. */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, { ...init, headers: authHeaders((init.headers as Record<string, string>) ?? {}) });
}

export type BackendConfig = {
  authRequired: boolean;
  maxImages: number;
  minDuration: number;
  maxDuration: number;
};

export async function fetchConfig(): Promise<BackendConfig | null> {
  try {
    const r = await fetch('/config');
    if (!r.ok) return null;
    return (await r.json()) as BackendConfig;
  } catch {
    return null;
  }
}
