/**
 * Google-only sign-in screen.
 *
 * Flow:
 *   1. User clicks "Continue with Google" → Supabase redirects to the
 *      Google consent page (configured under Supabase Auth → Providers).
 *   2. Google bounces back to ``window.location.origin``; supabase-js
 *      parses the hash fragment automatically via ``detectSessionInUrl``.
 *   3. ``SessionProvider`` picks up the new session and the gate in
 *      ``App.tsx`` flips from <LoginScreen /> to the dashboard.
 *
 * Three failure modes are surfaced visually so users never wonder why
 * they're stuck on this screen:
 *   - Misconfigured frontend (VITE_SUPABASE_URL missing).
 *   - Google handshake error returned in the redirect URL.
 *   - Backend rejected the email (not on ALLOWED_EMAILS) — set via
 *     sessionStorage by ``api/client.ts`` on 403, then displayed here.
 */
import { Activity, ShieldAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { supabase } from '../../lib/supabase'

// Shared key with api/client.ts. When a forced sign-out happens because
// the backend returned 403 (email not on the allowlist), we stash the
// reason here so the LoginScreen can show a clear banner instead of the
// user wondering why they keep getting bounced.
const AUTH_ERROR_KEY = 'geopo.auth.error'

export function setAuthError(message: string): void {
  try {
    sessionStorage.setItem(AUTH_ERROR_KEY, message)
  } catch {
    /* private mode — best effort */
  }
}

function readAndClearAuthError(): string | null {
  try {
    const v = sessionStorage.getItem(AUTH_ERROR_KEY)
    if (v) sessionStorage.removeItem(AUTH_ERROR_KEY)
    return v
  } catch {
    return null
  }
}

/**
 * Parse error params that Supabase / Google attach to the redirect URL
 * when the OAuth handshake fails (e.g. user denied consent, or the
 * Google client config is broken).
 */
function readOAuthError(): string | null {
  if (typeof window === 'undefined') return null
  const search = new URLSearchParams(window.location.search)
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const err = search.get('error_description') || hash.get('error_description')
  if (!err) return null
  // Clean the URL so a page reload doesn't keep showing the error.
  window.history.replaceState({}, '', window.location.pathname)
  return decodeURIComponent(err.replace(/\+/g, ' '))
}

export default function LoginScreen() {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Pick up any stashed reason on mount (forced sign-out due to 403, or
  // OAuth error in the redirect URL).
  useEffect(() => {
    setError(readAndClearAuthError() ?? readOAuthError())
  }, [])

  async function handleGoogle() {
    if (!supabase) {
      setError('Supabase is not configured (missing VITE_SUPABASE_URL).')
      return
    }
    setBusy(true)
    setError(null)
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        // Using the origin (not a hardcoded URL) makes this work in dev,
        // on a Railway preview URL, and on a custom domain unchanged.
        redirectTo: window.location.origin,
      },
    })
    if (error) {
      setBusy(false)
      setError(error.message)
    }
    // Otherwise the browser is already navigating away — no state to touch.
  }

  return (
    <div className="min-h-screen bg-[#0f1117] text-slate-200 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-[#1a1d27] border border-[#2a2d3a] rounded-xl p-8 shadow-2xl shadow-black/40">
        <div className="flex items-center gap-2 mb-8">
          <Activity className="w-6 h-6 text-blue-400" />
          <div>
            <div className="font-bold text-lg tracking-tight text-white">GEOPO</div>
            <div className="text-xs text-slate-500 font-mono">Geopolitics Dashboard</div>
          </div>
        </div>

        <h1 className="text-xl font-semibold text-white mb-1">Sign in</h1>
        <p className="text-sm text-slate-400 mb-6">
          Access is restricted to authorized accounts.
        </p>

        <button
          onClick={handleGoogle}
          disabled={busy}
          className="w-full flex items-center justify-center gap-3 bg-white hover:bg-slate-100 disabled:opacity-60 disabled:cursor-not-allowed text-slate-900 font-medium py-2.5 rounded-md transition-colors shadow-sm"
        >
          {busy ? (
            <svg className="animate-spin w-4 h-4 text-slate-700" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
              <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
          ) : (
            <GoogleG className="w-4 h-4" />
          )}
          <span className="text-sm">
            {busy ? 'Redirecting to Google…' : 'Continue with Google'}
          </span>
        </button>

        {error && (
          <div className="mt-5 flex items-start gap-2 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-md p-3">
            <ShieldAlert className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span className="leading-snug">{error}</span>
          </div>
        )}

        <p className="mt-6 text-[11px] text-slate-600 leading-relaxed">
          By continuing you agree to be authenticated through Google and Supabase.
          Your email is used only to verify your access — no profile data is stored.
        </p>
      </div>
    </div>
  )
}

/**
 * Google's official "G" logo as inline SVG — keeping the brand asset
 * local (rather than an <img src=>) avoids a network round-trip and a
 * potentially broken external dependency. Colors and proportions follow
 * Google's identity guidelines for sign-in buttons.
 */
function GoogleG({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.611 20.083H42V20H24v8h11.303c-1.649 4.657-6.08 8-11.303 8-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.65-.389-3.917z"
      />
      <path
        fill="#FF3D00"
        d="M6.306 14.691l6.571 4.819C14.655 15.108 18.961 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.046 6.053 29.268 4 24 4 16.318 4 9.656 8.337 6.306 14.691z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.166 0 9.86-1.977 13.409-5.192l-6.19-5.238C29.211 35.091 26.715 36 24 36c-5.202 0-9.619-3.317-11.283-7.946l-6.522 5.025C9.505 39.556 16.227 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.611 20.083H42V20H24v8h11.303c-.792 2.237-2.231 4.166-4.087 5.571l.003-.002 6.19 5.238C36.971 39.205 44 34 44 24c0-1.341-.138-2.65-.389-3.917z"
      />
    </svg>
  )
}
