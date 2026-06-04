import { useState, useEffect, useRef } from 'react'
import { Send, Loader2, Sparkles } from 'lucide-react'
import { apiFetch, apiStream } from '../../api/client'
import { useLLMModel } from '../../hooks/useLLMModel'
import LLMModelPicker from '../common/LLMModelPicker'
import { useLanguage } from '../../hooks/useLanguage'

const PRESET_PROMPTS = [
  {
    label: 'Summarize commodities',
    prompt: 'Summarize the most significant commodity price movements right now and what they suggest about geopolitical pressures. Focus on energy and agriculture.',
  },
  {
    label: 'News brief',
    prompt: 'Give me a 5-bullet brief of the most important geopolitical news today and how it could affect commodity markets.',
  },
  {
    label: 'Polymarket anomalies',
    prompt: 'List the Polymarket markets showing unusual betting behavior and speculate on what could be driving the moves.',
  },
  {
    label: 'Risk outlook',
    prompt: 'What are the top 3 geopolitical risks signaled by current prediction markets and commodity prices? Provide probabilities and reasoning.',
  },
]

interface Msg { role: 'user' | 'assistant'; content: string }

export default function LLMTab() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { model: selectedModel } = useLLMModel()
  const { language, languageName } = useLanguage()

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const enrichPromptWithContext = async (userPrompt: string) => {
    try {
      const [commodities, polymarket, news] = await Promise.all([
        apiFetch<any[]>('/commodities/'),
        apiFetch<any[]>(`/polymarket/?language=${language}`),
        apiFetch<any[]>(`/news/?limit=15&language=${language}`),
      ])
      const top = commodities.slice(0, 12).map((c: any) =>
        `${c.name} (${c.ticker}): $${c.price?.toFixed(2)} ${c.change_pct >= 0 ? '+' : ''}${c.change_pct?.toFixed(2)}%`,
      ).join('\n')
      const anomalies = polymarket.filter((m: any) => m.is_anomaly).slice(0, 8).map((m: any) =>
        `- ${m.question} — YES ${(m.yes_price * 100).toFixed(0)}% (${m.anomaly_reason})`,
      ).join('\n')
      const topMarkets = polymarket.slice(0, 8).map((m: any) =>
        `- ${m.question} — YES ${(m.yes_price * 100).toFixed(0)}% (vol $${(m.volume / 1000).toFixed(0)}k)`,
      ).join('\n')
      const headlines = news.slice(0, 10).map((n: any) =>
        `- [${n.source}] ${n.title}`,
      ).join('\n')

      return `## Live Context
Answer language: ${languageName}. Write the whole analysis in ${languageName}.

### Commodities (top movers)
${top || '(no data)'}

### Polymarket Anomalies
${anomalies || '(none detected)'}

### Top Polymarket Markets
${topMarkets || '(no data)'}

### Recent News Headlines
${headlines || '(no data)'}

## User question
${userPrompt}`
    } catch {
      return userPrompt
    }
  }

  const send = async (text: string) => {
    if (!text.trim() || streaming) return
    setInput('')
    const userMsg: Msg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg, { role: 'assistant', content: '' }])
    setStreaming(true)

    const fullPrompt = await enrichPromptWithContext(text)
    abortRef.current = new AbortController()
    try {
      await apiStream(
        '/llm/analyze',
        { prompt: fullPrompt, model: selectedModel, language },
        chunk => {
          setMessages(prev => {
            const copy = [...prev]
            copy[copy.length - 1] = { role: 'assistant', content: copy[copy.length - 1].content + chunk }
            return copy
          })
        },
        abortRef.current.signal,
      )
    } catch (e: any) {
      setMessages(prev => {
        const copy = [...prev]
        copy[copy.length - 1] = { role: 'assistant', content: copy[copy.length - 1].content + `\n[Error: ${e.message}]` }
        return copy
      })
    } finally {
      setStreaming(false)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-180px)] gap-4">
      {/* Header / controls */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <LLMModelPicker compact={false} />
        {messages.length > 0 && (
          <button
            onClick={() => setMessages([])}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            Clear chat
          </button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-auto space-y-4 pr-2">
        {messages.length === 0 && (
          <div className="text-center pt-12">
            <Sparkles className="w-10 h-10 text-slate-700 mx-auto mb-3" />
            <p className="text-slate-500 text-sm">Ask the LLM about commodity moves, news, or Polymarket bets.</p>
            <p className="text-slate-600 text-xs mt-1">Responses follow the selected language: {languageName}.</p>
            <p className="text-slate-600 text-xs mt-1">Live dashboard data is injected automatically.</p>
            <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
              {PRESET_PROMPTS.map(p => (
                <button
                  key={p.label}
                  onClick={() => send(p.prompt)}
                  className="text-left p-3 rounded-lg bg-[#1a1d27] border border-[#2a2d3a] hover:border-blue-500 transition-colors"
                >
                  <div className="text-sm font-medium text-slate-200">{p.label}</div>
                  <div className="text-xs text-slate-500 mt-1 line-clamp-2">{p.prompt}</div>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : ''}>
            <div className={`rounded-lg p-3 ${m.role === 'user' ? 'bg-blue-600 text-white max-w-xl' : 'bg-[#1a1d27] border border-[#2a2d3a] max-w-3xl'}`}>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{m.content || (streaming && i === messages.length - 1 ? '...' : '')}</pre>
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <form
        onSubmit={e => { e.preventDefault(); send(input) }}
        className="flex gap-2 items-end"
      >
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(input)
            }
          }}
          placeholder="Ask about market moves, news, or Polymarket bets… (Enter to send, Shift+Enter for newline)"
          rows={2}
          className="flex-1 bg-[#1a1d27] border border-[#2a2d3a] text-slate-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-blue-500 font-sans"
          disabled={streaming}
        />
        <button
          type="submit"
          disabled={streaming || !input.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg p-2.5 transition-colors"
        >
          {streaming ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
        </button>
      </form>
    </div>
  )
}
