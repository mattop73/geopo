/**
 * Auth session context.
 *
 * Wraps the app in a single source of truth for the current Supabase
 * session and exposes:
 *   - `useSession()`   → current session + loading state
 *   - `getAccessToken()` → synchronous helper for the API client
 *   - `signOut()`      → flush the session and redirect
 *
 * The provider also keeps a module-level reference to the latest access
 * token so the API client (`api/client.ts`) can read it without going
 * through React — useful for fetches triggered outside the component tree
 * (react-query background refetches, etc).
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { Session } from '@supabase/supabase-js'
import { authEnabled, supabase } from './supabase'

interface SessionContextValue {
  session: Session | null
  loading: boolean
  authEnabled: boolean
}

const SessionContext = createContext<SessionContextValue>({
  session: null,
  loading: true,
  authEnabled,
})

// Module-level cache so non-React callers (api/client.ts) can grab the
// current access token without re-rendering.
let _accessToken: string | null = null

export function getAccessToken(): string | null {
  return _accessToken
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState<boolean>(authEnabled)

  useEffect(() => {
    if (!authEnabled || !supabase) {
      _accessToken = null
      setLoading(false)
      return
    }

    // 1) Bootstrap from any session already in storage (covers page reloads
    //    and the post-redirect OAuth flow — supabase-js parses the URL hash
    //    automatically when `detectSessionInUrl` is true).
    supabase.auth.getSession().then(({ data }) => {
      _accessToken = data.session?.access_token ?? null
      setSession(data.session)
      setLoading(false)
    })

    // 2) Subscribe to subsequent changes (sign-in, sign-out, token refresh).
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      _accessToken = s?.access_token ?? null
      setSession(s)
    })

    return () => sub.subscription.unsubscribe()
  }, [])

  const value = useMemo<SessionContextValue>(
    () => ({ session, loading, authEnabled }),
    [session, loading],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionContextValue {
  return useContext(SessionContext)
}

export async function signOut(): Promise<void> {
  if (!supabase) return
  await supabase.auth.signOut()
  _accessToken = null
  // Hard reload so react-query caches + component state get nuked too.
  window.location.assign('/')
}
