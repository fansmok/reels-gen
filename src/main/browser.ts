import type { BrowserContext, Page } from 'playwright-core'
import { chromium } from 'playwright-core'
import { getPlatform } from '../shared/platforms'
import { isProxyConfigured, normalizeProxy } from '../shared/proxy'
import type { PlatformId, ProxyConfig } from '../shared/types'
import { startProxyRelay, type ProxyRelayHandle } from './proxy-relay'
import { stealthInitScript } from './stealth'
import { getPersisted, sessionsDir } from './store'

const openContexts = new Map<PlatformId, BrowserContext>()
const openRelays = new Map<PlatformId, ProxyRelayHandle>()

function playwrightProxy(proxy: ProxyConfig): { server: string; username?: string; password?: string } | undefined {
  const normalized = normalizeProxy(proxy)
  if (!isProxyConfigured(normalized)) return undefined
  const scheme = normalized.type === 'socks5' ? 'socks5' : 'http'
  return {
    server: `${scheme}://${normalized.host}:${normalized.port}`,
    username: normalized.username || undefined,
    password: normalized.password || undefined
  }
}

function shouldUseProxy(platform: PlatformId): boolean {
  const persisted = getPersisted()
  return persisted.platforms[platform].useProxy && isProxyConfigured(persisted.proxy)
}

function chromeArgs(proxyServer?: string, platform?: PlatformId): string[] {
  const args = ['--disable-blink-features=AutomationControlled', '--start-maximized']
  if (platform === 'instagram') args.push('--disable-http3')
  if (proxyServer) {
    args.push(`--proxy-server=${proxyServer}`, '--proxy-bypass-list=<-loopback>')
  }
  return args
}

async function launchWithFallback(
  userDataDir: string,
  options: Parameters<typeof chromium.launchPersistentContext>[1]
): Promise<BrowserContext> {
  const channels = ['chrome', 'msedge'] as const
  let lastError: unknown
  for (const channel of channels) {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        return await chromium.launchPersistentContext(userDataDir, { ...options, channel })
      } catch (error) {
        lastError = error
        await new Promise((resolve) => setTimeout(resolve, 800))
      }
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new Error('Не удалось открыть Chrome или Edge. Закройте лишние окна браузера и попробуйте снова.')
}

export async function closePlatformBrowser(platform: PlatformId): Promise<void> {
  const existing = openContexts.get(platform)
  if (existing) {
    openContexts.delete(platform)
    try {
      await existing.close()
    } catch {
      /* already closed */
    }
  }
  const relay = openRelays.get(platform)
  if (relay) {
    openRelays.delete(platform)
    await relay.close().catch(() => undefined)
  }
}

export async function openPlatformBrowser(platform: PlatformId): Promise<{ context: BrowserContext; page: Page }> {
  await closePlatformBrowser(platform)
  const persisted = getPersisted()
  const useProxy = shouldUseProxy(platform)

  let proxyServer: string | undefined
  let playwright: { server: string; username?: string; password?: string } | undefined
  if (useProxy) {
    const normalized = normalizeProxy(persisted.proxy)
    if (normalized.type === 'http') {
      const relay = await startProxyRelay(normalized)
      openRelays.set(platform, relay)
      proxyServer = relay.localUrl
    } else {
      proxyServer = `socks5://${normalized.host}:${normalized.port}`
      playwright = playwrightProxy(normalized)
    }
  }

  const context = await launchWithFallback(sessionsDir(platform), {
    channel: 'chrome',
    headless: false,
    viewport: null,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    args: chromeArgs(proxyServer, platform),
    ignoreDefaultArgs: [
      '--enable-automation',
      '--disable-extensions',
      '--disable-component-extensions-with-background-pages',
      '--disable-default-apps',
      '--disable-sync',
      '--metrics-recording-only'
    ],
    proxy: playwright
  }).catch(async (error) => {
    await closePlatformBrowser(platform)
    throw error
  })

  await context.addInitScript(stealthInitScript)

  openContexts.set(platform, context)
  context.on('close', () => {
    if (openContexts.get(platform) === context) openContexts.delete(platform)
    const relay = openRelays.get(platform)
    if (relay) {
      openRelays.delete(platform)
      void relay.close()
    }
  })
  const page = context.pages()[0] ?? (await context.newPage())
  const { preparePage, watchNewPages } = await import('./uploaders/helpers')
  const { uploadLog } = await import('./uploaders/upload-log')
  if (platform !== 'instagram') {
    await preparePage(page).catch(() => undefined)
  }
  watchNewPages(context, platform, page)
  uploadLog(platform, 'browser', `основная вкладка ${page.url() || '(пусто)'}`)
  return { context, page }
}

