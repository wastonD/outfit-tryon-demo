import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import en from './en'
import zh from './zh'

export type Lang = 'zh' | 'en'

const DICTS: Record<Lang, typeof zh> = { zh, en }
const STORAGE_KEY = 'outfit.lang'

type FlattenKeys<T, Prefix extends string = ''> = T extends string
  ? Prefix
  : { [K in keyof T & string]: FlattenKeys<T[K], `${Prefix}${Prefix extends '' ? '' : '.'}${K}`> }[keyof T & string]

export type TKey = FlattenKeys<typeof zh>

function detectLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch {
    // 忽略
  }
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

function get(dict: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), dict)
}

type I18nContextValue = {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: TKey) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(detectLang)

  const setLang = (next: Lang) => {
    setLangState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // 忽略
    }
  }

  const t = useMemo(() => {
    const dict = DICTS[lang]
    return (key: TKey): string => {
      const value = get(dict, key)
      return typeof value === 'string' ? value : key
    }
  }, [lang])

  const value = useMemo(() => ({ lang, setLang, t }), [lang, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useT(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useT must be used within I18nProvider')
  return ctx
}
