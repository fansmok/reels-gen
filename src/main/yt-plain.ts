import type { ChildProcessWithoutNullStreams } from 'child_process'
import { setTimeout as sleep } from 'node:timers/promises'
import type { Browser, BrowserContext, Page } from 'playwright-core'
import { chromium } from 'playwright-core'
import { PLATFORM_IDS, getPlatform } from '../shared/platforms'
import type { PlatformId, YoutubeProfileInfo } from '../shared/types'
import { runBridge, spawnBridge } from './python'
import { getPersisted } from './store'
import { uploadLog } from './uploaders/upload-log'

export type YoutubeLaunchMode = 'login' | 'upload'

interface ReadyMessage {
  type: 'ready'
  acc: number
  mode: YoutubeLaunchMode
  port: number
  pid: number
  profile: string
  locale: string
  timezoneId: string
  userAgent: string
  viewport: { width: number; height: number } | null
  proxyLabel: string
  antidetect: boolean
}

interface OpenProfile {
  platform: PlatformId
  number: number
  mode: YoutubeLaunchMode
  child: ChildProcessWithoutNullStreams
  browser: Browser
  context: BrowserContext
  ready: ReadyMessage
  closing: Promise<void> | null
}

function accountKey(platform: PlatformId, number: number): string {
  return `${platform}:${number}`
}

function emptyProfiles(): Record<PlatformId, YoutubeProfileInfo[]> {
  const out = {} as Record<PlatformId, YoutubeProfileInfo[]>
  for (const id of PLATFORM_IDS) out[id] = []
  return out
}

const open = new Map<string, OpenProfile>()
let platformCache: Record<PlatformId, YoutubeProfileInfo[]> = emptyProfiles()
const listeners = new Set<() => void>()
let profilesCache: YoutubeProfileInfo[] = []
let profilesLoading = false
let profilesError: string | undefined

export function onYoutubeProfilesChange(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function emit(): void {
  listeners.forEach((fn) => fn())
}

export function getYoutubeProfiles(): YoutubeProfileInfo[] {
  return profilesCache
}

export function getPlatformProfiles(): Record<PlatformId, YoutubeProfileInfo[]> {
  return platformCache
}

export function allAccountProfiles(): YoutubeProfileInfo[] {
  return PLATFORM_IDS.flatMap((id) => platformCache[id] ?? [])
}

export function isYoutubeProfilesLoading(): boolean {
  return profilesLoading
}

export function getYoutubeProfilesError(): string | undefined {
  return profilesError
}

export async function refreshYoutubeProfiles(): Promise<YoutubeProfileInfo[]> {
  if (profilesLoading) return profilesCache
  profilesLoading = true
  profilesError = undefined
  emit()
  try {
    const list = await runBridge<Partial<Record<PlatformId, YoutubeProfileInfo[]>>>('yt_bridge.py', ['list-all'], {
      timeoutMs: 90_000
    })
    const next = emptyProfiles()
    for (const id of PLATFORM_IDS) {
      const rows = Array.isArray(list?.[id]) ? list[id] : []
      next[id] = rows.map((row) => ({ ...row, platform: row.platform ?? id }))
    }
    platformCache = next
    profilesCache = next.youtube
  } catch (error) {
    profilesError = error instanceof Error ? error.message : String(error)
    uploadLog('youtube', 'profiles', `список профилей: ${profilesError}`)
  } finally {
    profilesLoading = false
    emit()
  }
  return profilesCache
}

export function isYoutubeProfileOpen(number: number): boolean {
  return open.has(accountKey('youtube', number))
}

export function isAccountProfileOpen(platform: PlatformId, number: number): boolean {
  return open.has(accountKey(platform, number))
}

export function openYoutubeProfileNumbers(): number[] {
  return [...open.values()]
    .filter((item) => item.platform === 'youtube')
    .map((item) => item.number)
    .sort((a, b) => a - b)
}

export function openAccountKeys(): string[] {
  return [...open.keys()].sort()
}

export function getOpenYoutubeProfile(number: number): { context: BrowserContext; mode: YoutubeLaunchMode } | undefined {
  return getOpenAccountProfile('youtube', number)
}

export function getOpenAccountProfile(
  platform: PlatformId,
  number: number
): { context: BrowserContext; mode: YoutubeLaunchMode } | undefined {
  const item = open.get(accountKey(platform, number))
  return item ? { context: item.context, mode: item.mode } : undefined
}

async function applyEmulation(page: Page, ready: ReadyMessage): Promise<void> {
  if (!ready.antidetect) return
  try {
    const cdp = await page.context().newCDPSession(page)
    if (ready.timezoneId) await cdp.send('Emulation.setTimezoneOverride', { timezoneId: ready.timezoneId }).catch(() => undefined)
    if (ready.locale) await cdp.send('Emulation.setLocaleOverride', { locale: ready.locale }).catch(() => undefined)
    if (ready.userAgent) {
      await cdp
        .send('Network.setUserAgentOverride', {
          userAgent: ready.userAgent,
          acceptLanguage: ready.locale ? `${ready.locale},${ready.locale.split('-')[0]};q=0.9` : undefined
        })
        .catch(() => undefined)
    }
    await cdp.detach().catch(() => undefined)
  } catch {
    /* страница уже закрыта */
  }
}

function waitForReady(child: ChildProcessWithoutNullStreams, onMessage: (cb: (msg: ReadyMessage) => void) => void, timeoutMs: number): Promise<ReadyMessage> {
  return new Promise<ReadyMessage>((resolve, reject) => {
    let settled = false
    const errors: string[] = []
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      child.kill()
      reject(new Error('Chrome профиля не открылся за отведённое время'))
    }, timeoutMs)
    onMessage((msg) => {
      if (settled) return
      if (msg.type === 'ready') {
        settled = true
        clearTimeout(timer)
        resolve(msg)
      } else if ((msg as { type: string }).type === 'error') {
        errors.push(String((msg as unknown as { message: string }).message))
      }
    })
    child.on('close', (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(new Error(errors[errors.length - 1] || `Python-мост завершился с кодом ${code}`))
    })
    child.on('error', (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(error)
    })
  })
}

