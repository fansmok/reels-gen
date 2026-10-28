/**
 * Настройки генератора рилсов — зеркало полей мастера из `reels_tab.py`.
 * Хранятся в state.json (`generator`), один раз импортируются из `reels_gen_settings.json`.
 */
import type { KiePack } from './kie-pack'

export type TopMode = 'all' | 'random_one' | 'latest' | 'single' | 'link' | 'telegram'
export type SourceMode = 'folder' | 'instagram' | 'telegram'
export type BannerPlace = 'mid' | 'end' | 'both'
export type CoverSource = 'top' | 'bottom' | 'split'
export type CoverPosition = 'bottom' | 'center' | 'top'
export type CoverTextSource = 'titles' | 'templates'
export type AsrModel = 'tiny' | 'base' | 'small' | 'medium' | 'large'
export type CirclePlace = 'left' | 'center' | 'right' | 'random'

export type CaptionPreset = 'karaoke' | 'kinetic' | 'pill' | 'weight' | 'neon' | 'editorial'

export interface CaptionStyle {
  preset: CaptionPreset
  font: string
  fontSize: number
  color: string
  /** Цвет слова, которое произносится прямо сейчас. */
  activeColor: string
  outlineColor: string
  outline: number
  bold: boolean
  italic: boolean
  uppercase: boolean
}

export const CIRCLE_PLACES: { id: CirclePlace; title: string }[] = [
  { id: 'left', title: 'Слева' },
  { id: 'center', title: 'Центр' },
  { id: 'right', title: 'Справа' },
  { id: 'random', title: 'Случайно' }
]

export const CAPTION_PRESETS: { id: CaptionPreset; title: string; hint: string }[] = [
  { id: 'kinetic', title: 'Удар', hint: 'Слова влетают по одному' },
  { id: 'karaoke', title: 'Караоке', hint: 'Цвет идёт по строке' },
  { id: 'pill', title: 'Плашка', hint: 'Строка в скруглённой плашке' },
  { id: 'weight', title: 'Акцент', hint: 'Жирным только текущее слово' },
  { id: 'neon', title: 'Неон', hint: 'Слово загорается' },
  { id: 'editorial', title: 'Редакция', hint: 'Строка и подчёркивание' }
]

export const CAPTION_FONTS: { id: string; label: string }[] = [
  { id: 'Arial Black', label: 'Жирный' },
  { id: 'Impact', label: 'Плакат' },
  { id: 'Arial', label: 'Обычный' },
  { id: 'Georgia', label: 'С засечками' },
  { id: 'Comic Sans MS', label: 'Мягкий' },
  { id: 'Times New Roman', label: 'Классический' }
]

export function defaultCaptionStyle(): CaptionStyle {
  return {
    preset: 'kinetic',
    font: 'Arial Black',
    fontSize: 82,
    color: '#FFFFFF',
    activeColor: '#FFE14A',
    outlineColor: '#000000',
    outline: 8,
    bold: true,
    italic: false,
    uppercase: true
  }
}
export type AutoMode = 'interval' | 'daily' | 'days'

/** Токен бота-триггера по умолчанию пустой — каждый вписывает свой в настройках. */
export const DEFAULT_TG_BOT_TOKEN = ''

/** Доп. Telegram user id, которым разрешена заливка вместе с закреплённым чатом. */
export const TG_EXTRA_UPLOADERS: number[] = []

/** Бот принимает ролики, когда в «Источнике» выбран пункт «Загрузка через Telegram». */
export interface TelegramTrigger {
  enabled: boolean
  token: string
  /** 0 — личный чат ещё не закреплён. */
  chatId: number
  /** Следующий update_id для getUpdates. */
  offset: number
  /** Старые сообщения на момент первого включения уже пропущены. */
  primed: boolean
}

export interface GeneratorBanner {
  enabled: boolean
  text: string
  style: string
  duration: number
  audio: string
  place: BannerPlace
  source: string
  dropBottom: boolean
}

export interface GeneratorCover {
  enabled: boolean
  source: CoverSource
  position: CoverPosition
  textColor: string
  strokeColor: string
  strokeWidth: number
  fontSize: number
  uppercase: boolean
  phrases: string
  textSource: CoverTextSource
}

export interface GeneratorAutomation {
  enabled: boolean
  mode: AutoMode
  intervalH: number
  time: string
  days: number
  daysTime: string
  onlyNew: boolean
  lastRun: string
  lastTopSig: string
}

