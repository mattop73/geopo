/**
 * Global LLM model preference, shared across LLM Chat & Themes tabs.
 *
 * - Persisted in localStorage under "geopo.llm.model".
 * - Falls back to the backend's `default_llm_model` (typically the local
 *   Ollama model) when nothing is stored yet.
 * - Exposes a `providerBuckets` helper so UI can render Cloud vs Local
 *   sections in the picker.
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../api/client'

export interface LLMModel {
  id: string
  label: string
  provider: 'anthropic' | 'openai' | 'ollama' | string
}

const STORAGE_KEY = 'geopo.llm.model'

function readStored(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStored(model: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, model)
  } catch {
    /* SSR / private mode — best effort */
  }
}

export function useLLMModel() {
  const { data: models = [] } = useQuery<LLMModel[]>({
    queryKey: ['llm-models'],
    queryFn: () => apiFetch('/llm/models'),
    staleTime: 5 * 60 * 1000,
  })

  const { data: defaultModel } = useQuery<{ model: string }>({
    queryKey: ['llm-default'],
    queryFn: () => apiFetch('/llm/default-model'),
    staleTime: 60 * 60 * 1000,
  })

  const [model, setModelState] = useState<string>(() => readStored() ?? '')

  // First boot: pick stored → default → first available.
  useEffect(() => {
    if (model) return
    const stored = readStored()
    const fallback = defaultModel?.model || models[0]?.id || ''
    const next = stored || fallback
    if (next) setModelState(next)
  }, [model, models, defaultModel])

  const setModel = (next: string) => {
    setModelState(next)
    writeStored(next)
  }

  const buckets = useMemo(() => {
    const cloud = models.filter((m) => m.provider === 'anthropic' || m.provider === 'openai')
    const local = models.filter((m) => m.provider === 'ollama')
    return { cloud, local }
  }, [models])

  const current = models.find((m) => m.id === model) ?? null
  const isLocal = current?.provider === 'ollama' || model.startsWith('ollama:')

  return { models, model, setModel, current, isLocal, buckets }
}
