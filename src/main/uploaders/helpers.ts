import { existsSync } from 'fs'
import type { BrowserContext, Locator, Page } from 'playwright-core'
import { setTimeout as sleep } from 'node:timers/promises'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'

export { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'

export async function humanDelay(min = 80, max = 180): Promise<void> {
  await sleep(min + Math.random() * (max - min))
}

export async function withRetry<T>(
  fn: () => Promise<T>,
  attempts = 2,
  delayMs = 1500,
  shouldRetry: (error: unknown) => boolean = () => true
): Promise<T> {
  let lastError: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error
      if (isStopError(error)) throw error
      if (!shouldRetry(error)) throw error
      if (i < attempts - 1) await sleep(delayMs)
    }
  }
  throw lastError
}

export function isHttpStatusFailure(error: unknown): boolean {
  return /err_http_response_code_failure/i.test(error instanceof Error ? error.message : String(error))
}

export function isNetworkError(error: unknown): boolean {
  const msg = (error instanceof Error ? error.message : String(error)).toLowerCase()
  if (isHttpStatusFailure(error)) return false
  return /err_connection|err_timed|err_ssl|err_tunnel|err_name_not_resolved|err_internet|err_proxy|err_http2|timeout|net::|connection was reset|forcibly closed/.test(
    msg
  )
}

export function alreadyOn(page: Page, url: string): boolean {
  try {
    const target = new URL(url)
    const current = new URL(page.url())
    const host = (value: string): string => value.replace(/^www\./, '').toLowerCase()
    if (host(current.hostname) !== host(target.hostname)) return false
    const tp = target.pathname.replace(/\/$/, '') || '/'
    const cp = current.pathname.replace(/\/$/, '') || '/'
    if (tp === '/') return !/\/business\/|\/login|\/signin|\/auth|\/accounts\/login/i.test(cp + current.pathname)
    return cp === tp || cp.startsWith(`${tp}/`)
  } catch {
    return false
  }
}

export async function clickIfPresent(page: Page, selectors: string[]): Promise<boolean> {
  if (page.isClosed()) return false
  for (const selector of selectors) {
    const locator = page.locator(selector).first()
    if ((await locator.count().catch(() => 0)) === 0) continue
    if (!(await locator.isVisible().catch(() => false))) continue
    await locator.click({ timeout: 1500 }).catch(async () => locator.click({ timeout: 800, force: true }))
    return true
  }
  return false
}

const BUSY_RE =
  /загрузк[аиеу]|загружается|обработк[аиеу]|обрабатывается|uploading|processing|encoding|checking your video|идёт загрузка|видео загружается|осталось/i

export async function waitWhileBusy(page: Page, timeout = 180_000): Promise<void> {
  const deadline = Date.now() + timeout
  let idleHits = 0
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    const texts = await page
      .locator('[role="progressbar"], [data-e2e="upload_status_container"], ytcp-video-upload-progress, [class*="UploadProgress"]')
      .allInnerTexts()
      .catch(() => [])
    const busy = texts.some((text) => BUSY_RE.test(text) && !/complete|готов|успешн|100\s*%/i.test(text))
    if (!busy) {
      idleHits += 1
      if (idleHits >= 3) return
    } else {
      idleHits = 0
    }
    await sleep(400)
  }
}

export async function waitUntilEnabled(locator: Locator, timeout = 180_000): Promise<void> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if ((await locator.count().catch(() => 0)) > 0 && (await locator.isVisible().catch(() => false))) {
      const disabled = await locator.isDisabled().catch(() => true)
      const aria = await locator.getAttribute('aria-disabled').catch(() => null)
      if (!disabled && aria !== 'true') return
    }
    await sleep(300)
  }
  throw new Error('Видео ещё загружается или обрабатывается. Дождитесь готовности и повторите.')
}

export async function clickWhenEnabled(
  page: Page,
  selector: string,
  timeout = 60_000
): Promise<boolean> {
  const locator = page.locator(selector).first()
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (page.isClosed()) return false
    if ((await locator.count().catch(() => 0)) > 0 && (await locator.isVisible().catch(() => false))) {
      const disabled = await locator.isDisabled().catch(() => false)
      const aria = await locator.getAttribute('aria-disabled').catch(() => null)
      if (!disabled && aria !== 'true') {
        await locator.click({ timeout: 4000 }).catch(async () => locator.click({ timeout: 2000, force: true }))
        return true
      }
    }
    await sleep(250)
  }
  return false
}

export async function softGoto(page: Page, url: string): Promise<void> {
  try {
    await page.goto(url, { waitUntil: 'commit', timeout: 60_000 })
  } catch (error) {
    if (isHttpStatusFailure(error) || /err_aborted/i.test(String(error))) {
      await page.waitForLoadState('domcontentloaded').catch(() => undefined)
      return
    }
    throw error
  }
}

