import type { Locator, Page } from 'playwright-core'
import {
  clickFirstOptional,
  dismissNuisances,
  fillFirst,
  humanDelay,
  looksLoggedOut,
  safeGoto,
  setToggle,
  waitUntilEnabled
} from './helpers'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'
import { vkClipsUploadUrl, type VkPublishOptions } from '../../shared/publish-options'
import type { PlatformAdapter, UploadPayload } from './types'

const PLATFORM = 'vk'

/** На ленте клипов кнопка открытия модалки — «Опубликовать», не «Добавить клип». */
const ADD_CLIP = '[data-testid="clips-publish-button"]'
const DROPZONE = '[data-testid="video_upload_modal"]'
const NEW_CLIP_DIALOG = '[data-testid="modalbox"][aria-label="Новый клип"]'
const VIDEO_INPUT = '[data-testid="video_upload_select_file"]'
const FORM = '[data-testid="video_upload_clip_form"]'
const STATUS = '[data-testid="clips-upload-status"]'
const DESCRIPTION = '[data-testid="clips-upload-description"]'
const COVER_INPUT = 'input[aria-label="Выбрать обложку"]'
const COVER_INPUT_FALLBACK = 'input[aria-label*="облож" i][accept*="image"]'
const PUBLISH_BTN = '[data-testid="clips-uploadForm-publish-button"]'
const DELETE_BTN = '[data-testid="clips-uploadForm-delete-button"]'

const READY_RE = /клип загружен и обработан|загружен и обработан/i
const COVER_LOCKED_RE = /выбор обложки будет доступен после обработки/i
const BUSY_RE = /загружено\s*\d+\s*%|загружается|загрузка клипа|обработк|uploading|processing|осталось|идёт загруз/i
const PUBLISHING_RE = /публикуем|публикация клипа|идёт публикация|идет публикация|отправляем клип|publishing/i
const PUBLISHED_RE = /клип опубликован|успешно опубликован|клип выложен|публикация прошла|опубликовано успешно/i
const PUBLISH_FAIL_RE = /не удалось опубликовать|ошибка публикации|не получилось опубликовать/i

const NOISE_URL =
  /ads\.vk|vkads|\/ads(?:\/|$|\?)|help\.vk|\/support|\/faq|\/help(?:\/|$|\?)|target\.(my\.com|vk)|business\.vk|\/promo|advert|academy|calendly/i
const NOISE_TITLE = /реклам|помощ|справк|vk ads|поддержк|help centre|help center/i

const watchedContexts = new WeakSet<object>()
const notedWindows = new WeakSet<Page>()

function isNoiseUrl(url: string): boolean {
  const u = url.toLowerCase()
  if (!u || u === 'about:blank' || u.startsWith('chrome://')) return false
  if (/vk\.(ru|com)\/clips/.test(u) || /id\.vk\./.test(u)) return false
  return NOISE_URL.test(u)
}

async function closeIfNoise(main: Page, extra: Page, waitLoad = true): Promise<void> {
  if (extra === main || extra.isClosed()) return
  if (waitLoad) {
    await extra.waitForLoadState('domcontentloaded').catch(() => undefined)
    await humanDelay(200, 400)
  }
  if (extra.isClosed() || extra === main) return
  const url = extra.url()
  const title = await extra.title().catch(() => '')
  if (isNoiseUrl(url) || NOISE_TITLE.test(title)) {
    uploadLogWindow(PLATFORM, url || title, 'closed')
    await extra.close().catch(() => undefined)
    return
  }
  if (url && url !== 'about:blank' && !notedWindows.has(extra)) {
    notedWindows.add(extra)
    uploadLogWindow(PLATFORM, url, 'opened')
  }
}

function watchExtraPages(main: Page): void {
  const ctx = main.context()
  if (watchedContexts.has(ctx)) return
  watchedContexts.add(ctx)
  ctx.on('page', (extra) => {
    void closeIfNoise(main, extra)
  })
}

async function closeExtraPages(main: Page): Promise<void> {
  for (const extra of main.context().pages()) {
    await closeIfNoise(main, extra, false)
  }
}

async function formRoot(page: Page): Promise<Locator> {
  const form = page.locator(FORM).first()
  if (await form.isVisible().catch(() => false)) return form
  const drop = page.locator(DROPZONE).first()
  if (await drop.isVisible().catch(() => false)) return drop
  const dialog = page.locator(NEW_CLIP_DIALOG).first()
  if (await dialog.isVisible().catch(() => false)) return dialog
  return page.locator('body')
}

