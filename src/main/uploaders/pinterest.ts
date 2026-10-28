import type { Locator, Page } from 'playwright-core'
import {
  dismissNuisances,
  fillFirst,
  humanDelay,
  looksLoggedOut,
  safeGoto,
  setToggle,
  waitUntilEnabled,
  resolvePublishedUrl,
  waitForPublicUrl
} from './helpers'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'
import type { PinterestPublishOptions } from '../../shared/publish-options'
import type { PlatformAdapter, UploadPayload } from './types'

const PIN_CREATION_URL = 'https://ru.pinterest.com/pin-creation-tool/'
const PIN_CREATION_URLS = [
  PIN_CREATION_URL,
  'https://www.pinterest.com/pin-creation-tool/',
  'https://ru.pinterest.com/idea-pin-builder/'
]
const PLATFORM = 'pinterest'

const VIDEO_INPUT = '#storyboard-upload-input, [data-test-id="storyboard-upload-input"]'
const TITLE_FIELDS = [
  '#storyboard-selector-title',
  '[data-test-id="storyboard-title-field-container"] input',
  '[data-test-id="pin-draft-title-text-area-container"] textarea',
  '[data-test-id="pin-draft-title-text-area-container"] input'
]
const DESC_FIELDS = [
  '[data-test-id="editor-with-mentions"] [contenteditable="true"]',
  '[data-test-id="storyboard-description-field-container"] [contenteditable="true"]',
  '[data-test-id="comment-editor-container"] [contenteditable="true"]'
]
const BUSY_RE = /загружается|обрабатывается|uploading|processing|encoding|preparing|подготовк/i
const FORMAT_ERROR_RE = /неправильный формат|wrong format|couldn't upload|не удалось загрузить/i
const PUBLISHED_RE =
  /your pin has been published|pin has been published|publish complete|пин опубликован|пин создан|published!/i
const JUNK_HOST_RE =
  /pinterestacademy|calendly|ads\.pinterest|help\.pinterest|business\.pinterest\.com/i
const JUNK_PATH_RE = /\/business\/blog|\/ads(?:\/|$)|\/help(?:\/|$)|\/pinterest-academy/i

function isVideoBuilder(url: string): boolean {
  return /pin-creation-tool|idea-pin-builder/i.test(url)
}

function isAdsPinBuilder(url: string): boolean {
  return /\/pin-builder/i.test(url) && !isVideoBuilder(url)
}

function isJunkUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (JUNK_HOST_RE.test(parsed.hostname)) return true
    if (JUNK_PATH_RE.test(parsed.pathname)) return true
    return false
  } catch {
    return JUNK_HOST_RE.test(url) || JUNK_PATH_RE.test(url)
  }
}

function publishWrap(page: Page): Locator {
  return page.locator('[data-test-id="storyboard-creation-nav-done"]').first()
}

function publishButton(page: Page): Locator {
  return publishWrap(page).locator('button').first()
}

function videoInput(page: Page): Locator {
  return page.locator(VIDEO_INPUT).first()
}

const notedWindows = new Set<string>()

async function closeExtraWindows(page: Page): Promise<void> {
  if (page.isClosed()) return
  for (const extra of page.context().pages()) {
    if (extra === page || extra.isClosed()) continue
    await extra.waitForLoadState('domcontentloaded', { timeout: 4000 }).catch(() => undefined)
    if (extra.isClosed()) continue
    const url = extra.url()
    if (isVideoBuilder(url) && !isVideoBuilder(page.url())) {
      uploadLog(PLATFORM, 'create', `видео-конструктор во вкладке ${url}`)
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 }).catch(() => undefined)
      await extra.close().catch(() => undefined)
      uploadLogWindow(PLATFORM, url, 'closed')
      continue
    }
    if ((isVideoBuilder(url) && isVideoBuilder(page.url())) || isJunkUrl(url) || isAdsPinBuilder(url)) {
      await extra.close().catch(() => undefined)
      uploadLogWindow(PLATFORM, url, 'closed')
      continue
    }
    if (!notedWindows.has(url)) {
      notedWindows.add(url)
      uploadLogWindow(PLATFORM, url, 'ignored')
    }
  }
}

