/**
 * Singleton Supabase browser client.
 *
 * Reads URL + anon key from Vite env vars at build time. In dev these come
 * from `frontend/.env.local`; in production they're injected by Railway as
 * `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` and baked into the static
 * bundle.
 *
 * When either var is missing we export a sentinel `null` and the session
 * provider switches to "auth disabled" mode — the SPA renders directly
 * without a login screen, which is the dev fallback that pairs with the
 * backend's missing-secret behavior.
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined

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
