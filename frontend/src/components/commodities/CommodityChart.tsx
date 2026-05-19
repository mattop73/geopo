import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createChart, IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { apiFetch } from '../../api/client'

interface OHLCV {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

const PERIODS = [
  { label: '1W', period: '5d',  interval: '1h' },
  { label: '1M', period: '1mo', interval: '1d' },
  { label: '3M', period: '3mo', interval: '1d' },
  { label: '6M', period: '6mo', interval: '1d' },
  { label: '1Y', period: '1y',  interval: '1wk' },
]

export default function CommodityChart({ ticker }: { ticker: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const [period, setPeriod] = useState(PERIODS[2])

  const { data = [], isLoading } = useQuery<OHLCV[]>({
    queryKey: ['commodity-history', ticker, period.period, period.interval],
    queryFn: () =>
      apiFetch(`/commodities/${encodeURIComponent(ticker)}/history?period=${period.period}&interval=${period.interval}`),
  })

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#1a1d27' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#2a2d3a' }, horzLines: { color: '#2a2d3a' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#2a2d3a' },
      timeScale: { borderColor: '#2a2d3a', timeVisible: true },
      width: containerRef.current.clientWidth,
      height: 320,
    })
    chartRef.current = chart
    seriesRef.current = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current?.clientWidth ?? 600 })
    })
    ro.observe(containerRef.current)
    return () => { chart.remove(); ro.disconnect(); chartRef.current = null; seriesRef.current = null }
  }, [])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!chart || !series || !data.length) return
    series.setData(
      data.map(d => ({
        time: d.time as unknown as Time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      })),
    )
    chart.timeScale().fitContent()
  }, [data])

  return (
    <div>
      <div className="flex gap-1 mb-3">
        {PERIODS.map(p => (
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
      </div>
      {isLoading && (
        <div className="h-80 flex items-center justify-center text-slate-500 text-sm">
          Loading chart…
        </div>
      )}
      <div ref={containerRef} className="tv-chart" style={{ display: isLoading ? 'none' : 'block' }} />
    </div>
  )
}