/** Чужие слои (реклама/помощь/меню профиля). Не кликать оверлей модалки «Новый клип». */
async function dismissOtherLayers(page: Page): Promise<void> {
  const layers = page.locator('[data-testid="modalbox"], [role="dialog"], .box_layout, [class*="PopoutWrapper"]')
  const total = Math.min(await layers.count().catch(() => 0), 8)
  for (let i = 0; i < total; i++) {
    const layer = layers.nth(i)
    if (!(await layer.isVisible().catch(() => false))) continue
    const keep =
      (await layer.locator(`${DROPZONE}, ${VIDEO_INPUT}, ${FORM}, ${PUBLISH_BTN}`).count().catch(() => 0)) > 0 ||
      ((await layer.getAttribute('aria-label').catch(() => '')) || '').includes('Новый клип')
    if (keep) continue
    const blob = (await layer.innerText().catch(() => '')).slice(0, 400)
    if (!NOISE_TITLE.test(blob) && !/подсказк|новинк|попробуйте|уведомлен|аккаунт/i.test(blob)) continue
    const close = layer.getByRole('button', { name: /^(закрыть|close)$/i }).first()
    if (!(await close.isVisible().catch(() => false))) continue
    uploadLog(PLATFORM, 'dismiss-layer', blob.slice(0, 80))
    await close.click({ timeout: 1500 }).catch(() => undefined)
    await humanDelay(150, 280)
  }
}

async function openClipForm(page: Page): Promise<Locator> {
  if (await page.locator(FORM).isVisible().catch(() => false)) return page.locator(FORM).first()
  if (await page.locator(`${DROPZONE}, ${VIDEO_INPUT}`).first().isVisible().catch(() => false)) {
    return formRoot(page)
  }

  uploadLog(PLATFORM, 'add-clip', `${ADD_CLIP} (текст «Опубликовать»)`)
  const started = await clickFirstOptional(page, [ADD_CLIP], 10_000)
  if (!started) throw new Error('Не найдена кнопка нового клипа VK (clips-publish-button)')

  await page
    .locator(`${NEW_CLIP_DIALOG}, ${DROPZONE}, ${VIDEO_INPUT}`)
    .first()
    .waitFor({ state: 'attached', timeout: 20_000 })
  const root = await formRoot(page)
  if ((await root.locator(VIDEO_INPUT).count().catch(() => 0)) === 0) {
    throw new Error('Не открылась модалка «Новый клип»')
  }
  uploadLog(PLATFORM, 'modal', 'video_upload_modal / Новый клип')
  return root
}

async function attachVideo(root: Locator, videoPath: string): Promise<void> {
  uploadLog(PLATFORM, 'video', VIDEO_INPUT)
  const input = root.locator(VIDEO_INPUT).first()
  await input.waitFor({ state: 'attached', timeout: 15_000 })
  await input.setInputFiles(videoPath)
  uploadLog(PLATFORM, 'video', 'setInputFiles video_upload_select_file')
}

async function waitClipReady(page: Page): Promise<Locator> {
  uploadLog(PLATFORM, 'wait-processing', 'ждём video_upload_clip_form и «Клип загружен и обработан»')
  const form = page.locator(FORM).first()
  await form.waitFor({ state: 'visible', timeout: 180_000 })
  const status = form.locator(STATUS).first()
  const publish = form.locator(PUBLISH_BTN).first()
  const deadline = Date.now() + 180_000
  let last = ''
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await closeExtraPages(page)
    await dismissOtherLayers(page)

    const statusText = (await status.innerText().catch(() => '')).replace(/\s+/g, ' ').trim()
    const formText = (await form.innerText().catch(() => '')).replace(/\s+/g, ' ')
    const busy = (BUSY_RE.test(statusText) || BUSY_RE.test(formText) || COVER_LOCKED_RE.test(formText)) && !READY_RE.test(statusText)
    if ((statusText || formText.slice(0, 80)) !== last) {
      last = statusText || formText.slice(0, 80)
      uploadLog(PLATFORM, 'wait-processing', last)
    }
    const coverReady = (await form.locator(`${COVER_INPUT}, ${COVER_INPUT_FALLBACK}`).count().catch(() => 0)) > 0
    const disabled = await publish.isDisabled().catch(() => true)
    const aria = await publish.getAttribute('aria-disabled').catch(() => null)
    if (READY_RE.test(statusText) && coverReady && !disabled && aria !== 'true' && !COVER_LOCKED_RE.test(formText)) {
      uploadLog(PLATFORM, 'wait-processing', 'клип обработан, обложка доступна')
      return form
    }
    if (!busy && coverReady && !disabled && aria !== 'true' && READY_RE.test(statusText + ' ' + formText)) {
      uploadLog(PLATFORM, 'wait-processing', 'форма готова')
      return form
    }
    await humanDelay(400, 700)
  }
  await waitUntilEnabled(publish, 8_000)
  if (COVER_LOCKED_RE.test(await form.innerText().catch(() => ''))) {
    throw new Error('VK ещё обрабатывает клип — обложка недоступна')
  }
  uploadLog(PLATFORM, 'wait-processing', 'таймаут цикла, кнопка опубликовать enabled')
  return form
}