export async function isBlockedPage(page: Page): Promise<boolean> {
  if (page.isClosed()) return true
  const url = page.url().toLowerCase()
  if (url.startsWith('chrome-error://') || url.includes('chromewebdata') || url.startsWith('about:neterror')) return true
  const err = page.locator(
    '#main-frame-error, .error-code, text=ERR_CONNECTION_RESET, text=ERR_CONNECTION_TIMED_OUT, text=ERR_TIMED_OUT, text=ERR_SSL, text=ERR_CONNECTION_CLOSED'
  )
  return (await err.count().catch(() => 0)) > 0
}

export function platformFromUrl(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, '').toLowerCase()
    if (host.includes('youtube') || host.includes('youtu.be')) return 'youtube'
    if (host.includes('rutube')) return 'rutube'
    if (host.includes('pinterest')) return 'pinterest'
    if (host.includes('dzen') || host.includes('zen.yandex')) return 'dzen'
    if (host.includes('tiktok')) return 'tiktok'
    if (host.includes('vk.') || host === 'vk.ru' || host === 'vk.com' || host === 'm.vk.ru' || host === 'm.vk.com') {
      return 'vk'
    }
    if (host.includes('instagram') || host.includes('cdninstagram')) return 'instagram'
  } catch {
    /* invalid url */
  }
  return 'unknown'
}

export function platformFromPage(page: Page): string {
  return platformFromUrl(page.url())
}

/** Реклама / помощь / academy / календарь — не основной upload-флоу. */
export function looksLikeNuisanceTab(url: string): boolean {
  const u = url.toLowerCase()
  if (!u || u.startsWith('about:') || u.startsWith('chrome:') || u.startsWith('chrome-extension:')) return false
  if (
    /oauth|accounts\.google|signin|login|passport|id\.vk|studio\.youtube|tiktokstudio|pin-builder|\/upload|\/create|reel|clip|editor|composer|challenge|captcha|approve_browser|consent|myaccount\.google/i.test(
      u
    )
  ) {
    return false
  }
  return /\/ads(\b|\/|\?)|[./]ads\.|doubleclick|googlesyndication|adservice|adsmanager|\/help(\b|\/|\?)|\/support(\b|\/|\?)|support\.(google|youtube|tiktok|vk|pinterest|rutube)|academy|skillshop|creatoracademy|\/learn(\b|\/|\?)|calendar\.google|\/calendar(\b|\/|\?)|youtube\.com\/premium|youtube\.com\/paid_memberships|tiktok\.com\/business|pinterest\.com\/(?:business|ideas)|dzen\.ru\/help|rutube\.ru\/info|vk\.(?:com|ru)\/(?:ads|help)/i.test(
    u
  )
}

export async function safeGoto(page: Page, url: string, attempts = 3): Promise<void> {
  const fromTarget = platformFromUrl(url)
  const platform = fromTarget !== 'unknown' ? fromTarget : platformFromPage(page)
  if (alreadyOn(page, url) && !page.url().startsWith('about:')) {
    uploadLog(platform, 'goto', `уже открыто ${url}`)
    await preparePage(page)
    await dismissNuisances(page)
    return
  }
  uploadLog(platform, 'goto', url)
  let lastError: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      if (page.isClosed()) throw new Error('Окно браузера закрыто')
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 })
      await humanDelay(120, 250)
      await preparePage(page)
      await dismissNuisances(page)
      if (await isBlockedPage(page)) {
        throw new Error(`Сайт не открылся (${url}). Сеть сбрасывает соединение — нужен прокси.`)
      }
      uploadLog(platform, 'goto-ok', page.url() || url)
      return
    } catch (error) {
      if (isHttpStatusFailure(error)) {
        const host = new URL(url).hostname.replace(/^www\./, '')
        if (page.url().toLowerCase().includes(host) && !(await isBlockedPage(page))) {
          uploadLog(platform, 'goto-ok', `http-status, но хост открыт ${page.url()}`)
          return
        }
      }
      lastError = error
      uploadLogError(platform, `goto attempt ${i + 1}/${attempts}`, error)
      await sleep(1200 + i * 800)
    }
  }
  if (isNetworkError(lastError) || (lastError instanceof Error && lastError.message.includes('нужен прокси'))) {
    const message = `Не открылась страница ${url}. Провайдер может блокировать сайт — включите прокси для этой площадки.`
    uploadLogError(platform, 'goto', message)
    throw new Error(message)
  }
  uploadLogError(platform, 'goto', lastError)
  throw lastError instanceof Error ? lastError : new Error(`Не открылась страница ${url}`)
}

