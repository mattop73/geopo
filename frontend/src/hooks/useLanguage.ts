import { useEffect, useState } from 'react'

export type LanguageCode = 'en' | 'fr'

export const LANGUAGES: Record<LanguageCode, { label: string; llmName: string }> = {
  en: { label: 'English', llmName: 'English' },
  fr: { label: 'Français', llmName: 'French' },
}

const STORAGE_KEY = 'geopo-language'
const EVENT_NAME = 'geopo-language-change'

function normalizeLanguage(value: string | null): LanguageCode {
  return value === 'fr' ? 'fr' : 'en'
}

export function getCurrentLanguage(): LanguageCode {
  return normalizeLanguage(localStorage.getItem(STORAGE_KEY))
}

export function useLanguage() {
  const [language, setLanguageState] = useState<LanguageCode>(() => getCurrentLanguage())

  useEffect(() => {
    const sync = () => setLanguageState(getCurrentLanguage())
    window.addEventListener(EVENT_NAME, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(EVENT_NAME, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  const setLanguage = (next: LanguageCode) => {
    localStorage.setItem(STORAGE_KEY, next)
    setLanguageState(next)
    window.dispatchEvent(new Event(EVENT_NAME))
  }

  return {
    language,
    languageName: LANGUAGES[language].llmName,
    setLanguage,
  }
}