export function isBrowserOpen(platform: PlatformId): boolean {
  return openContexts.has(platform)
}

export async function probeChrome(): Promise<{ ok: boolean; message?: string }> {
  try {
    const browser = await chromium.launch({ channel: 'chrome', headless: true })
    await browser.close()
    return { ok: true }
  } catch {
    try {
      const browser = await chromium.launch({ channel: 'msedge', headless: true })
      await browser.close()
      return { ok: true, message: 'Используется Microsoft Edge' }
    } catch {
      return {
        ok: false,
        message: 'Не найден Google Chrome. Установите Chrome — бот открывает его для входа и загрузки.'
      }
    }
  }
}

export async function testProxy(): Promise<{ ok: boolean; ip?: string; error?: string }> {
  const persisted = getPersisted()
  if (!isProxyConfigured(persisted.proxy)) {
    return { ok: false, error: 'Вставьте прокси одной строкой: host:port:login:pass' }
  }
  let relay: ProxyRelayHandle | undefined
  let context: BrowserContext | undefined
  try {
    const normalized = normalizeProxy(persisted.proxy)
    let proxyServer: string
    let playwright: { server: string; username?: string; password?: string } | undefined
    if (normalized.type === 'http') {
      relay = await startProxyRelay(normalized)
      proxyServer = relay.localUrl
    } else {
      proxyServer = `socks5://${normalized.host}:${normalized.port}`
      playwright = playwrightProxy(normalized)
    }
    context = await chromium.launchPersistentContext('', {
      channel: 'chrome',
      headless: true,
      args: [`--proxy-server=${proxyServer}`, '--proxy-bypass-list=<-loopback>'],
      proxy: playwright
    })
    const page = await context.newPage()
    const ip = await readExitIp(page)
    return { ok: true, ip }
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) }
  } finally {
    await context?.close().catch(() => undefined)
    await relay?.close().catch(() => undefined)
  }
}

async function readExitIp(page: Page): Promise<string> {
  const urls = ['https://api.ipify.org?format=json', 'https://api64.ipify.org?format=json']
  let lastError: unknown
  for (const url of urls) {
    try {
      await page.goto(url, { timeout: 25_000, waitUntil: 'domcontentloaded' })
      const body = await page.locator('body').innerText()
      const ip = String(JSON.parse(body).ip || '').trim()
      if (ip) return ip
    } catch (error) {
      lastError = error
    }
  }
  throw lastError instanceof Error ? lastError : new Error('Не удалось проверить IP через прокси')
}

export async function gotoLogin(platform: PlatformId): Promise<Page> {
  const { page } = await openPlatformBrowser(platform)
  const meta = getPlatform(platform)
  const { softGoto } = await import('./uploaders/helpers')
  const url = platform === 'instagram' ? 'https://www.instagram.com/' : meta.loginUrl
  await softGoto(page, url)
  return page
}

export function getOpenContext(platform: PlatformId): BrowserContext | undefined {
  return openContexts.get(platform)
}

export async function closeAllBrowsers(): Promise<void> {
  const ids = [...openContexts.keys()]
  await Promise.all(ids.map((id) => closePlatformBrowser(id)))
}
