/**
 * Thin fetch wrapper that:
 *   1. Prefixes paths with `/api`.
 *   2. Injects the Supabase access token as `Authorization: Bearer …`
 *      when one is available — same-origin in prod, /api proxied via
 *      Vite in dev.
 *   3. Triggers a forced sign-out on 401 so users never get stuck on a
 *      stale/expired token (Supabase auto-refresh covers the happy path;
 *      this is the safety net).
 *
 * The token is read from a module-level cache in `lib/session` rather
 * than pulled through React context — that lets react-query background
 * refetches and any imperative caller work without prop-drilling.
 */
import { setAuthError } from '../components/auth/LoginScreen'
import { getAccessToken, signOut } from '../lib/session'

const BASE = '/api'

function buildHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init)
  const token = getAccessToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return headers
}

async function safeDetail(r: Response): Promise<string | null> {
  try {
    const body = await r.clone().json()
    return typeof body?.detail === 'string' ? body.detail : null
  } catch {
    return null
  }
}

async function handle<T>(r: Response, label: string): Promise<T> {
  if (r.status === 401) {
    // Expired / revoked token. Force a clean re-login rather than letting
    // the UI loop on failed fetches. The 401 detail (e.g. "Session
    // expired", "Invalid auth token") goes to the login screen so the
    // user knows why they got bounced.
    const reason = (await safeDetail(r)) ?? 'Your session has expired. Please sign in again.'
    setAuthError(reason)
    void signOut()
    throw new Error(`${label} → 401 (signed out)`)
  }
  if (r.status === 403) {
    // Token is valid but the email isn't on the allowlist. Same UX as
    // 401 — bounce to login with the explanation.
    const reason = (await safeDetail(r))
      ?? 'This account is not authorized for this app. Contact the administrator.'
    setAuthError(reason)
    void signOut()
    throw new Error(`${label} → 403 (signed out)`)
  }
  if (!r.ok) throw new Error(`${label} → ${r.status}`)
  return r.json() as Promise<T>
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    ...options,
    headers: buildHeaders(options?.headers),
  })
  return handle<T>(r, `API ${path}`)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const headers = buildHeaders({ 'Content-Type': 'application/json' })
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  return handle<T>(r, `API POST ${path}`)
}

export async function apiStream(
  path: string,
  body: unknown,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = buildHeaders({ 'Content-Type': 'application/json' })
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (r.status === 401 || r.status === 403) {
    const reason = (await safeDetail(r))
      ?? (r.status === 403
        ? 'This account is not authorized for this app.'
        : 'Your session has expired. Please sign in again.')
    setAuthError(reason)
    void signOut()
    throw new Error(`Stream ${path} → ${r.status} (signed out)`)
  }
  if (!r.ok) throw new Error(`Stream ${path} → ${r.status}`)
  const reader = r.body!.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
}
