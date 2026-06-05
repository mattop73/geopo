import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Play, Cpu, Sparkles, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiFetch, apiPost } from '../../api/client'
import { fmtDate } from '../../lib/format'

type ModelId = 'quant' | 'semantic'

interface ModelMetrics {
  model: ModelId
  scored_count: number
  direction_accuracy: number | null
  mean_abs_error_pct: number | null
  band_coverage: number | null
}

interface DailyAccuracy {
  date: string
  quant: number | null
  semantic: number | null
}

interface Performance {
  window_days: number
  models: ModelMetrics[]
  daily_accuracy: DailyAccuracy[]
}

interface Prediction {
  id: number
  model: ModelId
  ticker: string
  name: string
  category: string
  made_at: string | null
  target_at: string | null
  base_price: number | null
  predicted_direction: string | null
  predicted_change_pct: number | null
  confidence: number | null
  rationale: string | null
  actual_change_pct: number | null
  actual_direction: string | null
  direction_correct: boolean | null
  abs_error_pct: number | null
  in_band: boolean | null
  scored_at: string | null
}

const WINDOWS = [
  { days: 1, label: '24h' },
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
]

const MODEL_META: Record<ModelId, { label: string; icon: typeof Cpu; color: string }> = {
  quant: { label: 'Quant (statistical)', icon: Cpu, color: '#3b82f6' },
  semantic: { label: 'Semantic (LLM)', icon: Sparkles, color: '#a855f7' },
}