/**
 * Открывает Chrome профиля площадки через Python-мост и подключается по CDP.
 * `login` — полный антидетект (CFT, отпечаток, гео); `upload` — обычный Chrome + прокси профиля.
 * Для площадок кроме YouTube заливка тоже идёт в режиме `login`, чтобы отпечаток не менялся.
 */
export async function openAccountProfile(
  platform: PlatformId,
  number: number,
  mode: YoutubeLaunchMode,
  options: { url?: string; onLog?: (line: string) => void } = {}
): Promise<{ context: BrowserContext; page: Page; ready: ReadyMessage }> {
  const key = accountKey(platform, number)
  const title = `${getPlatform(platform).shortName} #${number}`
  const existing = open.get(key)
  if (existing) {
    if (existing.mode !== mode) {
      throw new Error(
        existing.mode === 'login'
          ? `${title} уже открыт для входа. Закройте его окно и повторите.`
          : `${title} сейчас занят заливкой.`
      )
    }
    const page = existing.context.pages()[0] ?? (await existing.context.newPage())
    return { context: existing.context, page, ready: existing.ready }
  }

  const log = (line: string): void => {
    uploadLog(platform, `profile#${number}`, line)
    options.onLog?.(line)
  }

  let readyCb: ((msg: ReadyMessage) => void) | undefined
  const args = ['launch', '--platform', platform, '--acc', String(number), '--mode', mode]
  if (options.url) args.push('--url', options.url)
  const child = spawnBridge('yt_bridge.py', args, {
    onLog: log,
    onMessage: (msg) => readyCb?.(msg as unknown as ReadyMessage)
  })
  const ready = await waitForReady(child, (cb) => (readyCb = cb), 150_000)

  let browser: Browser
  try {
    browser = await chromium.connectOverCDP(`http://127.0.0.1:${ready.port}`, { timeout: 30_000 })
  } catch (error) {
    child.stdin.end()
    await sleep(500)
    child.kill()
    throw error instanceof Error ? error : new Error(String(error))
  }
  const context = browser.contexts()[0] ?? (await browser.newContext())
  const item: OpenProfile = { platform, number, mode, child, browser, context, ready, closing: null }
  open.set(key, item)
  emit()

  for (const page of context.pages()) await applyEmulation(page, ready)
  context.on('page', (page) => void applyEmulation(page, ready))

  browser.on('disconnected', () => {
    if (open.get(key) === item) void closeAccountProfile(platform, number)
  })
  child.on('close', () => {
    if (open.get(key) === item) {
      open.delete(key)
      emit()
    }
  })

  const page = context.pages()[0] ?? (await context.newPage())
  log(`Chrome открыт (${mode}${ready.proxyLabel ? `, ${ready.proxyLabel}` : ', без прокси'})`)
  return { context, page, ready }
}

export function openYoutubeProfile(
  number: number,
  mode: YoutubeLaunchMode,
  options: { url?: string; onLog?: (line: string) => void } = {}
): Promise<{ context: BrowserContext; page: Page; ready: ReadyMessage }> {
  return openAccountProfile('youtube', number, mode, options)
}

export async function closeAccountProfile(platform: PlatformId, number: number): Promise<void> {
  const key = accountKey(platform, number)
  const item = open.get(key)
  if (!item) return
  if (item.closing) return item.closing
  item.closing = (async () => {
    open.delete(key)
    emit()
    try {
      await item.browser.close()
    } catch {
      /* уже отключён */
    }
    try {
      item.child.stdin.write('close\n')
      item.child.stdin.end()
    } catch {
      /* stdin закрыт */
    }
    const exited = await Promise.race([
      new Promise<boolean>((resolve) => item.child.once('close', () => resolve(true))),
      sleep(15_000).then(() => false)
    ])
    if (!exited) {
      item.child.kill()
      await runBridge('yt_bridge.py', ['kill', '--platform', platform, '--acc', String(number)], { timeoutMs: 40_000 }).catch(
        () => undefined
      )
    }
  })()
  return item.closing
}

export function closeYoutubeProfile(number: number): Promise<void> {
  return closeAccountProfile('youtube', number)
}

export async function closeAllYoutubeProfiles(): Promise<void> {
  await Promise.all([...open.values()].map((item) => closeAccountProfile(item.platform, item.number)))
}

/** Режим Chrome для заливки: по умолчанию обычный Chrome + прокси (как в генераторе), по тумблеру — антидетект. */
export function uploadLaunchMode(): YoutubeLaunchMode {
  return getPersisted().settings.antidetectOnUpload ? 'login' : 'upload'
}
