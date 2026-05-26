import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createChart,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts'
import { Eye, EyeOff, RotateCcw } from 'lucide-react'
import { apiFetch } from '../../api/client'
import { fmtPct } from '../../lib/format'

interface Point { time: number; close: number }
interface CommodityHistory {
  ticker: string
  name: string
  category: string
  points: Point[]
}
interface HistoryResponse {
  period: string
  interval: string
  commodities: CommodityHistory[]
}

const PERIODS = [
  { label: '1W', period: '5d',  interval: '1h' },
  { label: '1M', period: '1mo', interval: '1d' },
  { label: '3M', period: '3mo', interval: '1d' },
  { label: '6M', period: '6mo', interval: '1d' },
  { label: '1Y', period: '1y',  interval: '1wk' },
] as const

export interface CommoditiesOverviewChartProps {
  /** Optional subset of tickers to plot (e.g. theme.commodities). When omitted,
   *  every tracked commodity is loaded. */
  tickers?: string[]
  /** Chart height in pixels. Default 420 (full-page mode). Use ~240 for inline. */
  height?: number
  /** Header title shown above the chart. */
  title?: string
  /** Subtitle / hint text shown under the title. */
  subtitle?: string
  /** Hide the toggleable legend strip (useful for very compact embeds). */
  hideLegend?: boolean
  /** Initial period; defaults to 1 month. */
  defaultPeriodLabel?: '1W' | '1M' | '3M' | '6M' | '1Y'
  /** When true, drop the card chrome (border + bg) — useful when the parent
   *  already provides its own panel (e.g. inside a ThemeCard). */
  bare?: boolean
}

// Distinct, accessible palette — picked so adjacent commodities don't clash.
const PALETTE = [
  '#60a5fa', '#22c55e', '#f59e0b', '#ef4444', '#a855f7',
  '#14b8a6', '#f97316', '#ec4899', '#84cc16', '#06b6d4',
  '#eab308', '#8b5cf6', '#10b981', '#f43f5e', '#3b82f6',
  '#d946ef', '#0ea5e9', '#65a30d', '#dc2626', '#7c3aed',
  '#fbbf24', '#34d399',
]

const CATEGORY_COLORS: Record<string, string> = {
  energy: '#f97316',
  metals: '#fbbf24',
  agriculture: '#22c55e',
  forex: '#60a5fa',
}

type ColorMode = 'unique' | 'category'

