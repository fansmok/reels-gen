import { app, safeStorage } from 'electron'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'
import { defaultContentDefaults, mergeContentDefaults } from '../shared/content-defaults'
import { PLATFORM_IDS } from '../shared/platforms'
import { defaultComposer, mergeComposer } from '../shared/publish-options'
import { emptyProxy, normalizeProxy } from '../shared/proxy'
import { importLegacyGeneratorSettings, mergeGeneratorSettings, type GeneratorSettings } from '../shared/generator'
import { platformsOfTargets } from '../shared/targets'
import type {
  AppSettings,
  ComposerDraft,
  ContentDefaults,
  EnginePaths,
  HistoryEntry,
  PlatformId,
  PlatformSettings,
  ProxyConfig,
  TargetId,
  VideoJob
} from '../shared/types'

export interface PersistedState {
  jobs: VideoJob[]
  history: HistoryEntry[]
  settings: AppSettings
  contentDefaults: ContentDefaults
  proxy: ProxyConfig
  platforms: Record<PlatformId, PlatformSettings>
  composer: ComposerDraft
  enginePaths: EnginePaths
  /** Галочки «грузить сюда» по направлениям (`youtube:3`, `rutube`, ...). */
  targets: Record<TargetId, boolean>
  /** Настройки мастера генератора. `null` — ещё не импортированы из reels_gen_settings.json. */
  generator: GeneratorSettings | null
}

const defaultSettings = (): AppSettings => ({
  delayBetweenPlatformsMs: 30_000,
  delayBetweenVideosMs: 60_000,
  headed: true,
  antidetectOnUpload: false,
  youtubeDistribute: false,
  youtubePerChannel: 1,
  kieApiKey: ''
})

/** Первый запуск: подтянуть настройки генератора из `reels_gen_settings.json` в корне движка. */
function importGeneratorSettings(enginePaths: EnginePaths): GeneratorSettings {
  const legacy = join(enginePaths.tgRoot, 'reels_gen_settings.json')
  try {
    if (existsSync(legacy)) {
      const raw = JSON.parse(readFileSync(legacy, 'utf-8')) as Record<string, unknown>
      return importLegacyGeneratorSettings(raw)
    }
  } catch {
    /* битый файл — стартуем с настроек по умолчанию */
  }
  return mergeGeneratorSettings(null)
}

/** Старые задания хранили результаты по площадкам — переводим на направления. */
function migrateJob(job: VideoJob): VideoJob {
  const targets = Array.isArray(job.targets) && job.targets.length > 0 ? job.targets : [...(job.enabledPlatforms ?? [])]
  const enabledPlatforms = platformsOfTargets(targets)
  return { ...job, targets, enabledPlatforms, results: job.results ?? {} }
}

/** Встроенный движок генерации (`reels-engine` с `reels_gen`). */
export function bundledEngineRoot(): string {
  return app.isPackaged ? join(process.resourcesPath, 'reels-engine') : join(app.getAppPath(), 'reels-engine')
}

function resolveDefaultTgRoot(): string {
  return bundledEngineRoot()
}

export const defaultEnginePaths = (): EnginePaths => {
  const tgRoot = resolveDefaultTgRoot()
  return {
    pythonExe: '',
    tgRoot,
    vkBot: join(tgRoot, 'profiles'),
    ydaRoot: '',
    ytCookies: join(tgRoot, 'YT-COOKIES')
  }
}

function mergeEnginePaths(raw?: Partial<EnginePaths>): EnginePaths {
  const defaults = defaultEnginePaths()
  const out = { ...defaults }
  for (const key of Object.keys(defaults) as (keyof EnginePaths)[]) {
    const value = String(raw?.[key] ?? '').trim()
    if (value) out[key] = value
  }
  return out
}

const defaultProxy = (): ProxyConfig => emptyProxy()

const defaultPlatforms = (): Record<PlatformId, PlatformSettings> => {
  const result = {} as Record<PlatformId, PlatformSettings>
  for (const id of PLATFORM_IDS) {
    result[id] = { useProxy: false, loggedIn: false }
  }
  return result
}

function filePath(): string {
  const dir = app.getPath('userData')
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
  return join(dir, 'state.json')
}

function encrypt(value: string): string {
  if (!value) return ''
  if (!safeStorage.isEncryptionAvailable()) return value
  return `enc:${safeStorage.encryptString(value).toString('base64')}`
}

function decrypt(value: string): string {
  if (!value) return ''
  if (!value.startsWith('enc:')) return value
  if (!safeStorage.isEncryptionAvailable()) return ''
  try {
    return safeStorage.decryptString(Buffer.from(value.slice(4), 'base64'))
  } catch {
    return ''
  }
}

function loadRaw(): PersistedState {
  const empty: PersistedState = {
    jobs: [],
    history: [],
    settings: defaultSettings(),
    contentDefaults: defaultContentDefaults(),
    proxy: defaultProxy(),
    platforms: defaultPlatforms(),
    composer: defaultComposer(),
    enginePaths: defaultEnginePaths(),
    targets: {},
    generator: null
  }
  try {
    if (!existsSync(filePath())) return empty
    const parsed = JSON.parse(readFileSync(filePath(), 'utf-8')) as Partial<PersistedState>
    const composer = mergeComposer(parsed.composer)
    const contentDefaults = mergeContentDefaults(parsed.contentDefaults)
    const legacyTiktok = composer.publishOptions.tiktok
    if (!contentDefaults.hashtags && legacyTiktok.hashtags) {
      contentDefaults.hashtags = legacyTiktok.hashtags
    }
    if (!contentDefaults.platforms.tiktok.description && legacyTiktok.description) {
      contentDefaults.platforms.tiktok.description = legacyTiktok.description
    }
    return {
      jobs: (parsed.jobs ?? []).map(migrateJob),
      history: parsed.history ?? [],
      settings: { ...defaultSettings(), ...parsed.settings },
      contentDefaults,
      proxy: normalizeProxy({
        ...defaultProxy(),
        ...parsed.proxy,
        password: decrypt(parsed.proxy?.password ?? '')
      }),
      platforms: { ...defaultPlatforms(), ...parsed.platforms },
      composer,
      enginePaths: mergeEnginePaths(parsed.enginePaths),
      targets: { ...(parsed.targets ?? {}) },
      generator: parsed.generator ? mergeGeneratorSettings(parsed.generator) : null
    }
  } catch {
    return empty
  }
}

let state: PersistedState | null = null

export function getPersisted(): PersistedState {
  if (!state) state = loadRaw()
  return state
}

/** Настройки генератора; при первом обращении могут импортироваться из legacy JSON движка. */
export function getGeneratorSettings(): GeneratorSettings {
  const current = getPersisted()
  if (current.generator) return current.generator
  const imported = importGeneratorSettings(current.enginePaths)
  patchPersisted({ generator: imported })
  return imported
}

export function savePersisted(): void {
  const current = getPersisted()
  const toWrite: PersistedState = {
    ...current,
    proxy: {
      ...current.proxy,
      password: encrypt(current.proxy.password)
    }
  }
  writeFileSync(filePath(), JSON.stringify(toWrite, null, 2), 'utf-8')
}

export function patchPersisted(patch: Partial<PersistedState>): PersistedState {
  state = { ...getPersisted(), ...patch }
  savePersisted()
  return state
}

export function sessionPath(platform: PlatformId): string {
  return join(app.getPath('userData'), 'sessions', platform)
}

export function sessionsDir(platform: PlatformId): string {
  const dir = sessionPath(platform)
  mkdirSync(dir, { recursive: true })
  return dir
}