async function loginCheck(page: Page): Promise<boolean> {
  uploadLog(PLATFORM, 'goto', PIN_CREATION_URL)
  await safeGoto(page, PIN_CREATION_URL)
  await dismissNuisances(page)
  await closeExtraWindows(page)
  if (looksLoggedOut(page.url())) {
    uploadLog(PLATFORM, 'login', `не вошли: ${page.url()}`)
    return false
  }
  const onTool = isVideoBuilder(page.url())
  const avatar = page
    .locator(
      '[data-test-id="header-profile"], [data-test-id="header-profile"] img, [data-test-id="user-avatar"], [data-test-id="header-accounts-options-button"], [data-test-id="header-create-menu-button"], [data-test-id="gestalt-create-button"]'
    )
    .first()
  const ok = onTool || (await avatar.count()) > 0 || /\/business(\/|$)/i.test(page.url())
  uploadLog(PLATFORM, 'login', ok ? `ok ${page.url()}` : `нет аватара ${page.url()}`)
  return ok
}

async function inputAcceptsVideo(page: Page): Promise<boolean> {
  const input = videoInput(page)
  if ((await input.count().catch(() => 0)) === 0) return false
  const accept = (await input.getAttribute('accept').catch(() => '')) || ''
  return /video/i.test(accept)
}

async function startFreshDraft(page: Page): Promise<void> {
  const create = page.locator('[data-test-id="storyboard-create-button"]').first()
  if (!(await create.isVisible().catch(() => false))) return
  uploadLog(PLATFORM, 'create', 'storyboard-create-button — новый черновик')
  await create.click({ timeout: 5000 }).catch(() => undefined)
  await humanDelay(400, 800)
}

async function gotoVideoBuilder(page: Page): Promise<void> {
  await closeExtraWindows(page)
  if (isVideoBuilder(page.url()) && (await inputAcceptsVideo(page))) {
    await startFreshDraft(page)
    uploadLog(PLATFORM, 'goto', `уже видео-конструктор ${page.url()}`)
    if (await inputAcceptsVideo(page)) return
  }

  for (const url of PIN_CREATION_URLS) {
    uploadLog(PLATFORM, 'goto', url)
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 }).catch(() => undefined)
    await closeExtraWindows(page)
    await dismissNuisances(page)
    if (isAdsPinBuilder(page.url())) {
      uploadLog(PLATFORM, 'create', `попали в объявления ${page.url()} — пропускаем`)
      continue
    }
    await startFreshDraft(page)
    await videoInput(page).waitFor({ state: 'attached', timeout: 12_000 }).catch(() => undefined)
    if (await inputAcceptsVideo(page)) {
      uploadLog(PLATFORM, 'goto', `видео-конструктор ${page.url()}`)
      return
    }
  }

  throw new Error(
    'Не открылся конструктор видео-пина (pin-creation-tool). Create → Пин с хаба открывает объявления без видео — нужен pin-creation-tool.'
  )
}

async function attachPinterestVideo(page: Page, videoPath: string): Promise<void> {
  const input = videoInput(page)
  await input.waitFor({ state: 'attached', timeout: 25_000 })
  if (!(await inputAcceptsVideo(page))) {
    throw new Error('Открыт конструктор объявлений: туда можно только картинки, не видео.')
  }

  try {
    await input.setInputFiles(videoPath)
    uploadLog(PLATFORM, 'file', `видео → storyboard-upload-input ${videoPath}`)
    return
  } catch (error) {
    uploadLog(
      PLATFORM,
      'file',
      `input не принял файл: ${error instanceof Error ? error.message : String(error)}`
    )
  }

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 15_000 })
  const drop = page
    .locator('[data-test-id="storyboard-draft-upload-container"], [data-test-id="drag-behavior-container"]')
    .first()
  if (await drop.isVisible().catch(() => false)) {
    await drop.click({ timeout: 5000 }).catch(() => drop.click({ force: true }))
  } else {
    await page.getByText(/загрузите медиафайлы|upload media/i).first().click({ timeout: 5000 })
  }
  await (await chooserPromise).setFiles(videoPath)
  uploadLog(PLATFORM, 'file', 'видео через filechooser «Загрузите медиафайлы»')
}

