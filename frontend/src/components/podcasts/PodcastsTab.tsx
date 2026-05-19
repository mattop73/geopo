import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ExternalLink,
  RefreshCw,
  Mic2,
  Clock,
  AlertCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Sparkles,
} from 'lucide-react'

import { apiFetch, apiPost } from '../../api/client'
import { timeAgo } from '../../lib/format'

// --------------------------------------------------------------------------
// Types — mirrors backend/services/podcast_service.py response shapes
// --------------------------------------------------------------------------

interface Channel {
  id: number
  slug: string
  name: string
  language: string
  youtube_channel_id: string | null
  description: string | null
  active: boolean
  episode_count: number
  pending_count: number
}

interface EpisodeSummary {
  tldr: string[]
  key_topics: { label: string; summary: string }[]
  notable_quotes: { speaker: string | null; quote: string }[]
  geopolitics_tags: string[]
}

interface EpisodeListItem {
  id: number
  youtube_video_id: string
  youtube_url: string
  title: string
  description: string | null
  published_at: string | null
  duration_sec: number | null
  thumbnail_url: string | null
  channel: { slug: string; name: string; language: string }
  has_transcript: boolean
  transcript_lang: string | null
  summary: EpisodeSummary | null
  summary_model: string | null
  summary_at: string | null
  error: string | null
}

interface EpisodeDetail extends EpisodeListItem {
  transcript: string | null
}

// --------------------------------------------------------------------------
// Tab
// --------------------------------------------------------------------------