async function fillDescription(page: Page, form: Locator, text: string): Promise<void> {
  uploadLog(PLATFORM, 'description', DESCRIPTION)
  const field = form.locator(DESCRIPTION).first()
  await field.waitFor({ state: 'visible', timeout: 20_000 })
  try {
    await field.click({ timeout: 4000 })
    await field.fill(text)
  } catch {
    await fillFirst(page, [DESCRIPTION, `${FORM} textarea`], text)
  }
}

async function attachCover(form: Locator, coverPath?: string): Promise<void> {
  if (!coverPath) return
  uploadLog(PLATFORM, 'cover', COVER_INPUT)
  const locked = COVER_LOCKED_RE.test(await form.innerText().catch(() => ''))
  if (locked) throw new Error('Нельзя ставить обложку до конца обработки клипа')
  const input = form.locator(`${COVER_INPUT}, ${COVER_INPUT_FALLBACK}`).first()
  await input.waitFor({ state: 'attached', timeout: 20_000 })
  await input.setInputFiles(coverPath)
  uploadLog(PLATFORM, 'cover', 'setInputFiles aria «Выбрать обложку» (image/png,jpeg)')
}

async function applyOptions(page: Page, opts: VkPublishOptions): Promise<void> {
  uploadLog(PLATFORM, 'options', 'свитчи на video_upload_clip_form, без «Развернуть»')
  await setToggle(page, [`${FORM} [data-testid="clips-upload-privacy-comments"]`], opts.comments)
  await setToggle(page, [`${FORM} [data-testid="clips-upload-wallpost"]`], opts.wallPost)
  await setToggle(page, [`${FORM} [data-testid="clips-upload-duets"]`], opts.duets)
  await setToggle(page, [`${FORM} [data-testid="clips-upload-publish-story"]`], opts.publishStory)
}

async function publishClip(form: Locator): Promise<void> {
  uploadLog(PLATFORM, 'publish', PUBLISH_BTN)
  const publish = form.locator(PUBLISH_BTN).first()
  await waitUntilEnabled(publish, 30_000)
  const handle = await publish.elementHandle().catch(() => null)
  if (handle) {
    uploadLog(PLATFORM, 'publish', 'native click Опубликовать')
    await handle.evaluate((el) => (el as HTMLElement).click())
  } else {
    await publish.click({ timeout: 8_000 })
  }
}

function isUploadProgressUrl(url: string): boolean {
  return /\/clips\/upload/i.test(url)
}

function isClipWatchUrl(url: string): boolean {
  return /vk\.(ru|com)\/clip-?\d+_\d+/i.test(url) || /vk\.(ru|com)\/video-?\d+_\d+/i.test(url)
}

