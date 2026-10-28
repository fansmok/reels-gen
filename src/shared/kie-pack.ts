import type { PlatformId, PlatformOverride } from './types'

/** Лимиты текста по площадкам — те же, что в python/kie_bridge.py. 0 — поля нет. */
export interface PlatformTextLimits {
  title: number
  description: number
  hashtags: number
}

export const PLATFORM_TEXT_LIMITS: Record<PlatformId, PlatformTextLimits> = {
  youtube: { title: 100, description: 5000, hashtags: 5 },
  rutube: { title: 100, description: 5000, hashtags: 5 },
  pinterest: { title: 100, description: 500, hashtags: 3 },
  dzen: { title: 0, description: 1000, hashtags: 5 },
  tiktok: { title: 0, description: 4000, hashtags: 5 },
  vk: { title: 0, description: 500, hashtags: 5 },
  instagram: { title: 0, description: 2200, hashtags: 5 }
}

/** Пакет текстов под площадки для одного ролика: ключ — площадка. */
export type KiePack = Partial<Record<PlatformId, PlatformOverride>>

export interface KiePackResult {
  pack: KiePack
  source: 'kie' | 'local'
  note?: string
}
