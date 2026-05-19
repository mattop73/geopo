import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ExternalLink,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Clock,
  Wallet,
  Activity,
} from 'lucide-react'
import { apiFetch, apiPost } from '../../api/client'
import { fmtVolume, timeAgo } from '../../lib/format'

interface Market {
  condition_id: string
  question: string
  category: string
  topic: string
  yes_price: number
  no_price: number
  volume: number
  volume_24h: number
  price_change_24h: number
  is_anomaly: boolean
  anomaly_reason: string | null
  recorded_at: string | null
  end_date: string | null
  url: string
}

interface Topic {
  id: string
  label: string
  icon: string
  color: string
}

type SortMode = 'recent' | 'volume' | 'volume_24h' | 'anomaly'

const SORT_OPTIONS: { id: SortMode; label: string; icon: React.ComponentType<{ className?: string }>; hint: string }[] = [
  { id: 'volume',     label: 'Top volume',  icon: Wallet,   hint: 'Total bet $$ descending' },
  { id: 'volume_24h', label: '24h volume',  icon: Activity, hint: 'Last 24h bet $$ descending' },
  { id: 'recent',     label: 'Most recent', icon: Clock,    hint: 'Newest snapshot first' },
  { id: 'anomaly',    label: 'Anomalies',   icon: AlertTriangle, hint: 'Flagged anomalies first then volume' },
]

export default function PolymarketTab() {
  const [anomaliesOnly, setAnomaliesOnly] = useState(false)
  const [activeTopic, setActiveTopic] = useState<string>('all')
  const [sort, setSort] = useState<SortMode>('volume')

  const { data: topics = [] } = useQuery<Topic[]>({
    queryKey: ['topics'],
    queryFn: () => apiFetch('/themes/topics'),
    staleTime: Infinity,
  })

  const { data: markets = [], isLoading, refetch } = useQuery<Market[]>({
    queryKey: ['polymarket', anomaliesOnly, activeTopic, sort],
    queryFn: () => {
      const params = new URLSearchParams({
        anomalies_only: String(anomaliesOnly),
        sort,
      })
      if (activeTopic !== 'all') params.set('topic', activeTopic)
      return apiFetch(`/polymarket/?${params.toString()}`)
    },
    refetchInterval: 5 * 60 * 1000,
  })

  const handleRefresh = async () => {
    await apiPost('/polymarket/refresh', {})
    refetch()
  }

  // Counts per topic across the currently-loaded set (no second roundtrip).
  // To populate topic chip counts even for non-active topics we use a separate
  // unfiltered query, otherwise the count would be 0 when filtered to one.
  const { data: allMarkets = [] } = useQuery<Market[]>({
    queryKey: ['polymarket-counts', anomaliesOnly],
    queryFn: () =>
      apiFetch(
        `/polymarket/?anomalies_only=${anomaliesOnly}&sort=anomaly`,
      ),
    staleTime: 60_000,
  })

  const topicCounts = useMemo(() => {
    const out: Record<string, number> = {}
    for (const m of allMarkets) out[m.topic] = (out[m.topic] ?? 0) + 1
    return out
  }, [allMarkets])

  const topicById = new Map(topics.map((t) => [t.id, t]))
  const anomalyCount = allMarkets.filter((m) => m.is_anomaly).length

  return (
    <div className="space-y-4">
      {/* Topic chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-widest text-slate-500 mr-1">Topic</span>
        <TopicChip
          label="All topics"
          active={activeTopic === 'all'}
          onClick={() => setActiveTopic('all')}
          count={allMarkets.length}
        />
        {topics.map((t) => {
          const c = topicCounts[t.id] ?? 0
          return (
            <TopicChip
              key={t.id}
              label={`${t.icon} ${t.label}`}
              color={t.color}
              active={activeTopic === t.id}
              onClick={() => setActiveTopic(t.id)}
              count={c}
              dimmed={activeTopic === 'all' && c === 0}
            />
          )
        })}
      </div>

      {/* Mode row: anomaly toggle + sort + refresh */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setAnomaliesOnly(false)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
              !anomaliesOnly
                ? 'bg-blue-600 text-white'
                : 'bg-[#1a1d27] text-slate-400 hover:text-white border border-[#2a2d3a]'
            }`}
          >
            All markets
            <span className="ml-2 text-xs opacity-70">{markets.length}</span>
          </button>
          <button
            onClick={() => setAnomaliesOnly(true)}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-sm font-medium transition-colors ${
              anomaliesOnly
                ? 'bg-yellow-600 text-white'
                : 'bg-[#1a1d27] text-slate-400 hover:text-white border border-[#2a2d3a]'
            }`}
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            Anomalies
            {anomalyCount > 0 && (
              <span className="bg-yellow-500 text-black text-xs font-bold rounded-full w-4 h-4 flex items-center justify-center">
                {anomalyCount}
              </span>
            )}
          </button>

          {/* Sort segmented control */}
          <div className="flex items-center ml-2 border border-[#2a2d3a] rounded bg-[#1a1d27] overflow-hidden">
            <span className="text-[10px] uppercase tracking-widest text-slate-500 px-2">Sort</span>
            {SORT_OPTIONS.map((s) => {
              const Icon = s.icon
              const active = sort === s.id
              return (
                <button
                  key={s.id}
                  onClick={() => setSort(s.id)}
                  title={s.hint}
                  className={`flex items-center gap-1 px-2.5 py-1 text-xs border-l border-[#2a2d3a] transition-colors ${
                    active
                      ? 'bg-blue-600 text-white'
                      : 'text-slate-400 hover:text-white hover:bg-[#0f1117]'
                  }`}
                >
                  <Icon className="w-3 h-3" />
                  {s.label}
                </button>
              )
            })}
          </div>
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-2 px-3 py-1.5 rounded bg-[#1a1d27] border border-[#2a2d3a] text-slate-400 hover:text-white text-sm"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {isLoading && (
        <div className="text-slate-500 text-sm py-12 text-center">Loading Polymarket data…</div>
      )}

      {!isLoading && markets.length === 0 && (
        <div className="text-slate-500 text-sm py-12 text-center">
          No markets match the current filter. Try a different topic or click Refresh.
        </div>
      )}

      <div className="space-y-2">
        {markets.map((m) => (
          <MarketRow key={m.condition_id} market={m} topic={topicById.get(m.topic)} />
        ))}
      </div>
    </div>
  )
}