async function collectClipHrefs(page: Page): Promise<string[]> {
  return page
    .locator('a[href]')
    .evaluateAll((els) =>
      [
        ...new Set(
          els
            .map((el) => (el as HTMLAnchorElement).href.split('?')[0])
            .filter((href) => /\/clip-?\d+_\d+/i.test(href) && !/\/clips\//i.test(href))
        )
      ]
    )
    .catch(() => [] as string[])
}

async function waitClipPublished(page: Page, known: Set<string>): Promise<string | undefined> {
  uploadLog(PLATFORM, 'publish', 'ждём ссылку на клип, Chrome не закрываем')
  const started = Date.now()
  const deadline = started + 300_000
  let lastNote = 0
  let lastRetry = 0
  let retried = 0

  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await closeExtraPages(page)
    await dismissOtherLayers(page)

    const url = page.url().split('?')[0]
    if (await page.getByText(PUBLISH_FAIL_RE).first().isVisible().catch(() => false)) {
      throw new Error('VK не смог опубликовать клип')
    }

    const hrefs = await collectClipHrefs(page)
    const fresh = hrefs.find((href) => !known.has(href))
    if (fresh) {
      uploadLog(PLATFORM, 'publish', `клип опубликован: ${fresh}`)
      await humanDelay(600, 1000)
      return fresh
    }
    if (isClipWatchUrl(url) && !known.has(url)) {
      uploadLog(PLATFORM, 'publish', `клип опубликован: ${url}`)
      await humanDelay(600, 1000)
      return url
    }

    const formVisible = await page.locator(FORM).isVisible().catch(() => false)
    const formText = formVisible ? await page.locator(FORM).innerText().catch(() => '') : ''
    const publishing =
      isUploadProgressUrl(url) ||
      PUBLISHING_RE.test(formText) ||
      (await page.getByText(PUBLISHED_RE).first().isVisible().catch(() => false))
    if (publishing || !formVisible) {
      if (Date.now() - lastNote > 4000) {
        lastNote = Date.now()
        uploadLog(PLATFORM, 'publish', `публикация… ${url}`)
      }
    }

    if (
      formVisible &&
      !publishing &&
      Date.now() - started > 4000 &&
      retried < 3 &&
      Date.now() - lastRetry > 4000
    ) {
      retried += 1
      lastRetry = Date.now()
      uploadLog(PLATFORM, 'publish', `повторный клик Опубликовать (${retried})`)
      await publishClip(page.locator(FORM).first())
    }

    await humanDelay(400, 700)
  }

  if (!(await page.locator(FORM).isVisible().catch(() => false))) {
    uploadLog(PLATFORM, 'publish', 'форма закрылась, ссылку на клип не нашли')
    return undefined
  }

  throw new Error(
    'VK не закончил публикацию клипа. Не закрывайте окно, пока не появится ссылка на клип.'
  )
}

async function loginCheck(page: Page): Promise<boolean> {
  uploadLog(PLATFORM, 'login-check')
  watchExtraPages(page)
  await safeGoto(page, 'https://vk.ru')
  await closeExtraPages(page)
  if (looksLoggedOut(page.url()) || page.url().includes('id.vk.com')) return false
  const feed = page.locator('#side_bar, [data-testid="leftmenu"], #l_pr, a[href*="/clips"]').first()
  return (await feed.count()) > 0
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  watchExtraPages(page)
  try {
    const opts = (payload.options || {}) as VkPublishOptions
    const clipsUrl = vkClipsUploadUrl(opts.communityUrl)
    uploadLog(PLATFORM, 'goto', clipsUrl)
    await safeGoto(page, clipsUrl)
    if (opts.communityUrl?.trim() && !/vk\.(ru|com)\/clips\/.+/i.test(page.url())) {
      throw new Error(
        'Не открылась страница клипов сообщества. Проверьте ссылку в настройках и права администратора.'
      )
    }
    await dismissNuisances(page)
    await closeExtraPages(page)
    await dismissOtherLayers(page)

    const dropzone = await openClipForm(page)
    await humanDelay()
    await closeExtraPages(page)

    await attachVideo(dropzone, payload.videoPath)
    const form = await waitClipReady(page)
    await humanDelay(400, 800)

    if (payload.description?.trim()) {
      await fillDescription(page, form, payload.description.trim())
    }
    await attachCover(form, payload.coverPath)
    await applyOptions(page, opts)
    await humanDelay()

    if (payload.dryRun) {
      uploadLog(PLATFORM, 'dry-run', `публикация пропущена, не жмём ${PUBLISH_BTN} / ${DELETE_BTN}`)
      return page.url()
    }
    const knownClips = new Set(await collectClipHrefs(page))
    await publishClip(form)
    const url = await waitClipPublished(page, knownClips)
    uploadLog(PLATFORM, 'done', url || page.url())
    return url
  } catch (error) {
    uploadLogError(PLATFORM, 'upload', error)
    throw error
  }
}

export const vkAdapter: PlatformAdapter = { loginCheck, upload }
