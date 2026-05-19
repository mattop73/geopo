import { useEffect, useRef, useState } from 'react'
import { Cloud, Cpu, ChevronDown, Check } from 'lucide-react'
import { clsx } from 'clsx'
import { useLLMModel } from '../../hooks/useLLMModel'

/**
 * Compact LLM model picker for the global header.
 *
 * - Shows the current provider icon (cloud vs local) and a short label.
 * - Click opens a popover with Cloud and Local sections; clicking a model
 *   persists the choice (see useLLMModel) and closes the popover.
 * - A single inline "Toggle local/cloud" button flips between the first
 *   available model of the other provider type — fulfils the "button to
 *   change" requirement from the spec.
 */
export default function LLMModelPicker({ compact = true }: { compact?: boolean }) {
  const { model, setModel, current, isLocal, buckets, models } = useLLMModel()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const flipProvider = () => {
    if (isLocal) {
      const cloud = buckets.cloud[0]
      if (cloud) setModel(cloud.id)
    } else {
      const local = buckets.local[0]
      if (local) setModel(local.id)
    }
  }

  const ProviderIcon = isLocal ? Cpu : Cloud
  const label = current?.label ?? (model || 'no model')
  const tagColor = isLocal ? 'text-amber-300' : 'text-blue-300'

  return (
    <div ref={ref} className="relative inline-flex items-center gap-1">
      <button
        onClick={flipProvider}
        title={`Switch to ${isLocal ? 'Cloud (Anthropic / OpenAI)' : 'Local (Ollama)'}`}
        className={clsx(
          'flex items-center gap-1.5 px-2 py-1 rounded text-xs border transition-colors',
          isLocal
            ? 'border-amber-800/40 bg-amber-900/20 text-amber-200 hover:bg-amber-900/40'
            : 'border-blue-800/40 bg-blue-900/20 text-blue-200 hover:bg-blue-900/40',
        )}
      >
        <ProviderIcon className="w-3.5 h-3.5" />
        {isLocal ? 'Local' : 'Cloud'}
      </button>

      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-xs border border-[#2a2d3a] bg-[#0f1117] text-slate-300 hover:text-white hover:border-[#3b4058]"
      >
        <span className={clsx('font-mono truncate', tagColor)} style={{ maxWidth: compact ? 140 : 240 }}>
          {label}
        </span>
        <ChevronDown className="w-3 h-3 text-slate-500" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-72 rounded-lg border border-[#2a2d3a] bg-[#1a1d27] shadow-xl py-1">
          {models.length === 0 && (
            <div className="px-3 py-2 text-xs text-slate-500">
              No models available. Configure ANTHROPIC_API_KEY or run Ollama locally.
            </div>
          )}
          {buckets.cloud.length > 0 && (
            <Section title="Cloud" icon={<Cloud className="w-3.5 h-3.5" />}>
              {buckets.cloud.map((m) => (
                <Option
                  key={m.id}
                  label={m.label}
                  selected={m.id === model}
                  onClick={() => { setModel(m.id); setOpen(false) }}
                />
              ))}
            </Section>
          )}
          {buckets.local.length > 0 && (
            <Section title="Local (Ollama)" icon={<Cpu className="w-3.5 h-3.5" />}>
              {buckets.local.map((m) => (
                <Option
                  key={m.id}
                  label={m.label}
                  selected={m.id === model}
                  onClick={() => { setModel(m.id); setOpen(false) }}
                />
              ))}
            </Section>
          )}
        </div>
      )}
    </div>
  )
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 px-3 py-1.5 text-[10px] uppercase tracking-widest text-slate-500 border-b border-[#2a2d3a]">
        {icon}
        {title}
      </div>
      <div className="py-1">{children}</div>
    </div>
  )
}

function Option({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex items-center w-full px-3 py-1.5 text-xs gap-2 text-left hover:bg-[#23263a] transition-colors',
        selected ? 'text-white' : 'text-slate-300',
      )}
    >
      <span className="flex-1 truncate font-mono">{label}</span>
      {selected && <Check className="w-3.5 h-3.5 text-blue-400" />}
    </button>
  )
}