function TopicChip({
  label,
  count,
  active,
  color,
  dimmed,
  onClick,
}: {
  label: string
  count?: number
  active: boolean
  color?: string
  dimmed?: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
        active
          ? 'text-white border-transparent'
          : 'bg-[#1a1d27] text-slate-300 border-[#2a2d3a] hover:border-[#3b4058]'
      } ${dimmed && !active ? 'opacity-40' : ''}`}
      style={active ? { backgroundColor: color ?? '#2563eb' } : undefined}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span
          className={`text-[10px] font-mono rounded px-1 ${
            active ? 'bg-black/20' : 'bg-[#0f1117] text-slate-500'
          }`}
        >
          {count}
        </span>
      )}
    </button>
  )
}

function MarketRow({ market: m, topic }: { market: Market; topic?: Topic }) {
  const yesColor = m.yes_price >= 0.5 ? 'text-green-400' : 'text-red-400'
  const barWidth = Math.round(m.yes_price * 100)
  const dayUp = (m.price_change_24h ?? 0) >= 0
  const ChangeIcon = dayUp ? TrendingUp : TrendingDown

  return (
    <div
      className={`bg-[#1a1d27] border rounded-lg p-4 transition-colors ${
        m.is_anomaly
          ? 'border-yellow-500/50 bg-yellow-950/10'
          : 'border-[#2a2d3a] hover:border-[#3b4058]'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            {m.is_anomaly && (
              <span className="flex items-center gap-1 text-xs text-yellow-400 font-medium bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-0.5">
                <AlertTriangle className="w-3 h-3" />
                Anomaly
              </span>
            )}
            {topic && (
              <span
                className="text-[10px] font-medium px-1.5 py-0.5 rounded"
                style={{ background: `${topic.color}22`, color: topic.color }}
                title={topic.label}
              >
                {topic.icon} {topic.label}
              </span>
            )}
            {m.category && (
              <span className="text-xs text-slate-500 truncate">{m.category}</span>
            )}
          </div>
          <h3 className="text-sm font-medium text-slate-200 leading-snug">{m.question}</h3>
          {m.is_anomaly && m.anomaly_reason && (
            <p className="text-xs text-yellow-400/80 mt-1">{m.anomaly_reason}</p>
          )}
          <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
            <span>Vol: {fmtVolume(m.volume)}</span>
            <span>24h: {fmtVolume(m.volume_24h)}</span>
            {m.end_date && <span>Ends: {new Date(m.end_date).toLocaleDateString()}</span>}
            <span>{timeAgo(m.recorded_at)}</span>
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <a
            href={m.url}
            target="_blank"
            rel="noreferrer"
            className="text-slate-500 hover:text-slate-300"
          >
            <ExternalLink className="w-4 h-4" />
          </a>
          <div className="text-right">
            <div className={`font-mono font-bold text-lg ${yesColor}`}>
              {(m.yes_price * 100).toFixed(0)}%
            </div>
            <div className="text-xs text-slate-500">YES</div>
            {m.price_change_24h !== 0 && (
              <div
                className={`flex items-center justify-end gap-0.5 text-xs font-mono mt-1 ${
                  dayUp ? 'text-green-400' : 'text-red-400'
                }`}
              >
                <ChangeIcon className="w-3 h-3" />
                {(m.price_change_24h * 100).toFixed(1)}%
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-3 h-2 bg-[#0f1117] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            m.yes_price >= 0.5 ? 'bg-green-500' : 'bg-red-500'
          }`}
          style={{ width: `${barWidth}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-slate-600 mt-1 font-mono">
        <span>YES {(m.yes_price * 100).toFixed(1)}%</span>
        <span>NO {(m.no_price * 100).toFixed(1)}%</span>
      </div>
    </div>
  )
}