export interface GeneratorSettings {
  step: number
  // шаг 1 — источник
  topMode: TopMode
  topFile: string
  topUrl: string
  titleTheme: string
  count: number
  sourceMode: SourceMode
  instagram: string
  linkedPath: string
  linkedKey: string
  /** 0 — звук только верхнего ролика, 100 — только нижнего. */
  audioMix: number
  /** Нижнее видео кружком внизу кадра, верх на весь экран. */
  bottomCircle: boolean
  /** Жирные субтитры по 1–2 слова из речи. */
  captions: boolean
  /** Где стоит кружок: слева, по центру, справа или случайно на каждый ролик. */
  circlePlace: CirclePlace
  captionStyle: CaptionStyle
  // шаг 2 — CTA
  slogans: string
  randSlogan: boolean
  tgCalls: string
  randTg: boolean
  ctaStyle: string
  randStyle: boolean
  ctaSec: number
  /** Экран призыва в конце. Выключен — ролик заканчивается без CTA. */
  ctaEnabled: boolean
  stickerEnabled: boolean
  stickerUrl: string
  stickerSelection: string
  qr: string
  qrFile: string
  // шаг 3 — баннер и обложка
  banner: GeneratorBanner
  cover: GeneratorCover
  // шаг 4 — текст
  titleBase: string
  transcript: string
  /** Какой файл распознан в transcript. Пусто — текст от другого ролика и в Kie не идёт. */
  transcriptVideo: string
  phrases: string[]
  phrasesChecked: string[]
  descManual: string
  hashtags: string
  permanentHashtags: string
  triggers: string[]
  useCustomMeta: boolean
  customTitles: string[]
  customDescriptions: string[]
  useKieTitles: boolean
  kieTitles: string[]
  kieTitlesChecked: string[]
  /** Перед отправкой в очередь — тексты под каждую площадку от Kie. */
  kiePack: boolean
  autoWhisper: boolean
  asrModel: AsrModel
  /** Бот для загрузки верхнего и нижнего ролика. Слушает, пока выбран пункт «Загрузка через Telegram». */
  tg: TelegramTrigger
  // шаг 5 — автоматизация
  auto: GeneratorAutomation
}

export interface GeneratedItem {
  video: string
  cover: string
  title: string
  description: string
  hashtags: string
  source: string
  uid: string
  coverFrom?: string
  /** Тексты под каждую площадку от Kie (или собранные локально при сбое). */
  pack?: KiePack
  packSource?: 'kie' | 'local'
}

export interface GeneratorFileInfo {
  name: string
  path: string
  size: number
  mtime: number
}

export interface GeneratorStyle {
  id: string
  title: string
}

export interface GeneratorInfo {
  folder1: string
  folder2: string
  output: string
  uploadQueue: string
  tops: GeneratorFileInfo[]
  bottoms: GeneratorFileInfo[]
  outputs: GeneratorFileInfo[]
  ctaStyles: GeneratorStyle[]
  bannerStyles: GeneratorStyle[]
  defaultSlogans: string[]
  defaultTgCalls: string[]
  defaultCoverPhrases: string[]
  defaultTriggers: string[]
  ffmpeg: boolean
}

export interface StickerPackInfo {
  name: string
  title: string
  count: number
  stickers: { index: number; emoji: string; label: string; thumb: string }[]
}

export interface GenerateResult {
  ok: number
  total: number
  items: GeneratedItem[]
  files: string[]
  titleBase?: string
  phrases?: string[]
  kieTitles?: string[]
  hashtags?: string
  description?: string
  linkedPath?: string
  linkedKey?: string
  transcript?: string
  transcriptVideo?: string
}

export interface LinkTopResult {
  path: string
  url: string
  title: string
  description: string
  titles: string[]
  tags: string
  mode: string
  theme: string
  key: string
}

export interface GeneratorRun {
  running: boolean
  /** Что сейчас крутится: генерация, распознавание, Kie, превью… */
  task: string
  progress: number
  log: string[]
  startedAt?: string
  finishedAt?: string
  result?: GeneratedItem[]
  error?: string
}

export const DEFAULT_STICKER_PACK = 'https://t.me/addstickers/Buddy_Bear'
export const DEFAULT_TITLE_THEME = 'футбол топ момент'

/** Бот слушает, только если верхний или нижний ролик берётся из Telegram. */
export function telegramArmed(settings: Pick<GeneratorSettings, 'topMode' | 'sourceMode'>): boolean {
  return settings.topMode === 'telegram' || settings.sourceMode === 'telegram'
}

