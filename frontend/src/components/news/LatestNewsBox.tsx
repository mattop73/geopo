import { useQuery } from '@tanstack/react-query'
import { Clock } from 'lucide-react'
import { apiFetch } from '../../api/client'
import { timeAgo } from '../../lib/format'

interface Article {
  id: number
  source: string
  title: string
  url: string
  published_at: string | null
  topic: string
}

interface Topic {
  id: string
  label: string
  icon: string
  color: string
}

/**
 * Compact "latest news" panel.
 *
 * Important behaviour: this widget runs an **unfiltered** query (no source /
 * topic / search applied). The main grid below can be filtered down to a
 * single source or topic, but the user always wants to see the absolute most
 * recent items in this box — that's its job as a "what just broke" view.
 */
export default function LatestNewsBox({
  limit = 8,
  className = '',
}: {
  limit?: number
  className?: string
}) {
  const { data: items = [], isLoading } = useQuery<Article[]>({
    queryKey: ['news-latest', limit],
    queryFn: () => apiFetch(`/news/?limit=${limit}`),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  const { data: topics = [] } = useQuery<Topic[]>({
    queryKey: ['topics'],
    queryFn: () => apiFetch('/themes/topics'),
    staleTime: Infinity,
  })
  const topicById = new Map(topics.map((t) => [t.id, t]))

  return (
    <aside
      className={`bg-[#1a1d27] border border-[#2a2d3a] rounded-lg overflow-hidden ${className}`}
    >
      <header className="px-3 py-2 border-b border-[#2a2d3a] flex items-center gap-2 bg-[#0f1117]/60">
        <Clock className="w-3.5 h-3.5 text-blue-400" />
        <span className="text-xs font-semibold text-slate-200 uppercase tracking-wide">
          Latest
        </span>
        <span className="ml-auto text-[10px] text-slate-500 font-mono">
          auto · 60s
        </span>
      </header>

      <ul className="divide-y divide-[#2a2d3a]">
        {isLoading && (
          <li className="px-3 py-6 text-xs text-slate-500 text-center">Loading…</li>
        )}
        {!isLoading && items.length === 0 && (
          <li className="px-3 py-6 text-xs text-slate-500 text-center">
            No articles yet.
          </li>
        )}
        {items.map((a) => {
          const topic = topicById.get(a.topic)
          return (
            <li key={a.id}>
              <a
                href={a.url}
                target="_blank"
                rel="noreferrer"
                className="block px-3 py-2 group hover:bg-[#0f1117]/60 transition-colors"
              >
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-[10px] font-mono text-slate-500 shrink-0">
                    {timeAgo(a.published_at)}
                  </span>
                  <span className="text-[10px] font-semibold text-blue-400 uppercase tracking-wide truncate">
                    {a.source}
                  </span>
                  {topic && (
                    <span
                      className="ml-auto shrink-0 text-[9px] font-medium px-1 rounded"
                      style={{ background: `${topic.color}22`, color: topic.color }}
                      title={topic.label}
                    >
                      {topic.icon}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-200 line-clamp-2 leading-snug group-hover:text-white">
                  {a.title}
                </p>
              </a>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
