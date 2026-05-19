import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { apiFetch, apiPost } from '../../api/client'
import { timeAgo } from '../../lib/format'
import LatestNewsBox from './LatestNewsBox'

interface Article {
  id: number
  source: string
  title: string
  description: string | null
  url: string
  image_url: string | null
  published_at: string | null
  topic: string
  tags: string[]
}

interface Topic {
  id: string
  label: string
  icon: string
  color: string
}

export default function NewsTab() {
  const [activeSource, setActiveSource] = useState('All')
  const [activeTopic, setActiveTopic] = useState<string>('all')

  const { data: topics = [] } = useQuery<Topic[]>({
    queryKey: ['topics'],
    queryFn: () => apiFetch('/themes/topics'),
    staleTime: Infinity,
  })

  const { data: articles = [], isLoading, refetch } = useQuery<Article[]>({
    queryKey: ['news', activeSource, activeTopic],
    queryFn: () => {
      const params = new URLSearchParams({ limit: '120' })
      if (activeSource !== 'All') params.set('source', activeSource)
      if (activeTopic !== 'all') params.set('topic', activeTopic)
      return apiFetch(`/news/?${params.toString()}`)
    },
    refetchInterval: 15 * 60 * 1000,
  })

  const handleRefresh = async () => {
    await apiPost('/news/refresh', {})
    refetch()
  }

  const sources = Array.from(new Set(articles.map((a) => a.source)))

  // Counts per topic across the *full* current source filter (so chips reflect
  // what would happen when you click them).
  const topicCounts = articles.reduce<Record<string, number>>((acc, a) => {
    acc[a.topic] = (acc[a.topic] ?? 0) + 1
    return acc
  }, {})

  const topicById = new Map(topics.map((t) => [t.id, t]))

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4 items-start">
      {/* Main column — filters + grid */}
      <div className="space-y-4 min-w-0">
      {/* Topic chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-widest text-slate-500 mr-1">Topic</span>
        <TopicChip
          label="All topics"
          active={activeTopic === 'all'}
          onClick={() => setActiveTopic('all')}
          count={articles.length}
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

      {/* Source chips + refresh */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-widest text-slate-500 mr-1">Source</span>
          {['All', ...sources].map((src) => (
            <button
              key={src}
              onClick={() => setActiveSource(src)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                activeSource === src
                  ? 'bg-blue-600 text-white'
                  : 'bg-[#1a1d27] text-slate-400 hover:text-white border border-[#2a2d3a]'
              }`}
            >
              {src}
            </button>
          ))}
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
        <div className="text-slate-500 text-sm py-12 text-center">Loading news…</div>
      )}

      {!isLoading && articles.length === 0 && (
        <div className="text-slate-500 text-sm py-12 text-center">
          No articles for this filter. Try a different topic or click Refresh.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {articles.map((a) => (
          <ArticleCard key={a.id} article={a} topic={topicById.get(a.topic)} />
        ))}
      </div>
      </div>

      {/* Sidebar — sticky on xl+, stacks above grid on smaller screens
          (CSS order swap keeps it visible-first on mobile). */}
      <div className="xl:sticky xl:top-2 order-first xl:order-none">
        <LatestNewsBox />
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

function ArticleCard({ article: a, topic }: { article: Article; topic?: Topic }) {
  return (
    <a
      href={a.url}
      target="_blank"
      rel="noreferrer"
      className="block bg-[#1a1d27] border border-[#2a2d3a] rounded-lg p-3 hover:border-[#3b4058] transition-colors group"
    >
      {/* Meta row */}
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[11px] font-semibold text-blue-400 uppercase tracking-wide">
          {a.source}
        </span>
        <span className="text-xs text-slate-600">·</span>
        <span className="text-[11px] text-slate-500">{timeAgo(a.published_at)}</span>
        {topic && (
          <span
            className="ml-auto text-[10px] font-medium px-1.5 py-0.5 rounded"
            style={{ background: `${topic.color}22`, color: topic.color }}
            title="Topic"
          >
            {topic.icon} {topic.label}
          </span>
        )}
        {!topic && <ExternalLink className="w-3 h-3 text-slate-600 ml-auto opacity-0 group-hover:opacity-100" />}
      </div>

      {/* Title */}
      <h3 className="text-sm font-medium text-slate-100 leading-snug line-clamp-3 group-hover:text-white">
        {a.title}
      </h3>

      {/* Tags — content-derived keywords */}
      {a.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {a.tags.map((tag) => (
            <span
              key={tag}
              className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#0f1117] text-slate-400 border border-[#2a2d3a]"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}
    </a>
  )
}