export default function PodcastsTab() {
  const queryClient = useQueryClient()
  const [activeChannel, setActiveChannel] = useState<string>('all')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const { data: channels = [] } = useQuery<Channel[]>({
    queryKey: ['podcast-channels'],
    queryFn: () => apiFetch('/podcasts/channels'),
    refetchInterval: 30_000,
  })

  const { data: episodes = [], isLoading } = useQuery<EpisodeListItem[]>({
    queryKey: ['podcast-episodes', activeChannel],
    queryFn: () => {
      const qs = new URLSearchParams({ limit: '120' })
      if (activeChannel !== 'all') qs.set('channel', activeChannel)
      return apiFetch(`/podcasts/episodes?${qs.toString()}`)
    },
    refetchInterval: 30_000,
  })

  // Auto-select the first episode whenever the channel filter changes (or on
  // first load). Keeps the detail pane never-empty.
  useEffect(() => {
    if (episodes.length === 0) return
    if (selectedId == null || !episodes.find((e) => e.id === selectedId)) {
      setSelectedId(episodes[0].id)
    }
  }, [episodes, selectedId])

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      await apiPost('/podcasts/refresh?max_process=3', {})
      // Refetch on a short delay so we surface the new "pending → done" state.
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['podcast-episodes'] })
        queryClient.invalidateQueries({ queryKey: ['podcast-channels'] })
      }, 1500)
    } finally {
      setIsRefreshing(false)
    }
  }

  const totalPending = channels.reduce((n, c) => n + c.pending_count, 0)

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-4 items-start">
      {/* LEFT — channel filter + episode list */}
      <div className="space-y-3 min-w-0">
        {/* Channel chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500 mr-1">
            Channel
          </span>
          <ChannelChip
            label="All"
            active={activeChannel === 'all'}
            count={channels.reduce((n, c) => n + c.episode_count, 0)}
            onClick={() => setActiveChannel('all')}
          />
          {channels.map((c) => (
            <ChannelChip
              key={c.slug}
              label={`${c.language === 'fr' ? '🇫🇷' : '🇺🇸'} ${c.name}`}
              count={c.episode_count}
              pending={c.pending_count}
              active={activeChannel === c.slug}
              onClick={() => setActiveChannel(c.slug)}
            />
          ))}
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="ml-auto flex items-center gap-2 px-3 py-1.5 rounded bg-[#1a1d27] border border-[#2a2d3a] text-slate-400 hover:text-white text-xs disabled:opacity-50"
            title={`${totalPending} episode(s) pending summarization`}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {/* Pending hint */}
        {totalPending > 0 && (
          <div className="text-[11px] text-amber-400/70 px-1 flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 animate-spin" />
            {totalPending} episode{totalPending > 1 ? 's' : ''} queued — summaries
            arrive a few at a time (cost-capped).
          </div>
        )}

        {/* Episode list */}
        <div className="space-y-2 max-h-[calc(100vh-220px)] overflow-y-auto pr-1">
          {isLoading && (
            <div className="text-slate-500 text-sm py-12 text-center">
              Loading episodes…
            </div>
          )}
          {!isLoading && episodes.length === 0 && (
            <div className="text-slate-500 text-sm py-12 text-center">
              No episodes yet — click <strong>Refresh</strong> to discover.
            </div>
          )}
          {episodes.map((ep) => (
            <EpisodeCard
              key={ep.id}
              ep={ep}
              selected={ep.id === selectedId}
              onSelect={() => setSelectedId(ep.id)}
            />
          ))}
        </div>
      </div>

      {/* RIGHT — detail panel */}
      <div className="xl:sticky xl:top-2">
        {selectedId == null ? (
          <div className="text-slate-600 text-sm py-20 text-center border border-dashed border-[#2a2d3a] rounded-lg">
            Select an episode to view its summary.
          </div>
        ) : (
          <EpisodeDetailPanel episodeId={selectedId} />
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------
// Channel chip
// --------------------------------------------------------------------------

function ChannelChip({
  label,
  count,
  pending,
  active,
  onClick,
}: {
  label: string
  count: number
  pending?: number
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
        active
          ? 'bg-blue-600 text-white border-transparent'
          : 'bg-[#1a1d27] text-slate-300 border-[#2a2d3a] hover:border-[#3b4058]'
      }`}
    >
      <span>{label}</span>
      <span
        className={`text-[10px] font-mono rounded px-1 ${
          active ? 'bg-black/20' : 'bg-[#0f1117] text-slate-500'
        }`}
      >
        {count}
      </span>
      {pending != null && pending > 0 && (
        <span className="text-[10px] text-amber-400" title={`${pending} pending`}>
          •
        </span>
      )}
    </button>
  )
}

// --------------------------------------------------------------------------
// Episode card (list item)
// --------------------------------------------------------------------------

function EpisodeCard({
  ep,
  selected,
  onSelect,
}: {
  ep: EpisodeListItem
  selected: boolean
  onSelect: () => void
}) {
  const status = ep.summary ? 'ready' : ep.error ? 'error' : 'pending'

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left bg-[#1a1d27] border rounded-lg p-2.5 hover:border-[#3b4058] transition-colors group ${
        selected ? 'border-blue-500' : 'border-[#2a2d3a]'
      }`}
    >
      <div className="flex gap-2.5">
        {ep.thumbnail_url ? (
          <img
            src={ep.thumbnail_url}
            alt=""
            className="w-20 h-12 object-cover rounded shrink-0"
          />
        ) : (
          <div className="w-20 h-12 rounded bg-[#0f1117] flex items-center justify-center shrink-0">
            <Mic2 className="w-4 h-4 text-slate-600" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[10px] font-semibold text-blue-400 uppercase tracking-wide truncate">
              {ep.channel.name}
            </span>
            <span className="text-[10px] text-slate-500 shrink-0">
              {timeAgo(ep.published_at)}
            </span>
            <StatusDot status={status} />
          </div>
          <h3 className="text-[13px] font-medium text-slate-100 leading-tight line-clamp-2 group-hover:text-white">
            {ep.title}
          </h3>
        </div>
      </div>
    </button>
  )
}

function StatusDot({ status }: { status: 'ready' | 'pending' | 'error' }) {
  if (status === 'ready') {
    return (
      <span
        className="ml-auto w-1.5 h-1.5 rounded-full bg-green-500 shrink-0"
        title="Summary ready"
      />
    )
  }
  if (status === 'error') {
    return (
      <AlertCircle
        className="ml-auto w-3 h-3 text-red-400 shrink-0"
        aria-label="Error — see detail panel"
      />
    )
  }
  return (
    <Loader2
      className="ml-auto w-3 h-3 text-amber-400 animate-spin shrink-0"
      aria-label="Pending"
    />
  )
}

// --------------------------------------------------------------------------
// Detail panel
// --------------------------------------------------------------------------

function EpisodeDetailPanel({ episodeId }: { episodeId: number }) {
  const queryClient = useQueryClient()
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [reprocessing, setReprocessing] = useState(false)

  const { data: ep, isLoading } = useQuery<EpisodeDetail>({
    queryKey: ['podcast-episode', episodeId],
    queryFn: () => apiFetch(`/podcasts/episodes/${episodeId}`),
    // Poll while still pending — stop polling once summarized.
    refetchInterval: (q) => (q.state.data?.summary ? false : 8000),
  })

  if (isLoading || !ep) {
    return (
      <div className="text-slate-500 text-sm py-20 text-center border border-[#2a2d3a] rounded-lg bg-[#1a1d27]">
        Loading…
      </div>
    )
  }

  const handleReprocess = async () => {
    setReprocessing(true)
    try {
      await apiPost(`/podcasts/episodes/${ep.id}/reprocess`, {})
      await apiPost('/podcasts/refresh?max_process=1', {})
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['podcast-episode', ep.id] })
        queryClient.invalidateQueries({ queryKey: ['podcast-episodes'] })
      }, 1500)
    } finally {
      setReprocessing(false)
    }
  }

  return (
    <div className="bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-4 space-y-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[11px] font-semibold text-blue-400 uppercase tracking-wide">
            {ep.channel.name}
          </span>
          {ep.published_at && (
            <span className="text-[11px] text-slate-500 inline-flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {timeAgo(ep.published_at)}
            </span>
          )}
          <a
            href={ep.youtube_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-white"
          >
            Open on YouTube <ExternalLink className="w-3 h-3" />
          </a>
        </div>
        <h2 className="text-base font-semibold text-slate-100 leading-snug">
          {ep.title}
        </h2>
      </div>

      {/* Error state */}
      {ep.error && !ep.summary && (
        <div className="border border-red-500/30 bg-red-500/5 rounded p-3 text-[12px] text-red-300 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="flex-1">
            <div className="font-semibold mb-0.5">Processing failed</div>
            <div className="text-red-300/80">{ep.error}</div>
          </div>
          <button
            onClick={handleReprocess}
            disabled={reprocessing}
            className="text-[11px] px-2 py-1 rounded bg-[#1a1d27] border border-red-500/30 hover:border-red-500 disabled:opacity-50"
          >
            Retry
          </button>
        </div>
      )}

      {/* Pending state */}
      {!ep.summary && !ep.error && (
        <div className="border border-amber-500/30 bg-amber-500/5 rounded p-3 text-[12px] text-amber-200 flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Queued. Transcript + Sonnet summary usually take 30-60s once a worker
          picks it up.
        </div>
      )}

      {/* Summary */}
      {ep.summary && (
        <>
          <SummaryBlock summary={ep.summary} />
          <div className="text-[10px] text-slate-600 flex items-center gap-2">
            <Sparkles className="w-3 h-3" />
            Summarized by {ep.summary_model ?? '?'} ·{' '}
            {ep.summary_at ? timeAgo(ep.summary_at) : '—'}
            <button
              onClick={handleReprocess}
              disabled={reprocessing}
              className="ml-auto text-[10px] underline hover:text-slate-300 disabled:opacity-50"
            >
              Regenerate
            </button>
          </div>
        </>
      )}

      {/* Transcript (collapsed by default) */}
      {ep.transcript && (
        <div className="border-t border-[#2a2d3a] pt-3">
          <button
            onClick={() => setTranscriptOpen((v) => !v)}
            className="flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-slate-500 hover:text-slate-300"
          >
            {transcriptOpen ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
            Full transcript ({ep.transcript_lang ?? '?'} ·{' '}
            {Math.round(ep.transcript.length / 1000)}k chars)
          </button>
          {transcriptOpen && (
            <pre className="mt-2 text-[11px] text-slate-400 whitespace-pre-wrap leading-relaxed max-h-[400px] overflow-y-auto p-2 bg-[#0f1117] rounded border border-[#2a2d3a]">
              {ep.transcript}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------
// Summary block — renders tldr / topics / quotes / tags
// --------------------------------------------------------------------------

function SummaryBlock({ summary }: { summary: EpisodeSummary }) {
  return (
    <div className="space-y-4">
      {/* TL;DR */}
      <section>
        <h3 className="text-[11px] uppercase tracking-widest text-slate-500 mb-1.5">
          TL;DR
        </h3>
        <ul className="space-y-1.5">
          {summary.tldr.map((t, i) => (
            <li
              key={i}
              className="text-[13px] text-slate-200 leading-snug pl-4 relative"
            >
              <span className="absolute left-0 top-1.5 w-1.5 h-1.5 rounded-full bg-blue-500" />
              {t}
            </li>
          ))}
        </ul>
      </section>

      {/* Key topics */}
      {summary.key_topics?.length > 0 && (
        <section>
          <h3 className="text-[11px] uppercase tracking-widest text-slate-500 mb-1.5">
            Key topics
          </h3>
          <div className="space-y-2">
            {summary.key_topics.map((t, i) => (
              <div
                key={i}
                className="bg-[#0f1117] border border-[#2a2d3a] rounded p-2.5"
              >
                <div className="text-[12px] font-semibold text-blue-300 mb-0.5">
                  {t.label}
                </div>
                <div className="text-[12px] text-slate-300 leading-snug">
                  {t.summary}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Notable quotes */}
      {summary.notable_quotes?.length > 0 && (
        <section>
          <h3 className="text-[11px] uppercase tracking-widest text-slate-500 mb-1.5">
            Notable quotes
          </h3>
          <div className="space-y-2">
            {summary.notable_quotes.map((q, i) => (
              <blockquote
                key={i}
                className="border-l-2 border-blue-500/60 pl-3 text-[12px] text-slate-200 leading-snug italic"
              >
                "{q.quote}"
                {q.speaker && (
                  <div className="not-italic text-[11px] text-slate-500 mt-0.5">
                    — {q.speaker}
                  </div>
                )}
              </blockquote>
            ))}
          </div>
        </section>
      )}

      {/* Tags */}
      {summary.geopolitics_tags?.length > 0 && (
        <section>
          <div className="flex flex-wrap gap-1">
            {summary.geopolitics_tags.map((t) => (
              <span
                key={t}
                className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#0f1117] text-slate-400 border border-[#2a2d3a]"
              >
                #{t}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