export async function firstVisible(page: Page, selectors: string[], timeout = 12_000): Promise<Locator> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    for (const selector of selectors) {
      const locator = page.locator(selector).first()
      if ((await locator.count().catch(() => 0)) > 0 && (await locator.isVisible().catch(() => false))) {
        return locator
      }
    }
    await sleep(150)
  }
  throw new Error(`Не найден элемент: ${selectors.slice(0, 3).join(' | ')}`)
}

export async function clickFirst(page: Page, selectors: string[], timeout = 12_000): Promise<void> {
  const locator = await firstVisible(page, selectors, timeout)
  await locator.click({ timeout: 8000 }).catch(async () => {
    await locator.click({ timeout: 5000, force: true })
  })
}

export async function clickFirstOptional(page: Page, selectors: string[], timeout = 2500): Promise<boolean> {
  try {
    await clickFirst(page, selectors, timeout)
    return true
  } catch {
    return false
  }
}

export async function clickText(page: Page, texts: string[], timeout = 4000, exact = false): Promise<boolean> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (page.isClosed()) return false
    for (const text of texts) {
      const byRole = page.getByRole('button', exact ? { name: text, exact: true } : { name: new RegExp(escapeReg(text), 'i') }).first()
      if (await byRole.isVisible().catch(() => false)) {
        await byRole.click().catch(() => byRole.click({ force: true }))
        return true
      }
      const byText = page.getByText(text, { exact }).first()
      if (await byText.isVisible().catch(() => false)) {
        const label = `${await byText.getAttribute('aria-label')} ${await byText.innerText()}`.toLowerCase()
        if (!exact && /позже|later|schedule/.test(label) && /опублик|publish/.test(text.toLowerCase())) continue
        await byText.click().catch(() => byText.click({ force: true }))
        return true
      }
    }
    await sleep(250)
  }
  return false
}

/** Клик по кнопке/role=button независимо от языка UI. */
export async function clickByName(page: Page, name: RegExp, timeout = 8000): Promise<boolean> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (page.isClosed()) return false
    const btn = page.getByRole('button', { name }).first()
    if (await btn.isVisible().catch(() => false)) {
      await btn.click().catch(() => btn.click({ force: true }))
      return true
    }
    await sleep(250)
  }
  return false
}

export const I18N = {
  next: /^(next|далее|следующий|siguiente|suivant|weiter|avanti|próximo|proximo|dalej|ileri|次へ|다음|下一步)$/i,
  create: /create|создать|crear|créer|erstellen|crea|criar/i,
  newPost:
    /new post|новая публикация|создать|nueva publicaci[oó]n|nouvelle publication|neuer beitrag|nuovo post|nova publica|nowy post|yeni g[oö]nderi|新しい投稿|새 게시물|新帖子/i,
  publish:
    /^(publish|опубликовать|опублікувати|veröffentlichen|publicar|publier|pubblica|yayınla|opublikuj|公開|게시|发布|發佈)$/i,
  share: /^(share|поделиться|compartir|partager|teilen|condividi|partilhar|paylaş)$/i,
  save: /^(save|сохранить|speichern|guardar|enregistrer|salva|salvar)$/i,
  done: /^(done|готово|fertig|listo|terminé|fatto)$/i,
  selectFile:
    /select (files?|video|from computer)|выбрать( файлы| видео| на компьютере)?|upload( video| files?)?|загрузить( видео)?|choisir|auswählen|seleccionar|seleziona/i,
  cover:
    /cover|облож|заставк|кадр|thumbnail|thumb|miniatura|vignette|vorschaubild|copertina/i,
  editCover:
    /edit cover|редактировать обложку|фото обложки|cover photo|change cover|custom cover|upload cover|указать заставку|выбрать обложку|загрузить свою/i,
  notNow: /^(not now|не сейчас|ahora no|pas maintenant|jetzt nicht|non ora|agora não|şimdi değil)$/i,
  gotIt: /^(got it|i understand|понятно|хорошо|entendido|verstanden|capito|j'ai compris)$/i,
  acceptCookies: /accept all|allow all cookies|принять все|разрешить все|akzeptieren|aceptar todas|accepter tout|accetta tutti|aceitar todos/i,
  close: /^(close|закрыть|cerrar|fermer|schließen|chiudi|fechar|kapat)$/i,
  comments: /comment|комментар|comentarios|kommentar/i,
  madeForKidsNo: /not made for kids|не (для детей|детский)|no[, ]+it'?s not|kein kinder|no es para ni[nñ]os/i,
  madeForKidsYes: /made for kids|для детей|sí,? es para ni[nñ]os/i,
  public: /^(public|открытый доступ|все пользователи|público|öffentlich|publiczne)$/i,
  unlisted: /unlisted|доступ по ссылке|ограниченный|nicht gelistet|no listado/i,
  private: /^(private|закрытый|личное|privado|privat)$/i
} as const

function escapeReg(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export async function setToggle(page: Page, selectors: string[], on: boolean, timeout = 8000): Promise<boolean> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first()
    if ((await locator.count().catch(() => 0)) === 0) continue
    try {
      await locator.setChecked(on, { timeout, force: true })
      return true
    } catch {
      const current = await locator.isChecked().catch(() => !on)
      if (current === on) return true
      await locator.click({ timeout: 4000, force: true }).catch(() => undefined)
      return true
    }
  }
  return false
}

