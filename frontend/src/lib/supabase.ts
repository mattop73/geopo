/**
 * Singleton Supabase browser client.
 *
 * Config resolution order — most → least reliable:
 *   1. ``window.GEOPO_CONFIG`` — injected at request time by FastAPI when
 *      serving ``index.html`` in production. Decouples deploy config from
 *      the Docker build step, so updating Supabase env vars only needs a
 *      process restart, not a rebuild.
 *   2. ``import.meta.env.VITE_SUPABASE_URL`` / ``VITE_SUPABASE_ANON_KEY``
 *      — Vite's build-time env. Used in local ``npm run dev`` where the
 *      injected script tag isn't present.
 *
 * When neither source supplies both values we export a sentinel ``null``
 * and the SessionProvider switches to "auth disabled" mode — the SPA
 * renders directly without a login gate (dev-only safety net).
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

declare global {
  interface Window {
    GEOPO_CONFIG?: {
      supabase_url?: string
      supabase_anon_key?: string
    }
  }
}

function pickConfig(): { url: string | undefined; anonKey: string | undefined } {
  const runtime = typeof window !== 'undefined' ? window.GEOPO_CONFIG : undefined
  const url =
    (runtime?.supabase_url && runtime.supabase_url.length > 0
      ? runtime.supabase_url
      : undefined) ||
    (import.meta.env.VITE_SUPABASE_URL as string | undefined)
  const anonKey =
    (runtime?.supabase_anon_key && runtime.supabase_anon_key.length > 0
      ? runtime.supabase_anon_key
      : undefined) ||
    (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined)
  return { url, anonKey }
}

const { url, anonKey } = pickConfig()

export const authEnabled: boolean = Boolean(url && anonKey)

export const supabase: SupabaseClient | null = authEnabled
  ? createClient(url!, anonKey!, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null
