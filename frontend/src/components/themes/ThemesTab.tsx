import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  Loader2,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  AlertTriangle,
  ExternalLink,
} from 'lucide-react'
import { apiFetch, apiStream } from '../../api/client'
import { fmtPct, fmtPrice, timeAgo } from '../../lib/format'
import { useLLMModel } from '../../hooks/useLLMModel'
import LLMModelPicker from '../common/LLMModelPicker'
import CommoditiesOverviewChart from '../commodities/CommoditiesOverviewChart'

interface Commodity {
  ticker: string
  name: string
  category: string
  price: number
  change_pct: number
}

interface NewsItem {
  id: number
  source: string
  title: string
  url: string
  published_at: string | null
}

interface Market {
  condition_id: string
  question: string
  yes_price: number
  price_change_24h: number
  volume: number
  is_anomaly: boolean
  anomaly_reason: string | null
  url: string
}

interface ThemeStats {
  news_count: number
  market_count: number
  anomaly_count: number
  avg_commodity_change_pct: number
}

interface Theme {
  id: string
  label: string
  icon: string
  color: string
  commodities: Commodity[]
  news: NewsItem[]
  markets: Market[]
  stats: ThemeStats
}

type CacheState = 'HIT' | 'MISS' | undefined

export default function ThemesTab() {
  const { model } = useLLMModel()
  const [analysis, setAnalysis] = useState<Record<string, string>>({})
  const [cacheState, setCacheState] = useState<Record<string, CacheState>>({})
  const [streamingId, setStreamingId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const { data: themes = [], isLoading, refetch, isFetching } = useQuery<Theme[]>({
    queryKey: ['themes'],
    queryFn: () => apiFetch('/themes/'),
    refetchInterval: 5 * 60 * 1000,
  })

  /**
   * Stream analysis from /api/themes/analyze, with two key behaviours:
   *  - Reads the `X-Cache` header so the UI can label "Cached".
   *  - When the caller passes `fresh=true`, the server bypasses the cache.
   *    We expose this via a second button on the card.
   */
  const analyzeTheme = async (theme: Theme, fresh = false) => {
    if (streamingId) return
    setStreamingId(theme.id)
    setAnalysis((prev) => ({ ...prev, [theme.id]: '' }))
    setCacheState((prev) => ({ ...prev, [theme.id]: undefined }))
    abortRef.current = new AbortController()

    try {
      const resp = await fetch('/api/themes/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic_id: theme.id, model, fresh }),
        signal: abortRef.current.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const cache = (resp.headers.get('x-cache') as CacheState) ?? undefined
      setCacheState((prev) => ({ ...prev, [theme.id]: cache }))

      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        setAnalysis((prev) => ({
          ...prev,
          [theme.id]: (prev[theme.id] ?? '') + chunk,
        }))
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setAnalysis((prev) => ({
          ...prev,
          [theme.id]: (prev[theme.id] ?? '') + `\n[Error: ${e.message}]`,
        }))
      }
    } finally {
      setStreamingId(null)
    }
  }

  const cancel = () => {
    abortRef.current?.abort()
    setStreamingId(null)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-amber-300" />
            Thematic links
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Commodities, news, and Polymarket odds grouped by topic. Click
            <span className="text-amber-300"> Analyze </span>
            to have the selected LLM explain how the three sources reinforce
            each other.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <LLMModelPicker />
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs bg-[#1a1d27] border border-[#2a2d3a] text-slate-300 hover:text-white"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            Reload
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="text-slate-500 text-sm py-12 text-center">Loading themes…</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {themes.map((theme) => (
          <ThemeCard
            key={theme.id}
            theme={theme}
            analysis={analysis[theme.id]}
            cacheState={cacheState[theme.id]}
            streaming={streamingId === theme.id}
            disabled={!!streamingId && streamingId !== theme.id}
            onAnalyze={() => analyzeTheme(theme, false)}
            onAnalyzeFresh={() => analyzeTheme(theme, true)}
            onCancel={cancel}
          />
        ))}
      </div>
    </div>
  )
}

function ThemeCard({
  theme,
  analysis,
  cacheState,
  streaming,
  disabled,
  onAnalyze,
  onAnalyzeFresh,
  onCancel,
}: {
  theme: Theme
  analysis: string | undefined
  cacheState: CacheState
  streaming: boolean
  disabled: boolean
  onAnalyze: () => void
  onAnalyzeFresh: () => void
  onCancel: () => void
}) {
  const avg = theme.stats.avg_commodity_change_pct
  const up = avg >= 0
  return (
    <section
      className="rounded-lg border bg-[#1a1d27] overflow-hidden"
      style={{ borderColor: `${theme.color}55` }}
    >
      {/* Header */}
      <header
        className="px-4 py-3 flex items-center gap-3 border-b"
        style={{
          background: `linear-gradient(90deg, ${theme.color}22, transparent 60%)`,
          borderColor: '#2a2d3a',
        }}
      >
        <span className="text-2xl leading-none">{theme.icon}</span>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-white truncate">{theme.label}</h3>
          <div className="flex items-center gap-3 text-xs text-slate-400 mt-0.5 flex-wrap">
            <span>
              <span className="text-slate-200">{theme.stats.news_count}</span> news
            </span>
            <span>
              <span className="text-slate-200">{theme.stats.market_count}</span> markets
            </span>
            <span>
              <span className="text-slate-200">{theme.commodities.length}</span> commodities
            </span>
            {theme.stats.anomaly_count > 0 && (
              <span className="flex items-center gap-1 text-amber-300">
                <AlertTriangle className="w-3 h-3" />
                {theme.stats.anomaly_count} anomalies
              </span>
            )}
            {theme.commodities.length > 0 && (
              <span
                className={`flex items-center gap-1 font-mono ${
                  up ? 'text-green-400' : 'text-red-400'
                }`}
                title="Avg change across linked commodities"
              >
                {up ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                {fmtPct(avg)}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {analysis !== undefined && !streaming && cacheState === 'HIT' && (
            <span
              className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-900/40 text-emerald-300 border border-emerald-800/40"
              title="Served from cache — click ↻ to regenerate"
            >
              Cached
            </span>
          )}
          {analysis !== undefined && !streaming && (
            <button
              onClick={onAnalyzeFresh}
              disabled={disabled}
              title="Re-analyze (bypass cache)"
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-[#0f1117] border border-[#2a2d3a] text-slate-400 hover:text-white disabled:opacity-40"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          )}
          <button
            onClick={streaming ? onCancel : onAnalyze}
            disabled={disabled}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
              streaming
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40'
            }`}
          >
            {streaming ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Cancel
              </>
            ) : (
              <>
                <Bot className="w-3.5 h-3.5" />
                Analyze
              </>
            )}
          </button>
        </div>
      </header>

      {/* LLM analysis output (only when present) */}
      {analysis !== undefined && (
        <div className="px-4 py-3 border-b border-[#2a2d3a] bg-[#0f1117]">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1.5 flex items-center gap-1">
            <Sparkles className="w-3 h-3" />
            LLM Brief
          </div>
          <pre className="whitespace-pre-wrap font-sans text-xs text-slate-200 leading-relaxed max-h-96 overflow-auto">
            {analysis || (streaming ? '...' : '')}
          </pre>
        </div>
      )}

      {/* Mini overview chart — only when there are enough linked tickers to
          make an overlay informative (1-line chart is just a sparkline). */}
      {theme.commodities.length >= 2 && (
        <div className="px-3 pt-3 border-t border-[#2a2d3a] bg-[#0f1117]/40">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1.5">
            Linked commodities · normalized
          </div>
          <CommoditiesOverviewChart
            tickers={theme.commodities.map((c) => c.ticker)}
            height={220}
            title=""
            subtitle=""
            hideLegend
            defaultPeriodLabel="1M"
            bare
          />
        </div>
      )}

      {/* Body — three columns of linked data */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-0 divide-y md:divide-y-0 md:divide-x divide-[#2a2d3a]">
        <CommodityList items={theme.commodities} />
        <NewsList items={theme.news} />
        <MarketList items={theme.markets} />
      </div>
    </section>
  )
}

function ColumnHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex items-center justify-between mb-2">
      <span className="text-[10px] uppercase tracking-widest text-slate-500">{label}</span>
      <span className="text-[10px] font-mono text-slate-600">{count}</span>
    </div>
  )
}

function CommodityList({ items }: { items: Commodity[] }) {
  return (
    <div className="p-3 min-h-[180px]">
      <ColumnHeader label="Commodities" count={items.length} />
      {items.length === 0 && <div className="text-xs text-slate-600">—</div>}
      <ul className="space-y-1">
        {items.map((c) => {
          const up = c.change_pct >= 0
          return (
            <li
              key={c.ticker}
              className="flex items-center justify-between px-2 py-1 rounded hover:bg-[#0f1117]"
            >
              <div className="min-w-0">
                <div className="text-xs text-slate-200 truncate">{c.name}</div>
                <div className="text-[10px] text-slate-500 font-mono">{c.ticker}</div>
              </div>
              <div className="text-right shrink-0 ml-2">
                <div className="text-xs font-mono text-slate-200">{fmtPrice(c.price)}</div>
                <div
                  className={`text-[10px] font-mono ${up ? 'text-green-400' : 'text-red-400'}`}
                >
                  {fmtPct(c.change_pct)}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function NewsList({ items }: { items: NewsItem[] }) {
  return (
    <div className="p-3 min-h-[180px]">
      <ColumnHeader label="News" count={items.length} />
      {items.length === 0 && <div className="text-xs text-slate-600">—</div>}
      <ul className="space-y-1.5">
        {items.map((n) => (
          <li key={n.id}>
            <a
              href={n.url}
              target="_blank"
              rel="noreferrer"
              className="block group px-2 py-1 rounded hover:bg-[#0f1117]"
            >
              <div className="text-xs text-slate-200 leading-snug line-clamp-2 group-hover:text-white">
                {n.title}
              </div>
              <div className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-1">
                <span className="uppercase tracking-wide text-blue-400">{n.source}</span>
                <span>·</span>
                <span>{timeAgo(n.published_at)}</span>
                <ExternalLink className="w-2.5 h-2.5 text-slate-600 ml-auto opacity-0 group-hover:opacity-100" />
              </div>
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

function MarketList({ items }: { items: Market[] }) {
  return (
    <div className="p-3 min-h-[180px]">
      <ColumnHeader label="Polymarket" count={items.length} />
      {items.length === 0 && <div className="text-xs text-slate-600">—</div>}
      <ul className="space-y-1.5">
        {items.map((m) => {
          const pct = Math.round((m.yes_price ?? 0) * 100)
          const d24 = (m.price_change_24h ?? 0) * 100
          const up = d24 >= 0
          return (
            <li key={m.condition_id}>
              <a
                href={m.url}
                target="_blank"
                rel="noreferrer"
                className="block group px-2 py-1 rounded hover:bg-[#0f1117]"
              >
                <div className="flex items-start gap-2">
                  <span
                    className={`text-[10px] font-mono rounded px-1.5 py-0.5 shrink-0 mt-0.5 ${
                      pct >= 50 ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'
                    }`}
                  >
                    {pct}%
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-slate-200 leading-snug line-clamp-2 group-hover:text-white">
                      {m.question}
                    </div>
                    <div className="text-[10px] mt-0.5 flex items-center gap-1.5 flex-wrap">
                      <span className={`font-mono ${up ? 'text-green-400' : 'text-red-400'}`}>
                        {d24 >= 0 ? '+' : ''}
                        {d24.toFixed(1)}pts/24h
                      </span>
                      {m.is_anomaly && (
                        <span
                          className="flex items-center gap-0.5 text-amber-300"
                          title={m.anomaly_reason ?? ''}
                        >
                          <AlertTriangle className="w-2.5 h-2.5" />
                          anomaly
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </a>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