export async function fillFirst(page: Page, selectors: string[], value: string, timeout = 12_000): Promise<void> {
  const locator = await firstVisible(page, selectors, timeout)
  await locator.click().catch(() => undefined)
  await humanDelay(40, 90)
  const selectAll = process.platform === 'darwin' ? 'Meta+A' : 'Control+A'
  await page.keyboard.press(selectAll).catch(() => undefined)
  try {
    await locator.fill(value)
  } catch {
    await page.keyboard.type(value, { delay: 12 })
  }
}

export async function attachFile(page: Page, filePath: string, clickSelectors: string[] = []): Promise<void> {
  if (!existsSync(filePath)) throw new Error(`Файл не найден: ${filePath}`)

  for (const selector of clickSelectors) {
    if (!/input|file-loader|upload-input|Filedata/i.test(selector)) continue
    if (selector === 'input[type="file"]') continue
    const loc = page.locator(selector).first()
    if ((await loc.count().catch(() => 0)) === 0) continue
    try {
      await loc.setInputFiles(filePath)
      return
    } catch {
      /* не file input */
    }
  }

  const listed = await listFileInputs(page)
  const videoIdx = listed.find((x) => x.video)?.i ?? listed.find((x) => !x.image)?.i
  if (videoIdx !== undefined) {
    try {
      await page.locator('input[type="file"]').nth(videoIdx).setInputFiles(filePath)
      return
    } catch {
      /* chooser */
    }
  }

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 25_000 })
  const clicked = clickSelectors.length
    ? await clickFirstOptional(page, clickSelectors, 12_000)
    : false
  if (!clicked) {
    const byName = await clickByName(page, I18N.selectFile, 8000)
    if (!byName) throw new Error('Не найдена кнопка выбора файла')
  }
  const chooser = await chooserPromise
  await chooser.setFiles(filePath)
}

export async function attachFileOptional(
  page: Page,
  filePath: string | undefined,
  clickSelectors: string[] = []
): Promise<void> {
  if (!filePath) return
  try {
    await attachFile(page, filePath, clickSelectors)
  } catch {
    /* cover is optional on some platforms */
  }
}

export function looksLoggedOut(url: string): boolean {
  const u = url.toLowerCase()
  return (
    u.includes('/login') ||
    u.includes('/signin') ||
    u.includes('accounts.google.com') ||
    u.includes('passport.yandex') ||
    u.includes('id.vk.') ||
    u.includes('/oauth')
  )
}

export async function hasChallenge(page: Page): Promise<boolean> {
  if (page.isClosed()) return false
  const prompt = page
    .getByText(/verify you are human|подтвердите, что вы не робот|unusual traffic|are you a robot/i)
    .first()
  if (await prompt.isVisible().catch(() => false)) return true

  // Только окно-пазл (bframe). Бейдж recaptcha/enterprise/anchor на Pinterest есть всегда — это не капча.
  const puzzles = page.locator(
    'iframe[src*="recaptcha"][src*="bframe"], iframe[src*="hcaptcha.com/captcha"], iframe[title*="challenge" i]'
  )
  const total = Math.min(await puzzles.count().catch(() => 0), 6)
  for (let i = 0; i < total; i++) {
    const frame = puzzles.nth(i)
    if (!(await frame.isVisible().catch(() => false))) continue
    const box = await frame.boundingBox().catch(() => null)
    if (box && box.width >= 180 && box.height >= 120) return true
  }
  return false
}

export async function waitIfChallenge(
  page: Page,
  onWait?: (message: string) => void,
  timeoutMs = 180_000
): Promise<void> {
  if (!(await hasChallenge(page))) return
  onWait?.('Капча или проверка. Подтвердите в окне Chrome — бот подождёт.')
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (page.isClosed()) return
    if (!(await hasChallenge(page))) {
      await humanDelay(600, 1200)
      return
    }
    await sleep(2000)
  }
}

export function isStopError(error: unknown): boolean {
  return error instanceof Error && error.message === 'Очередь остановлена'
}

