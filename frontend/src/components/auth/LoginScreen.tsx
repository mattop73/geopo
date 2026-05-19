/**
 * Google sign-in screen.
 *
 * The only button here triggers Supabase's `signInWithOAuth({ provider:
 * 'google' })` which redirects to Google's consent screen. After consent
 * Google bounces back to Supabase, Supabase issues a JWT, and the user
 * lands back on this app's `/` with a hash fragment that supabase-js
 * parses automatically — `SessionProvider.useEffect` then fires
 * `onAuthStateChange` and the gate in `App.tsx` flips.
 */
import { Activity, LogIn } from 'lucide-react'
import { useState } from 'react'
import { supabase } from '../../lib/supabase'

export default function LoginScreen() {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
        // Send the user back to wherever they came from. Using the origin
        // (not a hardcoded URL) makes this work in dev, on a Railway
        // preview URL, and on a custom domain without any code change.
        redirectTo: window.location.origin,
      },
    })
    if (error) {
      setBusy(false)
      setError(error.message)
    }
    // Otherwise the browser is already navigating away — no need to
    // touch state.
  }

  return (
    <div className="min-h-screen bg-[#0f1117] text-slate-200 flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-8 shadow-xl">
        <div className="flex items-center gap-2 mb-6">
          <Activity className="w-6 h-6 text-blue-400" />
          <div>
            <div className="font-bold text-lg tracking-tight text-white">GEOPO</div>
            <div className="text-xs text-slate-500 font-mono">Geopolitics Dashboard</div>
          </div>
        </div>

        <h1 className="text-xl font-semibold text-white mb-2">Sign in</h1>
        <p className="text-sm text-slate-400 mb-6">
          Access is restricted to authorized accounts. Use your Google
          account to continue.
        </p>

        <button
          onClick={handleGoogle}
          disabled={busy}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium py-2.5 rounded-md transition-colors"
        >
          <LogIn className="w-4 h-4" />
          {busy ? 'Redirecting…' : 'Continue with Google'}
        </button>

        {error && (
          <div className="mt-4 text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded p-3">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
