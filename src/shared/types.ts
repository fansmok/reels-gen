import type { GeneratorRun, GeneratorSettings } from './generator'
import type { PublishOptionsByPlatform } from './publish-options'

export type PlatformId =
  | 'youtube'
  | 'rutube'
  | 'pinterest'
  | 'dzen'
  | 'tiktok'
  | 'vk'
  | 'instagram'

export type JobStatus = 'queued' | 'waiting' | 'uploading' | 'done' | 'error' | 'partial' | 'paused'
export type PlatformJobStatus = 'pending' | 'uploading' | 'done' | 'error' | 'skipped'
export type QueueRunnerStatus = 'idle' | 'running' | 'paused' | 'waiting'

export interface PlatformOverride {
  title?: string
  description?: string
  hashtags?: string
  coverPath?: string
}

export interface PlatformResult {
  status: PlatformJobStatus
  error?: string
  url?: string
}

export interface VideoJob {
  id: string
  videoPath: string
  title: string
  description: string
  hashtags?: string
  coverPath?: string
  /** Площадки — вычисляются из `targets`, нужны старым экранам и адаптерам. */
  enabledPlatforms: PlatformId[]
  /** Направления заливки: `youtube:3`, `rutube`, … Результаты хранятся по ним. */
  targets: TargetId[]
  overrides: Partial<Record<PlatformId, PlatformOverride>>
  publishOptions?: Partial<PublishOptionsByPlatform>
  publishAt?: string
  status: JobStatus
  results: Partial<Record<TargetId, PlatformResult>>
  createdAt: string
  error?: string
}

export interface NewVideoPayload {
  videoPath: string
  title: string
  description: string
  hashtags?: string
  coverPath?: string
  enabledPlatforms: PlatformId[]
  /** Если не задано — направления берутся из `enabledPlatforms` (по одной сессии на площадку). */
  targets?: TargetId[]
  overrides: Partial<Record<PlatformId, PlatformOverride>>
  publishOptions?: Partial<PublishOptionsByPlatform>
  publishAt?: string
}

export interface ProxyConfig {
  enabled: boolean
  type: 'http' | 'socks5'
  host: string
  port: string
  username: string
  password: string
}

export interface PlatformSettings {
  useProxy: boolean
  loggedIn: boolean
}

export interface AppSettings {
  delayBetweenPlatformsMs: number
  delayBetweenVideosMs: number
  headed: boolean
  /** Открывать YouTube-профиль при заливке полным антидетектом (CFT + отпечаток). По умолчанию выкл — как в генераторе. */
  antidetectOnUpload: boolean
  /** Пачка роликов на YouTube: раздать по каналам без повторов (true) или каждый ролик во все отмеченные каналы (false). */
  youtubeDistribute: boolean
  /** Не больше N роликов на один канал за пачку в режиме «без повторов». */
  youtubePerChannel: number
  /** Ключ Kie AI для заголовков/описаний. Пусто — ключ по умолчанию из генератора. */
  kieApiKey: string
}

/** Пути к Python-движку генератора. Сам движок остаётся на диске, программа его только вызывает. */
export interface EnginePaths {
  pythonExe: string
  tgRoot: string
  vkBot: string
  ydaRoot: string
  ytCookies: string
}

export interface EngineCheck {
  ok: boolean
  python?: string
  ffmpeg?: boolean
  chrome?: string
  vkBot?: string
  problems: string[]
}

/** Профиль площадки: свой Chrome, отпечаток и прокси. YouTube — profiles_youtube_plain_N. */
export interface YoutubeProfileInfo {
  platform?: PlatformId
  number: number
  name: string
  path: string
  bound: string[]
  dateAdded: string
  proxyLabel: string
  proxyIp: string
  locked: boolean
}

/** Направление заливки: площадка + конкретный канал. `youtube:3`, `rutube`, `vk`. */
export type TargetId = string

export interface Target {
  id: TargetId
  platform: PlatformId
  channelNumber?: number
  label: string
  enabled: boolean
}

export interface PlatformCopy {
  title: string
  description: string
  hashtags?: string
}

export interface ContentDefaults {
  title: string
  description: string
  hashtags: string
  platforms: Record<PlatformId, PlatformCopy>
}

export interface HistoryEntry {
  id: string
  jobId: string
  jobTitle: string
  platform: PlatformId
  target?: TargetId
  status: 'done' | 'error'
  message: string
  url?: string
  at: string
}

export interface AccountStatus {
  platform: PlatformId
  loggedIn: boolean
  checking: boolean
  browserOpen: boolean
}

export interface ProgressEvent {
  jobId?: string
  platform?: PlatformId
  target?: TargetId
  message: string
  level: 'info' | 'success' | 'error' | 'warn'
}

export interface ComposerDraft {
  videoPath: string
  coverPath: string
  title: string
  description: string
  hashtags: string
  enabledPlatforms: PlatformId[]
  /** Выбранные направления на экране «Новый ролик». Пусто — брать галочки из «Аккаунтов». */
  targets?: TargetId[]
  overrides: Partial<Record<PlatformId, PlatformOverride>>
  publishOptions: PublishOptionsByPlatform
  scheduleOn: boolean
  publishAt: string
}

export interface AutomationStatus {
  enabled: boolean
  cycleRunning: boolean
  nextRun?: string
  lastRun?: string
  lastMessage?: string
  lastError?: string
  lastResult?: string
}

export interface TelegramStatus {
  enabled: boolean
  listening: boolean
  username: string
  chatId: number
  queued: number
  lastError: string
  lastText: string
  lastUrl: string
}

export interface AppState {
  jobs: VideoJob[]
  history: HistoryEntry[]
  settings: AppSettings
  contentDefaults: ContentDefaults
  proxy: ProxyConfig
  platforms: Record<PlatformId, PlatformSettings>
  accounts: Record<PlatformId, AccountStatus>
  runner: QueueRunnerStatus
  chromeAvailable: boolean
  chromeMessage?: string
  composer: ComposerDraft
  enginePaths: EnginePaths
  engine: EngineCheck
  youtubeProfiles: YoutubeProfileInfo[]
  /** Профили всех площадок, включая YouTube. Пустой список — аккаунтов этой площадки ещё нет. */
  platformProfiles: Record<PlatformId, YoutubeProfileInfo[]>
  youtubeProfilesLoading: boolean
  openYoutubeProfiles: number[]
  /** Открытые профили: `instagram:2`, `youtube:1`. */
  openAccountProfiles: string[]
  targets: Record<TargetId, boolean>
  generator: GeneratorSettings
  generatorRun: GeneratorRun
  automation: AutomationStatus
  telegram: TelegramStatus
}