const WATCH_URL_RE: Record<string, RegExp> = {
  youtube: /(?:youtube\.com\/(?:watch\?v=|shorts\/|live\/)|youtu\.be\/)/i,
  rutube: /rutube\.ru\/(?:video|shorts)\/[a-zA-Z0-9]+/i,
  pinterest: /pinterest\.(?:com|ru)\/pin\/\d+/i,
  dzen: /dzen\.ru\/(?:video\/watch|shorts)\/[a-zA-Z0-9_-]+/i,
  tiktok: /tiktok\.com\/@[^/]+\/video\/\d+/i,
  vk: /vk\.(?:com|ru)\/(?:clip-?\d+_\d+|video-?\d+_\d+)/i,
  instagram: /instagram\.com\/(?:reel|p)\/[A-Za-z0-9_-]+/i
}

function youtubePublicUrl(raw: string): string | undefined {
  const studio = raw.match(/studio\.youtube\.com\/video\/([a-zA-Z0-9_-]{6,})/i)
  if (studio) return `https://www.youtube.com/shorts/${studio[1]}`
  const watch = raw.match(/[?&]v=([a-zA-Z0-9_-]{6,})/)
  if (watch) return `https://www.youtube.com/watch?v=${watch[1]}`
  const shorts = raw.match(/youtube\.com\/shorts\/([a-zA-Z0-9_-]{6,})/i)
  if (shorts) return `https://www.youtube.com/shorts/${shorts[1]}`
  return undefined
}

function studioToPublic(platform: string, raw: string): string | undefined {
  if (platform === 'youtube') return youtubePublicUrl(raw)
  if (platform === 'rutube') {
    const id = raw.match(/rutube\.ru\/(?:video|metainfo\/video)\/([a-zA-Z0-9]+)/i)
    if (id) return `https://rutube.ru/video/${id[1]}/`
    const studio = raw.match(/studio\.rutube\.ru\/(?:video|editor)\/([a-zA-Z0-9-]+)/i)
    if (studio) return `https://rutube.ru/video/${studio[1]}/`
  }
  if (platform === 'dzen') {
    const pub = raw.match(/videoEditorPublicationId=([a-zA-Z0-9_-]+)/i)
    if (pub) return `https://dzen.ru/video/watch/${pub[1]}`
    const watch = raw.match(/dzen\.ru\/(?:video\/watch|shorts)\/([a-zA-Z0-9_-]+)/i)
    if (watch) return `https://dzen.ru/video/watch/${watch[1]}`
  }
  if (platform === 'pinterest') {
    const pin = raw.match(/\/pin\/(\d+)/)
    if (pin) return `https://www.pinterest.com/pin/${pin[1]}/`
  }
  return undefined
}