async function waitPinMediaReady(page: Page, timeout = 180_000): Promise<void> {
  uploadLog(PLATFORM, 'processing wait', 'ожидание обработки видео в pin-creation-tool')
  const title = page.locator('#storyboard-selector-title').first()
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await closeExtraWindows(page)
    const errorToast = page
      .locator('[role="alert"], [data-test-id*="toast"], [data-test-id*="banner"]')
      .filter({ hasText: FORMAT_ERROR_RE })
    if ((await errorToast.count().catch(() => 0)) > 0) {
      throw new Error(
        'Pinterest отклонил файл (неправильный формат). Видео грузим в pin-creation-tool, не в конструктор объявлений.'
      )
    }
    const draftText = await page
      .locator('[data-test-id="header-content-container"], [data-test-id="storyboard-pin-card"]')
      .first()
      .innerText()
      .catch(() => '')
    const busy = BUSY_RE.test(draftText)
    const titleReady = (await title.count()) > 0 && (await title.isVisible().catch(() => false))
    if (!busy && titleReady) {
      uploadLog(PLATFORM, 'processing wait', 'черновик с видео, поле названия готово')
      return
    }
    await humanDelay(350, 550)
  }
  throw new Error('Pinterest не закончил обработку видео за 3 минуты. Площадка пропущена, очередь идёт дальше.')
}

async function waitPinDraftSaved(page: Page, timeout = 90_000): Promise<void> {
  uploadLog(PLATFORM, 'save', 'ждём saving-status-saved / Changes stored')
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const saved = (await page.locator('[data-test-id="saving-status-saved"]').count().catch(() => 0)) > 0
    const savingEl = (await page.locator('[data-test-id="saving-status-saving"]').count().catch(() => 0)) > 0
    const savingText =
      (await page.getByText(/^Saving(\.\.\.|…)?$/i).isVisible().catch(() => false)) ||
      (await page.getByText(/^Сохран(ение|яем|яется)/i).isVisible().catch(() => false))
    if (saved && !savingEl && !savingText) {
      uploadLog(PLATFORM, 'save', 'черновик сохранён (saving-status-saved)')
      await humanDelay(250, 450)
      return
    }
    await humanDelay(300, 500)
  }
  uploadLog(PLATFORM, 'save', 'таймаут Saved, всё равно жмём Publish')
}

async function pinLooksPublished(page: Page): Promise<boolean> {
  if ((await page.locator('[data-test-id="saving-status-created"]').count().catch(() => 0)) > 0) {
    return true
  }
  const toast = page.getByText(PUBLISHED_RE).first()
  if (await toast.isVisible().catch(() => false)) return true
  const wrapGone = (await publishWrap(page).count().catch(() => 0)) === 0
  const emptyCanvas = await inputAcceptsVideo(page)
  return wrapGone && emptyCanvas
}

async function clickPinterestPublish(page: Page): Promise<string | undefined> {
  await waitPinDraftSaved(page)
  const wrap = publishWrap(page)
  const btn = publishButton(page)
  await waitUntilEnabled(btn, 60_000).catch(() => undefined)
  uploadLog(PLATFORM, 'publish', 'native click Publish / Опубликовать (storyboard-creation-nav-done)')
  await wrap.evaluate((el) => {
    const button = el.querySelector('button') || el
    ;(button as HTMLElement).click()
  })
  await humanDelay(400, 800)

  const deadline = Date.now() + 90_000
  let sawPublishing = false
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await closeExtraWindows(page)
    if ((await page.locator('[data-test-id="saving-status-publishing"]').count().catch(() => 0)) > 0) {
      if (!sawPublishing) {
        sawPublishing = true
        uploadLog(PLATFORM, 'publish', 'saving-status-publishing — пин уходит')
      }
    }
    const pinUrl = await resolvePublishedUrl(page, PLATFORM, page.url())
    if (pinUrl) {
      uploadLog(PLATFORM, 'publish', `пин опубликован ${pinUrl}`)
      return pinUrl
    }
    if (await pinLooksPublished(page)) {
      uploadLog(PLATFORM, 'publish', 'saving-status-created / тост: пин опубликован')
      return await waitForPublicUrl(page, PLATFORM, 8_000)
    }
    const dialogPub = page
      .locator('[role="dialog"] button, [data-test-id*="confirm"] button')
      .filter({ hasText: /^(publish|опубликовать)$/i })
      .first()
    if (await dialogPub.isVisible().catch(() => false)) {
      uploadLog(PLATFORM, 'publish', 'подтверждение в диалоге')
      await dialogPub.evaluate((el) => (el as HTMLElement).click())
    }
    await humanDelay(400, 700)
  }

  if (sawPublishing) {
    uploadLog(PLATFORM, 'publish', 'Publishing был, тост мог закрыться — ищем ссылку')
    return await waitForPublicUrl(page, PLATFORM, 8_000)
  }

  throw new Error(
    'Pinterest не опубликовал пин: native click Publish не дал saving-status-publishing / «Your Pin has been published».'
  )
}