export const ASR_MODELS: { id: AsrModel; label: string }[] = [
  { id: 'tiny', label: 'tiny — очень быстро, грубо' },
  { id: 'base', label: 'base — быстро' },
  { id: 'small', label: 'small — баланс' },
  { id: 'medium', label: 'medium — точнее, медленнее' },
  { id: 'large', label: 'large — максимум точности' }
]

export function defaultGeneratorSettings(): GeneratorSettings {
  return {
    step: 0,
    topMode: 'latest',
    topFile: '',
    topUrl: '',
    titleTheme: DEFAULT_TITLE_THEME,
    count: 1,
    sourceMode: 'folder',
    instagram: '',
    linkedPath: '',
    linkedKey: '',
    audioMix: 100,
    bottomCircle: true,
    captions: true,
    circlePlace: 'center',
    captionStyle: defaultCaptionStyle(),
    slogans: '',
    randSlogan: true,
    tgCalls: '',
    randTg: true,
    ctaStyle: 'random',
    randStyle: true,
    ctaSec: 5,
    ctaEnabled: true,
    stickerEnabled: false,
    stickerUrl: DEFAULT_STICKER_PACK,
    stickerSelection: 'random',
    qr: '',
    qrFile: '',
    banner: {
      enabled: false,
      text: 'ПОДПИШИСЬ',
      style: 'random',
      duration: 4,
      audio: '',
      place: 'mid',
      source: '',
      dropBottom: false
    },
    cover: {
      enabled: true,
      source: 'bottom',
      position: 'bottom',
      textColor: '#FFFFFF',
      strokeColor: '#000000',
      strokeWidth: 8,
      fontSize: 0,
      uppercase: true,
      phrases: '',
      textSource: 'titles'
    },
    titleBase: '',
    transcript: '',
    transcriptVideo: '',
    phrases: [],
    phrasesChecked: [],
    descManual: '',
    hashtags: '',
    permanentHashtags: '',
    triggers: [],
    useCustomMeta: false,
    customTitles: [],
    customDescriptions: [],
    useKieTitles: true,
    kieTitles: [],
    kieTitlesChecked: [],
    kiePack: true,
    autoWhisper: true,
    asrModel: 'small',
    tg: {
      enabled: true,
      token: DEFAULT_TG_BOT_TOKEN,
      chatId: 0,
      offset: 0,
      primed: false
    },
    auto: {
      enabled: false,
      mode: 'daily',
      intervalH: 6,
      time: '10:00',
      days: 1,
      daysTime: '10:00',
      onlyNew: true,
      lastRun: '',
      lastTopSig: ''
    }
  }
}

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : value == null ? fallback : String(value)
}

function num(value: unknown, fallback: number): number {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : fallback
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function strList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((v) => str(v).trim()).filter(Boolean) : []
}

function hexColor(value: unknown, fallback: string): string {
  const raw = str(value).trim()
  return /^#[0-9A-Fa-f]{6}$/.test(raw) ? raw.toUpperCase() : fallback
}