function isWatchable(platform: string, url?: string): boolean {
  if (!url || !/^https?:\/\//i.test(url)) return false
  if (WATCH_URL_RE[platform]?.test(url)) return true
  return Boolean(studioToPublic(platform, url))
}

const UPLOAD_FORM_RE =
  /pin-creation-tool|idea-pin-builder|tiktokstudio\/upload|\/upload$|instagram\.com\/(?:create|reels\/?$)|studio\.youtube\.com\/channel|vk\.(?:com|ru)\/clips(?:\/(?:upload|club|public)|\/?$)|vk\.com\/clip\/new|dzen\.ru\/(?:studio\/video\/create|profile\/editor)/i

function pickPublished(platform: string, candidates: string[]): string | undefined {
  for (const raw of candidates) {
    if (!raw) continue
    const converted = studioToPublic(platform, raw)
    if (converted) return converted
    if (UPLOAD_FORM_RE.test(raw)) continue
    if (WATCH_URL_RE[platform]?.test(raw)) return raw.split('&')[0]
  }
  return candidates.find((url) => isWatchable(platform, url) && !UPLOAD_FORM_RE.test(url))
}

async function collectUrlCandidates(page: Page, fallback?: string): Promise<string[]> {
  const candidates: string[] = []
  if (fallback) candidates.push(fallback)
  if (page.isClosed()) return candidates
  candidates.push(page.url())
  const share = page
    .locator(
      '#share-url, input#share-url, ytcp-video-share-dialog input, input[aria-label*="ссылк" i], input[aria-label*="link" i]'
    )
    .first()
  if ((await share.count().catch(() => 0)) > 0) {
    const value = await share.inputValue().catch(() => '')
    if (value) candidates.push(value)
  }
  const hrefs = await page
    .locator('a[href]')
    .evaluateAll((els) =>
      els
        .map((el) => (el as HTMLAnchorElement).href)
        .filter((href) => /^https?:\/\//i.test(href))
        .slice(0, 120)
    )
    .catch(() => [] as string[])
  candidates.push(...hrefs)
  const values = await page
    .locator('input, textarea')
    .evaluateAll((els) =>
      els
        .map((el) => (el as HTMLInputElement).value)
        .filter((value) => /^https?:\/\//i.test(value))
        .slice(0, 20)
    )
    .catch(() => [] as string[])
  candidates.push(...values)
  return candidates
}

/** Ссылка на опубликованный ролик, а не на форму загрузки. */
export async function resolvePublishedUrl(
  page: Page,
  platform: string,
  fallback?: string
): Promise<string | undefined> {
  if (page.isClosed()) return toPublicWatchUrl(platform, fallback)
  const found = pickPublished(platform, await collectUrlCandidates(page, fallback))
  if (found) return found
  return toPublicWatchUrl(platform, fallback)
}

export function toPublicWatchUrl(platform: string, raw?: string): string | undefined {
  if (!raw) return undefined
  return pickPublished(platform, [raw])
}

const CONTENT_LIBRARY: Partial<Record<string, string>> = {
  youtube: 'https://studio.youtube.com/',
  rutube: 'https://studio.rutube.ru/videos',
  pinterest: 'https://www.pinterest.com/me/',
  dzen: 'https://dzen.ru/profile/editor/publications',
  tiktok: 'https://www.tiktok.com/tiktokstudio/content',
  vk: 'https://vk.ru/clips',
  instagram: 'https://www.instagram.com/'
}

/** Публичная ссылка на рилс. Если форма загрузки её не отдала — открываем список роликов и берём свежую. */
export async function captureReelLink(page: Page, platform: string, rawUrl?: string): Promise<string | undefined> {
  const watchable = (value?: string): string | undefined => {
    const pub = toPublicWatchUrl(platform, value)
    if (!pub || UPLOAD_FORM_RE.test(pub)) return undefined
    return pub
  }
  const direct = watchable(rawUrl)
  if (direct) return direct
  if (page.isClosed()) return undefined
  const scraped = await resolvePublishedUrl(page, platform, rawUrl).catch(() => undefined)
  const fromPage = watchable(scraped)
  if (fromPage) return fromPage
  const library = CONTENT_LIBRARY[platform]
  if (!library) return undefined
  uploadLog(platform, 'link', 'открываю список роликов, чтобы взять ссылку')
  await page.goto(library, { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => undefined)
  await sleep(2200)
  const after = await resolvePublishedUrl(page, platform).catch(() => undefined)
  return watchable(after)
}

export async function waitForPublicUrl(
  page: Page,
  platform: string,
  timeout = 45_000
): Promise<string | undefined> {
  const deadline = Date.now() + timeout
  let last: string | undefined
  while (Date.now() < deadline) {
    if (page.isClosed()) return last
    last = await resolvePublishedUrl(page, platform, page.url())
    if (last) return last
    await sleep(500)
  }
  return last
}

const PREPARE_FLAG = '__reelsPrepared'

/** Кнопки закрытия баннеров — без «опубликовать» и без «далее» мастера загрузки. */
const COOKIE_BTN_RE =
  /accept all|allow all cookies|принять все|разрешить все|akzeptieren|aceptar todas|accepter tout|accetta tutti|aceitar todos|同意/i
const NOT_NOW_RE =
  /^(not now|не сейчас|ahora no|pas maintenant|jetzt nicht|non ora|agora não|şimdi değil|지금은 안 함|现在不要)$/i
const GOT_IT_RE =
  /^(got it|i understand|понятно|хорошо|entendido|verstanden|capito|j'ai compris|明白了)$/i

function isPublishLabel(text: string): boolean {
  return /опублик|publish|share|поделить|post now|^post$|выложить|publicar|publier/i.test(text) && !/позже|later|schedule|anyway/i.test(text)
}

export async function dismissNuisances(page: Page): Promise<void> {
  if (page.isClosed()) return
  const platform = platformFromPage(page)
  let dismissed = 0

  if (
    await clickIfPresent(page, [
      '#onetrust-accept-btn-handler',
      '#accept-all-cookies',
      'button[id*="accept-all" i]',
      'button[data-testid*="cookie" i][data-testid*="accept" i]',
      '[data-testid="cookie-policy-dialog"] button[id*="accept" i]'
    ])
  ) {
    dismissed += 1
  }

  const buttons = page.getByRole('button')
  const total = Math.min(await buttons.count().catch(() => 0), 20)
  for (let i = 0; i < total; i++) {
    const btn = buttons.nth(i)
    if (!(await btn.isVisible().catch(() => false))) continue
    const label = `${await btn.getAttribute('aria-label') ?? ''} ${await btn.innerText().catch(() => '')}`.replace(/\s+/g, ' ').trim()
    if (!label || isPublishLabel(label)) continue
    if (COOKIE_BTN_RE.test(label) || NOT_NOW_RE.test(label) || GOT_IT_RE.test(label)) {
      await btn.click({ timeout: 1200 }).catch(() => undefined)
      dismissed += 1
      await sleep(180)
    }
  }

  const notNow = page.getByText(NOT_NOW_RE).first()
  if (await notNow.isVisible().catch(() => false)) {
    await notNow.click({ timeout: 1200 }).catch(() => undefined)
    dismissed += 1
  }

  const errorModal = page.getByText(/что-то пошло не так|something went wrong|something’s wrong|something's wrong/i).first()
  if (await errorModal.isVisible().catch(() => false)) {
    await clickText(page, ['Повторить попытку', 'Retry', 'Try again', 'Try Again', 'OK'], 2000)
    await page.keyboard.press('Escape').catch(() => undefined)
    dismissed += 1
  }

  if (dismissed > 0) {
    uploadLog(platform, 'dismiss', `закрыто баннеров/диалогов: ${dismissed}`)
  }
}

async function settlePageUrl(page: Page, ms = 3500): Promise<string> {
  const deadline = Date.now() + ms
  while (Date.now() < deadline && !page.isClosed()) {
    const url = page.url()
    if (url && url !== 'about:blank' && !url.startsWith('about:')) return url
    await Promise.race([page.waitForLoadState('domcontentloaded').catch(() => undefined), sleep(350)])
  }
  return page.isClosed() ? '' : page.url()
}

async function handleExtraPage(platform: string, opened: Page, mainPage: Page): Promise<void> {
  if (opened.isClosed()) return
  const raw = opened.url() || '(loading)'
  uploadLogWindow(platform, raw, 'opened')

  if (platform !== 'instagram') {
    await preparePage(opened).catch(() => undefined)
  }

  const url = await settlePageUrl(opened)
  if (opened.isClosed()) return

  const isMain = opened === mainPage
  const livePages = opened.context().pages().filter((item) => !item.isClosed())
  const lastPage = livePages.length <= 1

  if (platform === 'instagram' || isMain || lastPage) {
    if (opened !== mainPage) uploadLogWindow(platform, url || raw, 'ignored')
    return
  }

  if (looksLikeNuisanceTab(url)) {
    await opened.close({ reason: 'лишнее окно: реклама/помощь/academy' }).catch(() => undefined)
    uploadLogWindow(platform, url, 'closed')
    return
  }

  if (opened !== mainPage) {
    uploadLogWindow(platform, url || raw, 'ignored')
  }
}

/** Логирует новые вкладки; явно лишние (реклама/помощь/academy/календарь) закрывает. Instagram не трогает. */
export function watchNewPages(context: BrowserContext, platform: string, mainPage: Page): void {
  const onPage = (opened: Page): void => {
    if (opened === mainPage) return
    void handleExtraPage(platform, opened, mainPage).catch((error) => {
      uploadLogError(platform, 'window', error)
    })
  }
  context.on('page', onPage)
  for (const extra of context.pages()) {
    if (extra !== mainPage) onPage(extra)
  }
}

export async function preparePage(page: Page): Promise<void> {
  if (page.isClosed()) return
  const already = await page.evaluate((flag) => Boolean((window as unknown as Record<string, boolean>)[flag]), PREPARE_FLAG).catch(() => false)
  if (!already) {
    await page.evaluate((flag) => {
      ;(window as unknown as Record<string, boolean>)[flag] = true
    }, PREPARE_FLAG).catch(() => undefined)
    page.on('dialog', (dialog) => {
      void dialog.dismiss().catch(() => undefined)
    })
    const overlays = [
      page.locator('#onetrust-banner-sdk, #onetrust-accept-btn-handler'),
      page.getByRole('dialog').filter({ hasText: /cookie|cookies|куки|consent|персональн/i }),
      page.getByRole('button', { name: NOT_NOW_RE }),
      page.getByRole('button', { name: GOT_IT_RE })
    ]
    for (const overlay of overlays) {
      try {
        await page.addLocatorHandler(overlay.first(), async () => {
          await dismissNuisances(page)
        })
      } catch {
        /* нет addLocatorHandler */
      }
    }
  }
  await dismissNuisances(page)
}

async function listFileInputs(page: Page): Promise<Array<{ i: number; image: boolean; video: boolean }>> {
  return page.evaluate(() =>
    [...document.querySelectorAll('input[type="file"]')].map((el, i) => {
      const accept = el.getAttribute('accept') || ''
      const aria = el.getAttribute('aria-label') || ''
      const id = el.id || ''
      const test = el.getAttribute('data-testid') || el.getAttribute('data-test-id') || el.getAttribute('data-e2e') || ''
      const name = el.getAttribute('name') || ''
      const blob = `${accept} ${aria} ${id} ${test} ${name}`.toLowerCase()
      const hasImage = /image|jpg|jpeg|png|webp|gif|thumb|cover|облож|заставк|кадр|still|poster/.test(blob)
      const hasVideo = /video|mp4|webm|quicktime|\.mov|\.avi/.test(blob)
      const image = hasImage && !hasVideo
      const video = hasVideo
      return { i, image, video }
    })
  )
}

export async function confirmCropDialog(page: Page): Promise<void> {
  await humanDelay(400, 800)
  const byId = page.locator(
    '[data-test-id="video-cover-edit-cover-done-button"], [data-e2e="cover_edit_confirm"], [data-e2e="confirm-cover"]'
  ).first()
  if (await byId.isVisible().catch(() => false)) {
    await byId.click({ timeout: 4000 }).catch(() => undefined)
    return
  }
  const dialog = page.locator('[role="dialog"], tp-yt-paper-dialog, [data-testid="modalbox"]').last()
  const confirm = dialog
    .getByRole('button', {
      name: /^(done|apply|save|ok|crop|confirm|готово|применить|сохранить|обрезать|подтвердить|listo|fertig|terminer|applica|confirmar)$/i
    })
    .first()
  if (await confirm.isVisible().catch(() => false)) {
    const label = `${await confirm.innerText()}`.trim()
    if (!isPublishLabel(label) && !/чернов|draft/i.test(label)) {
      await confirm.click({ timeout: 4000 }).catch(() => undefined)
    }
  }
}

async function setImageOnInput(page: Page, filePath: string, selector?: string, index?: number): Promise<boolean> {
  try {
    const loc = selector ? page.locator(selector).first() : page.locator('input[type="file"]').nth(index ?? 0)
    await loc.setInputFiles(filePath)
    await confirmCropDialog(page)
    return true
  } catch {
    return false
  }
}

export async function attachImage(page: Page, filePath: string, clickSelectors: string[] = []): Promise<boolean> {
  if (!filePath || !existsSync(filePath)) return false

  for (const selector of clickSelectors) {
    if (!/input|#file-loader|upload-input|accept/i.test(selector)) continue
    if (await setImageOnInput(page, filePath, selector)) return true
  }

  const tryListed = async (): Promise<boolean> => {
    const listed = await listFileInputs(page)
    const imageIdx = listed.find((x) => x.image)?.i
    if (imageIdx !== undefined) return setImageOnInput(page, filePath, undefined, imageIdx)
    return false
  }
  if (await tryListed()) return true

  await clickFirstOptional(page, clickSelectors, 8000)
  await clickFirstOptional(
    page,
    [
      '#file-loader',
      'input[type="file"][accept*="image"]',
      'button[aria-label*="cover" i]',
      'button[aria-label*="thumb" i]',
      'button[aria-label*="облож" i]',
      'button[aria-label*="заставк" i]',
      '[data-e2e="cover_container"]',
      '[data-e2e="cover_edit"]',
      '[data-test-id="video-cover-container-edit-cover-button"]',
      '[data-testid="clips-upload-cover"]'
    ],
    2500
  )
  await clickByName(page, I18N.editCover, 2500)
  await humanDelay(400, 700)
  if (await tryListed()) return true

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 12_000 }).catch(() => null)
  const dialog = page.locator('[role="dialog"], [class*="Cover"], [class*="cover-edit"], [data-e2e*="cover"]').last()
  const uploadInDialog = dialog
    .getByRole('button', { name: /upload|загрузить|custom|облож|image|файл|file/i })
    .filter({ hasNotText: /чернов|draft|cancel|отмен|schedule|позже/i })
    .first()
  const opened =
    (await uploadInDialog.isVisible().catch(() => false)
      ? await uploadInDialog.click({ timeout: 3000 }).then(() => true).catch(() => false)
      : false) ||
    (await clickByName(page, I18N.editCover, 3000)) ||
    (await clickText(
      page,
      [
        'Upload file',
        'Upload image',
        'Upload cover',
        'Edit cover',
        'Change cover',
        'Custom cover',
        'Select image',
        'Загрузить файл',
        'Загрузить обложку',
        'Выбрать обложку',
        'Указать заставку',
        'Редактировать обложку'
      ],
      3000
    ))
  const chooser = await chooserPromise
  if (chooser) {
    await chooser.setFiles(filePath)
    await confirmCropDialog(page)
    return true
  }
  if (!opened && (await tryListed())) return true
  await confirmCropDialog(page)
  return await tryListed()
}

export async function attachCoverOptional(page: Page, filePath: string | undefined, clickSelectors: string[] = []): Promise<void> {
  if (!filePath) return
  try {
    await attachImage(page, filePath, clickSelectors)
  } catch {
    /* обложка необязательна */
  }
}