async function pickBoardIfNeeded(page: Page): Promise<void> {
  const board = page
    .locator(
      '[data-test-id="board-dropdown-select-button"], [data-test-id="storyboard-selector-board"] button, [data-test-id="board-dropdown"] button'
    )
    .first()
  if (!(await board.isVisible().catch(() => false))) return
  const label = ((await board.innerText().catch(() => '')) || '').trim()
  if (label && !/выберите|select a board|доск/i.test(label)) {
    uploadLog(PLATFORM, 'board', `уже: ${label.slice(0, 80)}`)
    return
  }
  await board.click({ timeout: 4000 }).catch(() => undefined)
  await humanDelay(200, 400)
  const option = page
    .locator('[data-test-id="board-row"], [role="option"], [data-test-id="board-dropdown"] [role="listitem"]')
    .first()
  if (await option.isVisible().catch(() => false)) {
    const name = (await option.innerText().catch(() => '')).trim().slice(0, 80)
    await option.click({ timeout: 4000 })
    uploadLog(PLATFORM, 'board', name || 'первая доска')
  }
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  try {
    uploadLog(PLATFORM, 'upload', 'публикация только через pin-creation-tool, хаб не трогаем')
    await gotoVideoBuilder(page)
    await attachPinterestVideo(page, payload.videoPath)
    await waitPinMediaReady(page)

    const titleBox = page.locator('#storyboard-selector-title').first()
    await titleBox.waitFor({ state: 'visible', timeout: 60_000 }).catch(() => undefined)
    await waitUntilEnabled(titleBox, 60_000).catch(() => undefined)
    await fillFirst(page, TITLE_FIELDS, payload.title, 12_000).catch((error) =>
      uploadLogError(PLATFORM, 'title', error)
    )
    uploadLog(PLATFORM, 'title', payload.title)

    if (payload.description) {
      await fillFirst(page, DESC_FIELDS, payload.description, 8000).catch(() => undefined)
      uploadLog(PLATFORM, 'description', 'заполнено')
    }

    await pickBoardIfNeeded(page)

    const opts = payload.options as PinterestPublishOptions
    if (opts.link) {
      await fillFirst(
        page,
        [
          '[data-test-id="storyboard-selector-link"] input',
          '[data-test-id="storyboard-selector-link"] textarea',
          '#WebsiteField',
          'input[type="url"]'
        ],
        opts.link,
        4000
      ).catch(() => undefined)
    }
    await setToggle(page, ['#CommentSwitch'], opts.comments)
    if (typeof opts.aiGenerated === 'boolean') {
      await setToggle(
        page,
        ['[data-test-id="ai-disclosure-switch"] input', 'input[id*="pin-draft-ai-disclosure"]'],
        opts.aiGenerated
      )
    }
    await closeExtraWindows(page)

    if (payload.dryRun) {
      await waitPinDraftSaved(page).catch(() => undefined)
      uploadLog(PLATFORM, 'publish', 'dryRun — Publish не нажимаем')
      return page.url()
    }

    const pinUrl = await clickPinterestPublish(page)
    uploadLog(PLATFORM, 'done', pinUrl || page.url())
    return pinUrl || page.url()
  } catch (error) {
    uploadLogError(PLATFORM, 'upload', error)
    throw error
  }
}

export const pinterestAdapter: PlatformAdapter = { loginCheck, upload }