export default function PredictionsTab() {
  const [windowDays, setWindowDays] = useState(7)
  const [modelFilter, setModelFilter] = useState<ModelId | 'all'>('all')
  const [running, setRunning] = useState(false)

  const { data: perf, refetch: refetchPerf } = useQuery<Performance>({
    queryKey: ['predictions', 'performance', windowDays],
    queryFn: () => apiFetch(`/predictions/performance?window_days=${windowDays}`),
    refetchInterval: 5 * 60 * 1000,
  })

  const { data: predictions = [], refetch: refetchList } = useQuery<Prediction[]>({
    queryKey: ['predictions', 'list', modelFilter],
    queryFn: () =>
      apiFetch(`/predictions/?limit=100${modelFilter === 'all' ? '' : `&model=${modelFilter}`}`),
    refetchInterval: 5 * 60 * 1000,
  })

  const handleRun = async () => {
    setRunning(true)
    try {
      await apiPost('/predictions/run', {})
      await Promise.all([refetchPerf(), refetchList()])
    } finally {
      setRunning(false)
    }
  }

  const metricsByModel = (m: ModelId): ModelMetrics =>
    perf?.models.find(x => x.model === m) ?? {
      model: m,
      scored_count: 0,
      direction_accuracy: null,
      mean_abs_error_pct: null,
      band_coverage: null,
    }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-white">Next-hour predictions</h2>
          <p className="text-xs text-slate-500">
            Two models forecast every open commodity each hour; scored against the realized price.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-lg bg-[#0f1117] border border-[#2a2d3a] p-1">
            {WINDOWS.map(w => (
              <button
                key={w.days}
                onClick={() => setWindowDays(w.days)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  windowDays === w.days ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>
          <button
            onClick={handleRun}
            disabled={running}
            className="flex items-center gap-2 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm transition-colors"
          >
            {running ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            Run now
          </button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {(['quant', 'semantic'] as ModelId[]).map(m => (
          <ModelCard key={m} model={m} metrics={metricsByModel(m)} />
        ))}
      </div>

      {/* Accuracy over time */}
      <div className="bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-4">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3">
          Direction accuracy over time (%)
        </h3>
        {perf && perf.daily_accuracy.length > 0 ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={perf.daily_accuracy} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
              <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
              <YAxis domain={[0, 100]} stroke="#64748b" fontSize={11} />
              <Tooltip
                contentStyle={{ background: '#0f1117', border: '1px solid #2a2d3a', borderRadius: 8 }}
                labelStyle={{ color: '#e2e8f0' }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="quant"
                name="Quant"
                stroke={MODEL_META.quant.color}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="semantic"
                name="Semantic"
                stroke={MODEL_META.semantic.color}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="text-slate-500 text-sm py-12 text-center">
            No scored predictions yet. Predictions are resolved one hour after they're made —
            hit "Run now" to seed, then again next hour to score.
          </div>
        )}
      </div>

      {/* Recent predictions */}
      <div className="bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Recent predictions
          </h3>
          <div className="flex gap-1 rounded-lg bg-[#0f1117] border border-[#2a2d3a] p-1">
            {(['all', 'quant', 'semantic'] as const).map(m => (
              <button
                key={m}
                onClick={() => setModelFilter(m)}
                className={`px-2.5 py-1 rounded text-xs font-medium capitalize transition-colors ${
                  modelFilter === m ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <PredictionsTable predictions={predictions} />
      </div>
    </div>
  )
}

function ModelCard({ model, metrics }: { model: ModelId; metrics: ModelMetrics }) {
  const { label, icon: Icon, color } = MODEL_META[model]
  return (
    <div className="bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-4">
      <div className="flex items-center gap-2 mb-4">
        <Icon className="w-4 h-4" style={{ color }} />
        <span className="font-semibold text-white">{label}</span>
        <span className="ml-auto text-xs text-slate-500">{metrics.scored_count} scored</span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Stat
          label="Direction acc."
          value={metrics.direction_accuracy != null ? `${metrics.direction_accuracy.toFixed(1)}%` : '—'}
          highlight
        />
        <Stat
          label="Mean abs err"
          value={metrics.mean_abs_error_pct != null ? `${metrics.mean_abs_error_pct.toFixed(2)}%` : '—'}
        />
        <Stat
          label="Band coverage"
          value={metrics.band_coverage != null ? `${metrics.band_coverage.toFixed(0)}%` : 'n/a'}
        />
      </div>
    </div>
  )
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div className={`font-mono font-semibold ${highlight ? 'text-xl text-white' : 'text-lg text-slate-200'}`}>
        {value}
      </div>
      <div className="text-[11px] text-slate-500 mt-0.5">{label}</div>
    </div>
  )
}

function DirectionBadge({ direction }: { direction: string | null }) {
  if (direction === 'up') return <span className="inline-flex items-center gap-1 text-green-400"><TrendingUp className="w-3.5 h-3.5" />up</span>
  if (direction === 'down') return <span className="inline-flex items-center gap-1 text-red-400"><TrendingDown className="w-3.5 h-3.5" />down</span>
  return <span className="inline-flex items-center gap-1 text-slate-400"><Minus className="w-3.5 h-3.5" />flat</span>
}

function PredictionsTable({ predictions }: { predictions: Prediction[] }) {
  if (predictions.length === 0) {
    return <div className="text-slate-500 text-sm py-8 text-center">No predictions yet.</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-[#2a2d3a]">
            <th className="py-2 pr-3 font-medium">Commodity</th>
            <th className="py-2 px-3 font-medium">Model</th>
            <th className="py-2 px-3 font-medium">Target hour</th>
            <th className="py-2 px-3 font-medium">Predicted</th>
            <th className="py-2 px-3 font-medium">Actual</th>
            <th className="py-2 px-3 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {predictions.map(p => (
            <tr key={p.id} className="border-b border-[#23262f] hover:bg-[#20242f] transition-colors">
              <td className="py-2 pr-3">
                <div className="text-slate-200">{p.name}</div>
                <div className="text-[11px] text-slate-500 font-mono">{p.ticker}</div>
              </td>
              <td className="py-2 px-3">
                <span
                  className="text-xs px-1.5 py-0.5 rounded"
                  style={{ color: MODEL_META[p.model].color, background: `${MODEL_META[p.model].color}1a` }}
                >
                  {p.model}
                </span>
              </td>
              <td className="py-2 px-3 text-slate-400 whitespace-nowrap">{fmtDate(p.target_at)}</td>
              <td className="py-2 px-3">
                <DirectionBadge direction={p.predicted_direction} />
                {p.predicted_change_pct != null && (
                  <span className="ml-2 font-mono text-xs text-slate-400">
                    {p.predicted_change_pct >= 0 ? '+' : ''}{p.predicted_change_pct.toFixed(2)}%
                  </span>
                )}
                {p.confidence != null && (
                  <span className="ml-2 text-[11px] text-slate-500">conf {(p.confidence * 100).toFixed(0)}%</span>
                )}
              </td>
              <td className="py-2 px-3">
                {p.scored_at ? (
                  <>
                    <DirectionBadge direction={p.actual_direction} />
                    {p.actual_change_pct != null && (
                      <span className="ml-2 font-mono text-xs text-slate-400">
                        {p.actual_change_pct >= 0 ? '+' : ''}{p.actual_change_pct.toFixed(2)}%
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-xs text-slate-600">pending</span>
                )}
              </td>
              <td className="py-2 px-3">
                {p.scored_at ? (
                  p.direction_correct ? (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-green-500/15 text-green-400">hit</span>
                  ) : (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/15 text-red-400">miss</span>
                  )
                ) : (
                  <span className="text-xs text-slate-600">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