export default function CommoditiesOverviewChart({
  tickers,
  height = 420,
  title = 'All commodities — normalized',
  subtitle = 'Percent change from start of window · scroll / drag to pan · pinch or mouse-wheel on axis to zoom',
  hideLegend = false,
  defaultPeriodLabel = '1M',
  bare = false,
}: CommoditiesOverviewChartProps = {}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const [period, setPeriod] = useState<typeof PERIODS[number]>(
    () => PERIODS.find((p) => p.label === defaultPeriodLabel) ?? PERIODS[1],
  )
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [hovered, setHovered] = useState<{ ticker: string; pct: number } | null>(null)
  const [colorMode] = useState<ColorMode>('unique')

  // Stable cache key + URL when caller passes a ticker subset.
  const tickersKey = tickers && tickers.length > 0 ? tickers.join(',') : ''
  const { data, isLoading, isFetching } = useQuery<HistoryResponse>({
    queryKey: ['commodities-history-all', period.period, period.interval, tickersKey],
    queryFn: () => {
      const params = new URLSearchParams({
        period: period.period,
        interval: period.interval,
      })
      if (tickersKey) params.set('tickers', tickersKey)
      return apiFetch(`/commodities/history/all?${params.toString()}`)
    },
    staleTime: 60_000,
    // Skip the fetch entirely if the caller passed an empty list — avoids
    // accidentally loading every commodity when the theme has none linked.
    enabled: tickers === undefined || tickers.length > 0,
  })

  // Stable color assignment keyed by ticker so toggling doesn't reshuffle.
  const colorByTicker = useMemo(() => {
    const m = new Map<string, string>()
    if (!data) return m
    data.commodities.forEach((c, i) => {
      m.set(
        c.ticker,
        colorMode === 'category'
          ? CATEGORY_COLORS[c.category] ?? PALETTE[i % PALETTE.length]
          : PALETTE[i % PALETTE.length],
      )
    })
    return m
  }, [data, colorMode])

  // ---- Chart lifecycle ---------------------------------------------------
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    let disposed = false
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#1a1d27' },
        textColor: '#94a3b8',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#23263180' },
        horzLines: { color: '#23263180' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: {
        borderColor: '#2a2d3a',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: '#2a2d3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      width: container.clientWidth,
      height,
    })
    chartRef.current = chart

    // Reference 0% line so users can immediately see who's above/below.
    const refSeries = chart.addLineSeries({
      color: '#475569',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    seriesRef.current.set('__ref__', refSeries)

    const ro = new ResizeObserver(() => {
      if (disposed) return
      chart.applyOptions({ width: container.clientWidth || 600 })
    })
    ro.observe(container)

    chart.subscribeCrosshairMove((param) => {
      if (disposed) return
      if (!param.time || !param.seriesData.size) {
        setHovered(null)
        return
      }
      // Find the topmost (largest pct) series under the crosshair.
      let best: { ticker: string; pct: number } | null = null
      for (const [ticker, series] of seriesRef.current) {
        if (ticker === '__ref__') continue
        const v = param.seriesData.get(series) as { value?: number } | undefined
        if (v?.value == null) continue
        if (!best || Math.abs(v.value) > Math.abs(best.pct)) {
          best = { ticker, pct: v.value }
        }
      }
      setHovered(best)
    })

    return () => {
      disposed = true
      ro.disconnect()
      chartRef.current = null
      seriesRef.current.clear()
      chart.remove()
    }
  }, [])

  // ---- Push data into chart whenever it (or hidden state) changes -------
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !data) return

    // Clear all existing commodity series (keep __ref__).
    for (const [ticker, series] of seriesRef.current) {
      if (ticker === '__ref__') continue
      chart.removeSeries(series)
    }
    const refSeries = seriesRef.current.get('__ref__')
    seriesRef.current.clear()
    if (refSeries) seriesRef.current.set('__ref__', refSeries)

    // Determine global time range to render the dashed 0% reference line.
    let tMin = Infinity
    let tMax = -Infinity

    for (const c of data.commodities) {
      if (c.points.length < 2) continue
      const base = c.points[0].close
      if (!base) continue

      const normalized = c.points.map((p) => ({
        time: p.time as unknown as Time,
        value: ((p.close - base) / base) * 100,
      }))
      tMin = Math.min(tMin, c.points[0].time)
      tMax = Math.max(tMax, c.points[c.points.length - 1].time)

      const series = chart.addLineSeries({
        color: colorByTicker.get(c.ticker) ?? '#60a5fa',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerRadius: 3,
        title: c.name,
        visible: !hidden.has(c.ticker),
      })
      series.setData(normalized)
      seriesRef.current.set(c.ticker, series)
    }

    if (refSeries && Number.isFinite(tMin) && Number.isFinite(tMax)) {
      refSeries.setData([
        { time: tMin as unknown as Time, value: 0 },
        { time: tMax as unknown as Time, value: 0 },
      ])
    }

    chart.timeScale().fitContent()
  }, [data, colorByTicker])

  // Toggle visibility without rebuilding series.
  useEffect(() => {
    for (const [ticker, series] of seriesRef.current) {
      if (ticker === '__ref__') continue
      series.applyOptions({ visible: !hidden.has(ticker) })
    }
  }, [hidden])

  // ---- Derived stats for legend ----------------------------------------
  const stats = useMemo(() => {
    if (!data) return []
    return data.commodities
      .map((c) => {
        if (c.points.length < 2) return null
        const base = c.points[0].close
        const last = c.points[c.points.length - 1].close
        const pct = base ? ((last - base) / base) * 100 : 0
        return {
          ticker: c.ticker,
          name: c.name,
          category: c.category,
          pct,
          color: colorByTicker.get(c.ticker) ?? '#60a5fa',
        }
      })
      .filter((x): x is NonNullable<typeof x> => x != null)
      .sort((a, b) => b.pct - a.pct)
  }, [data, colorByTicker])

  const toggle = (ticker: string) =>
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(ticker)) next.delete(ticker)
      else next.add(ticker)
      return next
    })

  const allOff = stats.length > 0 && hidden.size === stats.length
  const setAll = (visible: boolean) =>
    setHidden(visible ? new Set() : new Set(stats.map((s) => s.ticker)))

  const resetZoom = () => chartRef.current?.timeScale().fitContent()

  return (
    <div className={bare ? '' : 'bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-4'}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        {(title || subtitle) ? (
          <div>
            {title && <h2 className="font-semibold text-white">{title}</h2>}
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
        ) : (
          // Spacer so period buttons stay on the right when no header.
          <div />
        )}
        <div className="flex items-center gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.label}
              onClick={() => setPeriod(p)}
              className={`px-2.5 py-1 rounded text-xs font-mono font-medium transition-colors ${
                period.label === p.label
                  ? 'bg-blue-600 text-white'
                  : 'bg-[#0f1117] text-slate-500 hover:text-white border border-[#2a2d3a]'
              }`}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={resetZoom}
            title="Reset zoom"
            className="ml-2 flex items-center gap-1 px-2 py-1 rounded text-xs bg-[#0f1117] text-slate-400 hover:text-white border border-[#2a2d3a]"
          >
            <RotateCcw className="w-3 h-3" />
            Reset
          </button>
          <button
            onClick={() => setAll(allOff)}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-[#0f1117] text-slate-400 hover:text-white border border-[#2a2d3a]"
          >
            {allOff ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            {allOff ? 'Show all' : 'Hide all'}
          </button>
        </div>
      </div>

      {/* Hover readout */}
      <div className="h-5 mb-1 text-xs font-mono text-slate-400">
        {hovered ? (
          <>
            <span className="text-slate-200">{hovered.ticker}</span>{' '}
            <span className={hovered.pct >= 0 ? 'text-green-400' : 'text-red-400'}>
              {fmtPct(hovered.pct)}
            </span>
          </>
        ) : isFetching ? (
          'Loading…'
        ) : (
          ''
        )}
      </div>

      {/* Chart */}
      <div className="relative">
        {isLoading && (
          <div
            className="flex items-center justify-center text-slate-500 text-sm"
            style={{ height }}
          >
            Loading multi-commodity chart…
          </div>
        )}
        {!isLoading && (!data || data.commodities.length === 0) && (
          <div
            className="flex items-center justify-center text-slate-500 text-sm"
            style={{ height }}
          >
            No linked commodities to plot.
          </div>
        )}
        <div
          ref={containerRef}
          style={{
            height,
            visibility: isLoading || !data || data.commodities.length === 0 ? 'hidden' : 'visible',
          }}
        />
      </div>

      {/* Legend */}
      {!hideLegend && stats.length > 0 && (
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-1.5">
          {stats.map((s) => {
            const isHidden = hidden.has(s.ticker)
            const up = s.pct >= 0
            return (
              <button
                key={s.ticker}
                onClick={() => toggle(s.ticker)}
                title={`${s.ticker} · click to ${isHidden ? 'show' : 'hide'}`}
                className={`flex items-center gap-2 px-2 py-1 rounded text-xs border transition-all text-left ${
                  isHidden
                    ? 'border-[#2a2d3a] bg-[#0f1117] opacity-40 hover:opacity-70'
                    : 'border-[#2a2d3a] bg-[#0f1117] hover:border-[#3b4058]'
                }`}
              >
                <span
                  className="w-3 h-0.5 shrink-0 rounded"
                  style={{ background: s.color }}
                />
                <span className="truncate text-slate-300 flex-1">{s.name}</span>
                <span
                  className={`font-mono shrink-0 ${
                    up ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {fmtPct(s.pct)}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
