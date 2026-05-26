import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { apiFetch, apiPost } from '../../api/client'
import { fmtPrice, fmtPct } from '../../lib/format'
import CommodityChart from './CommodityChart'
import CommoditiesOverviewChart from './CommoditiesOverviewChart'

interface Commodity {
  ticker: string
  name: string
  category: string
  price: number
  previous_close: number
  change_pct: number
  volume: number
  fetched_at: string
}

const CATEGORIES = ['energy', 'metals', 'agriculture', 'forex']
const CATEGORY_LABELS: Record<string, string> = {
  energy: 'Energy', metals: 'Metals', agriculture: 'Agriculture', forex: 'FX / Indices'
}

export default function CommoditiesTab() {
  const [selected, setSelected] = useState<Commodity | null>(null)
  const [activeCategory, setActiveCategory] = useState<string>('all')

  const { data: commodities = [], isLoading, refetch } = useQuery<Commodity[]>({
    queryKey: ['commodities'],
    queryFn: () => apiFetch('/commodities/'),
    refetchInterval: 5 * 60 * 1000,
  })

  const handleRefresh = async () => {
    await apiPost('/commodities/refresh', {})
    refetch()
  }

  const filtered = useMemo(
    () => activeCategory === 'all'
      ? commodities
      : commodities.filter(c => c.category === activeCategory),
    [activeCategory, commodities],
  )
  const overviewTickers = useMemo(() => filtered.map(c => c.ticker), [filtered])
  const overviewTitle = activeCategory === 'all'
    ? 'All commodities — normalized'
    : `${CATEGORY_LABELS[activeCategory]} — normalized`

  useEffect(() => {
    if (selected && !filtered.some(c => c.ticker === selected.ticker)) {
      setSelected(null)
    }
  }, [filtered, selected])

  const grouped: Record<string, Commodity[]> = {}
  for (const c of filtered) {
    if (!grouped[c.category]) grouped[c.category] = []
    grouped[c.category].push(c)
  }

  return (
    <div className="space-y-6">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button
            onClick={() => setActiveCategory('all')}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${activeCategory === 'all' ? 'bg-blue-600 text-white' : 'bg-[#1a1d27] text-slate-400 hover:text-white border border-[#2a2d3a]'}`}
          >
            All
          </button>
          {CATEGORIES.map(cat => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`px-3 py-1 rounded text-sm font-medium capitalize transition-colors ${activeCategory === cat ? 'bg-blue-600 text-white' : 'bg-[#1a1d27] text-slate-400 hover:text-white border border-[#2a2d3a]'}`}
            >
              {CATEGORY_LABELS[cat]}
            </button>
          ))}
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-2 px-3 py-1.5 rounded bg-[#1a1d27] border border-[#2a2d3a] text-slate-400 hover:text-white text-sm transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {isLoading && (
        <div className="text-slate-500 text-sm py-12 text-center">Loading commodity data…</div>
      )}

      {/* Multi-commodity overview chart (normalized %) */}
      <CommoditiesOverviewChart
        tickers={overviewTickers}
        title={overviewTitle}
      />

      {/* Single-commodity OHLC chart panel */}
      {selected && (
        <div className="bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="font-semibold text-white">{selected.name}</h2>
              <span className="text-xs text-slate-500 font-mono">{selected.ticker}</span>
            </div>
            <div className="text-right">
              <div className="font-mono text-lg text-white">{fmtPrice(selected.price)}</div>
              <div className={`text-sm font-mono ${selected.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {fmtPct(selected.change_pct)}
              </div>
            </div>
          </div>
          <CommodityChart ticker={selected.ticker} />
        </div>
      )}

      {/* KPI Grid */}
      {(activeCategory === 'all' ? CATEGORIES : [activeCategory]).map(cat => {
        const items = grouped[cat]
        if (!items?.length) return null
        return (
          <div key={cat}>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3">
              {CATEGORY_LABELS[cat]}
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
              {items.map(c => (
                <CommodityCard
                  key={c.ticker}
                  commodity={c}
                  isSelected={selected?.ticker === c.ticker}
                  onClick={() => setSelected(selected?.ticker === c.ticker ? null : c)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CommodityCard({
  commodity: c,
  isSelected,
  onClick,
}: {
  commodity: Commodity
  isSelected: boolean
  onClick: () => void
}) {
  const up = c.change_pct >= 0
  return (
    <button
      onClick={onClick}
      className={`text-left p-3 rounded-lg border transition-all ${
        isSelected
          ? 'border-blue-500 bg-blue-950/30'
          : 'border-[#2a2d3a] bg-[#1a1d27] hover:border-[#3b4058]'
      }`}
    >
      <div className="text-xs text-slate-500 font-mono truncate">{c.ticker}</div>
      <div className="text-sm font-medium text-slate-200 truncate mt-0.5">{c.name}</div>
      <div className="font-mono font-semibold text-white mt-1">{fmtPrice(c.price)}</div>
      <div className={`text-xs font-mono mt-0.5 ${up ? 'text-green-400' : 'text-red-400'}`}>
        {up ? '▲' : '▼'} {fmtPct(c.change_pct)}
      </div>
    </button>
  )
}
