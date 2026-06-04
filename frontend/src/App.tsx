import { useState } from 'react'
import { BarChart2, Newspaper, TrendingUp, Bot, Activity, Sparkles, Mic2, LogOut } from 'lucide-react'
import { clsx } from 'clsx'
import CommoditiesTab from './components/commodities/CommoditiesTab'
import NewsTab from './components/news/NewsTab'
import PolymarketTab from './components/polymarket/PolymarketTab'
import PodcastsTab from './components/podcasts/PodcastsTab'
import LLMTab from './components/llm/LLMTab'
import ThemesTab from './components/themes/ThemesTab'
import LLMModelPicker from './components/common/LLMModelPicker'
import LoginScreen from './components/auth/LoginScreen'
import { signOut, useSession } from './lib/session'
import { LANGUAGES, type LanguageCode, useLanguage } from './hooks/useLanguage'

const TABS = [
  { id: 'commodities', label: 'Commodities', icon: BarChart2 },
  { id: 'news',        label: 'News',        icon: Newspaper },
  { id: 'polymarket',  label: 'Polymarket',  icon: TrendingUp },
  { id: 'podcasts',    label: 'Podcasts',    icon: Mic2 },
  { id: 'themes',      label: 'Themes',      icon: Sparkles },
  { id: 'llm',         label: 'LLM Analysis',icon: Bot },
] as const

type TabId = typeof TABS[number]['id']

export default function App() {
  const [active, setActive] = useState<TabId>('commodities')
  const { session, loading, authEnabled } = useSession()
  const { language, setLanguage } = useLanguage()

  // While Supabase rehydrates the session from storage we render a blank
  // dark frame instead of flashing the login screen for users who are
  // already logged in.
  if (authEnabled && loading) {
    return <div className="min-h-screen bg-[#0f1117]" />
  }

  // Auth is on but the user isn't signed in → show the login gate.
  if (authEnabled && !session) {
    return <LoginScreen />
  }

  // Either auth is disabled (dev mode) or a valid session exists. The
  // `user` may be null in dev mode, in which case the header just hides
  // the email/logout block.
  const user = session?.user ?? null

  return (
    <div className="min-h-screen bg-[#0f1117] text-slate-200 flex flex-col">
      {/* Header */}
      <header className="border-b border-[#2a2d3a] bg-[#1a1d27] px-6 py-3 flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          <span className="font-bold text-lg tracking-tight text-white">GEOPO</span>
          <span className="text-xs text-slate-500 font-mono">Geopolitics Dashboard</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <LanguageSelector language={language} onChange={setLanguage} />
          <LLMModelPicker />
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <span className="text-xs text-slate-500">Live</span>
          </div>
          {user && (
            <div className="flex items-center gap-2 pl-3 border-l border-[#2a2d3a]">
              <span className="text-xs text-slate-400" title={user.email ?? ''}>
                {user.email}
              </span>
              <button
                onClick={() => void signOut()}
                title="Sign out"
                className="text-slate-400 hover:text-white transition-colors p-1 rounded hover:bg-[#2a2d3a]"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Nav */}
      <nav className="border-b border-[#2a2d3a] bg-[#1a1d27] px-6">
        <div className="flex gap-1">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActive(id)}
              className={clsx(
                'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors',
                active === id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-600',
              )}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <main className="flex-1 overflow-auto p-6">
        {active === 'commodities' && <CommoditiesTab />}
        {active === 'news'        && <NewsTab />}
        {active === 'polymarket'  && <PolymarketTab />}
        {active === 'podcasts'    && <PodcastsTab />}
        {active === 'themes'      && <ThemesTab />}
        {active === 'llm'         && <LLMTab />}
      </main>
    </div>
  )
}

function LanguageSelector({
  language,
  onChange,
}: {
  language: LanguageCode
  onChange: (language: LanguageCode) => void
}) {
  return (
    <div className="flex items-center gap-1 rounded-lg bg-[#0f1117] border border-[#2a2d3a] p-1">
      {(Object.keys(LANGUAGES) as LanguageCode[]).map((code) => (
        <button
          key={code}
          onClick={() => onChange(code)}
          className={clsx(
            'px-2.5 py-1 rounded text-xs font-medium transition-colors',
            language === code
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white hover:bg-[#1a1d27]',
          )}
          title={`Display headlines and LLM analysis in ${LANGUAGES[code].llmName}`}
        >
          {LANGUAGES[code].label}
        </button>
      ))}
    </div>
  )
}