function captionStyleOf(value: unknown): CaptionStyle {
  const d = defaultCaptionStyle()
  const raw = (value && typeof value === 'object' ? value : {}) as Record<string, unknown>
  const font = str(raw.font)
  return {
    preset: oneOf(raw.preset, ['karaoke', 'kinetic', 'pill', 'weight', 'neon', 'editorial'] as const, d.preset),
    font: CAPTION_FONTS.some((item) => item.id === font) ? font : d.font,
    fontSize: Math.min(160, Math.max(36, Math.round(num(raw.fontSize, d.fontSize)))),
    color: hexColor(raw.color, d.color),
    activeColor: hexColor(raw.activeColor, d.activeColor),
    outlineColor: hexColor(raw.outlineColor, d.outlineColor),
    outline: Math.min(20, Math.max(0, Math.round(num(raw.outline, d.outline)))),
    bold: bool(raw.bold, d.bold),
    italic: bool(raw.italic, d.italic),
    uppercase: bool(raw.uppercase, d.uppercase)
  }
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

export function mergeGeneratorSettings(raw?: Partial<GeneratorSettings> | null): GeneratorSettings {
  const d = defaultGeneratorSettings()
  if (!raw || typeof raw !== 'object') return d
  const r = raw as Record<string, unknown>
  const banner = (r.banner ?? {}) as Record<string, unknown>
  const cover = (r.cover ?? {}) as Record<string, unknown>
  const auto = (r.auto ?? {}) as Record<string, unknown>
  const tg = (r.tg ?? {}) as Record<string, unknown>
  return {
    step: Math.min(4, Math.max(0, Math.floor(num(r.step, d.step)))),
    topMode: oneOf(r.topMode, ['all', 'random_one', 'latest', 'single', 'link', 'telegram'] as const, d.topMode),
    topFile: str(r.topFile),
    topUrl: str(r.topUrl),
    titleTheme: str(r.titleTheme, d.titleTheme) || d.titleTheme,
    count: Math.max(1, Math.floor(num(r.count, d.count))),
    sourceMode: oneOf(r.sourceMode, ['folder', 'instagram', 'telegram'] as const, d.sourceMode),
    instagram: str(r.instagram),
    linkedPath: str(r.linkedPath),
    linkedKey: str(r.linkedKey),
    audioMix: Math.min(100, Math.max(0, Math.round(num(r.audioMix, d.audioMix)))),
    bottomCircle: bool(r.bottomCircle, d.bottomCircle),
    captions: bool(r.captions, d.captions),
    circlePlace: oneOf(r.circlePlace, ['left', 'center', 'right', 'random'] as const, d.circlePlace),
    captionStyle: captionStyleOf(r.captionStyle),
    slogans: str(r.slogans),
    randSlogan: bool(r.randSlogan, d.randSlogan),
    tgCalls: str(r.tgCalls),
    randTg: bool(r.randTg, d.randTg),
    ctaStyle: str(r.ctaStyle, d.ctaStyle) || 'random',
    randStyle: bool(r.randStyle, d.randStyle),
    ctaSec: Math.min(15, Math.max(1, num(r.ctaSec, d.ctaSec))),
    ctaEnabled: bool(r.ctaEnabled, d.ctaEnabled),
    stickerEnabled: bool(r.stickerEnabled, d.stickerEnabled),
    stickerUrl: str(r.stickerUrl, d.stickerUrl) || d.stickerUrl,
    stickerSelection: str(r.stickerSelection, 'random') || 'random',
    qr: str(r.qr),
    qrFile: str(r.qrFile),
    banner: {
      enabled: bool(banner.enabled, d.banner.enabled),
      text: str(banner.text, d.banner.text) || d.banner.text,
      style: str(banner.style, d.banner.style) || 'random',
      duration: Math.min(20, Math.max(1, num(banner.duration, d.banner.duration))),
      audio: str(banner.audio),
      place: oneOf(banner.place, ['mid', 'end', 'both'] as const, d.banner.place),
      source: str(banner.source),
      dropBottom: bool(banner.dropBottom, d.banner.dropBottom)
    },
    cover: {
      enabled: bool(cover.enabled, d.cover.enabled),
      source: oneOf(cover.source, ['top', 'bottom', 'split'] as const, d.cover.source),
      position: oneOf(cover.position, ['bottom', 'center', 'top'] as const, d.cover.position),
      textColor: str(cover.textColor, d.cover.textColor) || d.cover.textColor,
      strokeColor: str(cover.strokeColor, d.cover.strokeColor) || d.cover.strokeColor,
      strokeWidth: Math.max(0, Math.floor(num(cover.strokeWidth, d.cover.strokeWidth))),
      fontSize: Math.max(0, Math.floor(num(cover.fontSize, d.cover.fontSize))),
      uppercase: bool(cover.uppercase, d.cover.uppercase),
      phrases: str(cover.phrases),
      textSource: oneOf(cover.textSource, ['titles', 'templates'] as const, d.cover.textSource)
    },
    titleBase: str(r.titleBase),
    transcript: str(r.transcript),
    transcriptVideo: str(r.transcriptVideo),
    phrases: strList(r.phrases),
    phrasesChecked: strList(r.phrasesChecked),
    descManual: str(r.descManual),
    hashtags: str(r.hashtags),
    permanentHashtags: str(r.permanentHashtags),
    triggers: strList(r.triggers),
    useCustomMeta: bool(r.useCustomMeta, d.useCustomMeta),
    customTitles: strList(r.customTitles),
    customDescriptions: strList(r.customDescriptions),
    useKieTitles: bool(r.useKieTitles, d.useKieTitles),
    kieTitles: strList(r.kieTitles),
    kieTitlesChecked: strList(r.kieTitlesChecked),
    kiePack: bool(r.kiePack, d.kiePack),
    autoWhisper: bool(r.autoWhisper, d.autoWhisper),
    asrModel: oneOf(r.asrModel, ['tiny', 'base', 'small', 'medium', 'large'] as const, d.asrModel),
    tg: {
      enabled: bool(tg.enabled, d.tg.enabled),
      token: typeof tg.token === 'string' ? tg.token.trim() : d.tg.token,
      chatId: Math.trunc(num(tg.chatId, 0)),
      offset: Math.max(0, Math.trunc(num(tg.offset, 0))),
      primed: bool(tg.primed, false)
    },
    auto: {
      enabled: bool(auto.enabled, d.auto.enabled),
      mode: oneOf(auto.mode, ['interval', 'daily', 'days'] as const, d.auto.mode),
      intervalH: Math.max(1, Math.floor(num(auto.intervalH, d.auto.intervalH))),
      time: str(auto.time, d.auto.time) || d.auto.time,
      days: Math.max(1, Math.floor(num(auto.days, d.auto.days))),
      daysTime: str(auto.daysTime, d.auto.daysTime) || d.auto.daysTime,
      onlyNew: bool(auto.onlyNew, d.auto.onlyNew),
      lastRun: str(auto.lastRun),
      lastTopSig: str(auto.lastTopSig)
    }
  }
}

/** Разовый импорт `reels_gen_settings.json` генератора (ключи snake_case из reels_tab.py). */
export function importLegacyGeneratorSettings(raw: Record<string, unknown>): GeneratorSettings {
  const banner = (raw.banner ?? {}) as Record<string, unknown>
  const cover = (raw.cover ?? {}) as Record<string, unknown>
  const triggers = Array.isArray(raw.triggers) ? raw.triggers : typeof raw.triggers === 'string' ? raw.triggers.split('\n') : []
  return mergeGeneratorSettings({
    step: num(raw.step, 0),
    topMode: raw.top_mode as TopMode,
    topFile: str(raw.top_file),
    topUrl: str(raw.top_url),
    titleTheme: str(raw.title_theme),
    count: num(raw.count, 1),
    sourceMode: raw.source as SourceMode,
    instagram: Array.isArray(raw.ig_accounts) ? strList(raw.ig_accounts).join('\n') : str(raw.ig),
    slogans: str(raw.slogans),
    randSlogan: bool(raw.rand_slogan, true),
    tgCalls: str(raw.tg_calls),
    randTg: bool(raw.rand_tg, true),
    ctaStyle: str(raw.style, 'random'),
    randStyle: bool(raw.rand_style, true),
    ctaSec: num(raw.cta_sec, 5),
    stickerEnabled: bool(raw.sticker_enabled, false),
    stickerUrl: str(raw.sticker_pack_url),
    stickerSelection: str(raw.sticker_selection, 'random'),
    qr: str(raw.qr),
    qrFile: str(raw.qr_file),
    banner: {
      enabled: bool(banner.enabled, false),
      text: str(banner.text),
      style: str(banner.style, 'random'),
      duration: num(banner.duration, 4),
      audio: str(banner.audio),
      place: banner.place as BannerPlace,
      source: str(banner.source),
      dropBottom: bool(banner.drop_bottom, false)
    },
    cover: {
      enabled: bool(cover.enabled, true),
      source: cover.source as CoverSource,
      position: cover.position as CoverPosition,
      textColor: str(cover.text_color),
      strokeColor: str(cover.stroke_color),
      strokeWidth: num(cover.stroke_width, 8),
      fontSize: num(cover.font_size, 0),
      uppercase: bool(cover.uppercase, true),
      phrases: str(cover.phrases),
      textSource: cover.text_source as CoverTextSource
    },
    titleBase: str(raw.title_base),
    transcript: str(raw.transcript),
    phrases: strList(raw.phrases),
    phrasesChecked: strList(raw.phrases_checked),
    descManual: str(raw.desc_manual),
    hashtags: str(raw.hashtags),
    permanentHashtags: str(raw.permanent_hashtags),
    triggers: strList(triggers),
    useCustomMeta: bool(raw.use_custom_meta, false),
    customTitles: strList(raw.custom_titles),
    customDescriptions: strList(raw.custom_descriptions),
    useKieTitles: bool(raw.use_kie_titles, true),
    kieTitles: strList(raw.kie_titles),
    kieTitlesChecked: strList(raw.kie_titles_checked),
    autoWhisper: bool(raw.auto_whisper, true),
    asrModel: raw.asr_model as AsrModel,
    auto: {
      enabled: bool(raw.auto_enabled, false),
      mode: raw.auto_mode as AutoMode,
      intervalH: num(raw.auto_interval_h, 6),
      time: str(raw.auto_time),
      days: num(raw.auto_days, 1),
      daysTime: str(raw.auto_days_time),
      onlyNew: bool(raw.auto_only_new, true),
      lastRun: str(raw.auto_last_run),
      lastTopSig: str(raw.auto_last_top_sig)
    }
  })
}

export const STEP_TITLES = ['Источник', 'Призыв (CTA)', 'Баннер и обложка', 'Текст', 'Запуск'] as const
