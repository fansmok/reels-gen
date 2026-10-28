import type { Locator, Page } from 'playwright-core'
import { setTimeout as sleep } from 'node:timers/promises'
import {
  clickIfPresent,
  confirmCropDialog,
  dismissNuisances,
  fillFirst,
  humanDelay,
  looksLoggedOut,
  safeGoto,
  setToggle,
  waitForPublicUrl
} from './helpers'
import {
  DEFAULT_RUTUBE_CATEGORY,
  RUTUBE_CATEGORY_NAMES,
  type RutubePublishOptions
} from '../../shared/publish-options'
import type { PlatformAdapter, UploadPayload } from './types'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'

const PLATFORM = 'rutube'
const STUDIO = 'https://studio.rutube.ru/?period=7_days&tab=main'
const PROCESS_MS = 180_000
const HELP_URL_RE = /academy|for_creators|\/info\/faq|support|help|partners@|invalid-content/i

function editor(page: Page): Locator {
  return page.locator('[data-testid="video-editor-layout"]').first()
}

function publishButton(page: Page): Locator {
  return page.locator('button[type="submit"]').filter({ hasText: /^Опубликовать$/i }).last()
}

function videoFileInput(page: Page): Locator {
  return page.locator('input[type="file"][accept*=".mp4"], input[type="file"][accept*="mp4"]').first()
}

function imageFileInput(page: Page): Locator {
  return page.locator(
    'input[type="file"][accept*="image"], input[type="file"][accept*="png"], input[type="file"][accept*="jpg"], input[type="file"][accept*="jpeg"]'
  )
}

async function closeExtraPages(page: Page): Promise<void> {
  for (const extra of page.context().pages()) {
    if (extra === page || extra.isClosed()) continue
    const url = extra.url()
    if (!HELP_URL_RE.test(url)) continue
    uploadLogWindow(PLATFORM, url, 'closed')
    await extra.close().catch(() => undefined)
  }
}

async function dismissRutubePopups(page: Page, keepEditor: boolean): Promise<void> {
  if (page.isClosed()) return
  await closeExtraPages(page)
  await dismissNuisances(page)
  if (!keepEditor) await clickIfPresent(page, ['button[aria-label="closeIcon"]'])
  const subtitlesFail = page.getByText(/не получилось сгенерировать субтитры/i).first()
  if (await subtitlesFail.isVisible().catch(() => false)) {
    uploadLog(PLATFORM, 'dismiss', 'тост субтитров')
    await page.keyboard.press('Escape').catch(() => undefined)
  }

  const extras = page.getByRole('dialog').filter({
    hasText: /академи|rutube academy|присоединиться|новости студии|черновик|новый\s+\d+\s+минут/i
  })
  const extraCount = Math.min(await extras.count().catch(() => 0), 6)
  for (let i = 0; i < extraCount; i++) {
    const dialog = extras.nth(i)
    if (!(await dialog.isVisible().catch(() => false))) continue
    const isUpload =
      (await dialog.locator('[data-testid="video-editor-layout"], [data-testid="uploadVideo"]').count().catch(() => 0)) >
        0 ||
      (await dialog.getByRole('button', { name: /выбрать файлы|^опубликовать$/i }).count().catch(() => 0)) > 0
    if (isUpload) continue
    const snippet = (await dialog.innerText().catch(() => '')).replace(/\s+/g, ' ').trim().slice(0, 80)
    uploadLog(PLATFORM, 'dismiss', snippet || 'лишний диалог')
    await dialog
      .locator('button[aria-label="Закрыть"], button[aria-label="close"]')
      .first()
      .click({ timeout: 1500 })
      .catch(() => undefined)
    await dialog.getByRole('button', { name: /^закрыть$/i }).first().click({ timeout: 1500 }).catch(() => undefined)
  }
}

async function waitStudioReady(page: Page): Promise<void> {
  await page.locator('[data-testid="global-loader"]').waitFor({ state: 'hidden', timeout: 45_000 }).catch(() => undefined)
  await page.locator('[data-testid="header-add-button"], button:has-text("Добавить")').first().waitFor({
    state: 'visible',
    timeout: 45_000
  })
}

async function loginCheck(page: Page): Promise<boolean> {
  await safeGoto(page, STUDIO)
  await waitStudioReady(page)
  await dismissRutubePopups(page, false)
  if (looksLoggedOut(page.url())) return false
  return !page.url().includes('auth') && !page.url().includes('login')
}

async function processingPercentVisible(page: Page): Promise<boolean> {
  return page.getByText(/^Обработка\s+\d+\s*%/).first().isVisible().catch(() => false)
}

async function waitRutubeProcessed(page: Page): Promise<void> {
  const publish = publishButton(page)
  await publish.waitFor({ state: 'visible', timeout: 90_000 })
  uploadLog(PLATFORM, 'processing', 'Опубликовать видна, ждём enabled (до 3 мин)')
  const deadline = Date.now() + PROCESS_MS
  let lastLog = 0
  let sawEnabled = false
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    const disabled = await publish.isDisabled().catch(() => true)
    const aria = await publish.getAttribute('aria-disabled').catch(() => null)
    const enabled = !disabled && aria !== 'true'
    const processing = await processingPercentVisible(page)
    if (enabled && !sawEnabled) {
      uploadLog(PLATFORM, 'processing', 'Опубликовать активна')
      sawEnabled = true
    }
    if (enabled && !processing) {
      uploadLog(PLATFORM, 'processing', 'обработка в UI завершена')
      return
    }
    if (Date.now() - lastLog > 15_000) {
      uploadLog(PLATFORM, 'processing', enabled ? 'кнопка активна, в UI ещё «Обработка %»' : 'видео ещё обрабатывается')
      lastLog = Date.now()
    }
    await dismissRutubePopups(page, true)
    await sleep(400)
  }
  if (sawEnabled) {
    uploadLog(PLATFORM, 'processing', '3 мин истекли, Опубликовать уже enabled — идём дальше')
    return
  }
  const err = new Error('Rutube всё ещё обрабатывает видео. «Опубликовать» неактивна больше 3 минут.')
  uploadLogError(PLATFORM, 'processing', err)
  throw err
}

async function attachRutubeVideo(page: Page, videoPath: string): Promise<void> {
  const input = videoFileInput(page)
  try {
    await input.waitFor({ state: 'attached', timeout: 20_000 })
    const accept = (await input.getAttribute('accept')) || ''
    if (/image|png|jpe?g|webp/i.test(accept) && !/\.mp4|video/i.test(accept)) {
      throw new Error(`видео-input оказался картинкой: ${accept}`)
    }
    await input.setInputFiles(videoPath)
    uploadLog(PLATFORM, 'file', `видео через input accept=${accept}`)
    return
  } catch (error) {
    uploadLog(PLATFORM, 'file', `input mp4 не сработал: ${error instanceof Error ? error.message : String(error)}`)
  }

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 20_000 })
  const pick = page.getByRole('button', { name: /выбрать файлы/i }).first()
  await pick.waitFor({ state: 'visible', timeout: 12_000 })
  await pick.click({ timeout: 8000 })
  await (await chooserPromise).setFiles(videoPath)
  uploadLog(PLATFORM, 'file', 'видео через filechooser «Выбрать файлы»')
}

async function clickUploadOwnCover(root: Locator): Promise<boolean> {
  const candidates = [
    root.locator('[class*="cover-uploader"]').getByText('Загрузить свою', { exact: true }),
    root.locator('p').filter({ hasText: /^Загрузить свою$/ }),
    root.getByText('Загрузить свою', { exact: true })
  ]
  for (const loc of candidates) {
    const el = loc.first()
    if (!(await el.isVisible().catch(() => false))) continue
    await el.scrollIntoViewIfNeeded().catch(() => undefined)
    await el.click({ timeout: 4000 }).catch(async () => el.click({ force: true, timeout: 2000 }))
    return true
  }
  return false
}

async function attachRutubeCover(page: Page, coverPath: string): Promise<void> {
  const root = (await editor(page).count().catch(() => 0)) > 0 ? editor(page) : page.locator('body')
  uploadLog(PLATFORM, 'cover', 'секция Обложка → p «Загрузить свою» в [class*=cover-uploader]')

  const heading = root.locator('span').filter({ hasText: /^Обложка$/ }).first()
  await heading.waitFor({ state: 'visible', timeout: 20_000 }).catch(() => undefined)
  await heading.scrollIntoViewIfNeeded().catch(() => undefined)
  await humanDelay(150, 300)

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 12_000 }).catch(() => null)
  const own = await clickUploadOwnCover(root)
  if (!own) {
    const err = new Error('Не найдена «Загрузить свою» в секции Обложка')
    uploadLogError(PLATFORM, 'cover', err)
    throw err
  }
  uploadLog(PLATFORM, 'cover', 'клик «Загрузить свою», кадр из видео не трогаем')

  const chooser = await chooserPromise
  if (chooser) {
    await chooser.setFiles(coverPath)
    uploadLog(PLATFORM, 'cover', 'PNG через filechooser')
  } else {
    const image = imageFileInput(page)
    if ((await image.count()) > 0) {
      await image.last().setInputFiles(coverPath)
      uploadLog(PLATFORM, 'cover', 'PNG через image-input (запасной путь)')
    } else {
      const err = new Error('После «Загрузить свою» не открылся filechooser обложки')
      uploadLogError(PLATFORM, 'cover', err)
      throw err
    }
  }

  await confirmCropDialog(page)
  const done = page.getByRole('button', { name: /^готово$/i }).last()
  if (await done.isVisible().catch(() => false)) {
    await done.click({ timeout: 4000 }).catch(() => undefined)
    uploadLog(PLATFORM, 'cover', 'кроп: Готово')
  }
}

function categoryAlreadySelected(text: string, category: string): boolean {
  const compact = text.replace(/\s+/g, ' ')
  return compact.includes(category) && !/выберите категори/i.test(compact)
}

async function selectRutubeCategory(page: Page, category: string): Promise<void> {
  const name = RUTUBE_CATEGORY_NAMES.includes(category as (typeof RUTUBE_CATEGORY_NAMES)[number])
    ? category
    : DEFAULT_RUTUBE_CATEGORY
  const field = page.locator('[data-control-name="category"]').first()
  await field.waitFor({ state: 'visible', timeout: 20_000 })
  await field.scrollIntoViewIfNeeded().catch(() => undefined)
  uploadLog(PLATFORM, 'category', name)

  const current = (await field.innerText().catch(() => '')).replace(/\s+/g, ' ')
  if (categoryAlreadySelected(current, name)) {
    uploadLog(PLATFORM, 'category', `уже выбрано: ${name}`)
    return
  }

  const combo = field.locator('[role="combobox"]').first()
  await combo.click({ timeout: 5000 }).catch(async () => combo.click({ force: true, timeout: 3000 }))
  await humanDelay(200, 400)

  const input = field.locator('input[type="text"]').first()
  if ((await input.count().catch(() => 0)) > 0) {
    await input.fill(name).catch(async () => {
      await input.click({ force: true })
      const selectAll = process.platform === 'darwin' ? 'Meta+A' : 'Control+A'
      await page.keyboard.press(selectAll).catch(() => undefined)
      await page.keyboard.type(name, { delay: 20 })
    })
    await humanDelay(150, 280)
    await page.keyboard.press('Enter').catch(() => undefined)
    await humanDelay(200, 350)
  }

  const afterFill = (await field.innerText().catch(() => '')).replace(/\s+/g, ' ')
  if (!categoryAlreadySelected(afterFill, name)) {
    const option = page.getByRole('option', { name, exact: true }).first()
    if (await option.isVisible().catch(() => false)) {
      await option.click({ force: true, timeout: 4000 })
    } else {
      const listed = page
        .locator('[role="listbox"] [role="option"], [role="listbox"] li')
        .filter({ hasText: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) })
        .first()
      if (await listed.isVisible().catch(() => false)) {
        await listed.click({ force: true, timeout: 4000 })
      }
    }
    await humanDelay(200, 350)
  }

  const after = (await field.innerText().catch(() => '')).replace(/\s+/g, ' ')
  if (!categoryAlreadySelected(after, name)) {
    const err = new Error(`Не удалось выбрать категорию «${name}». Без категории Rutube не публикует.`)
    uploadLogError(PLATFORM, 'category', err)
    throw err
  }
  uploadLog(PLATFORM, 'category', `выбрано «${name}»`)
}

async function clickRutubePublish(page: Page, dryRun?: boolean): Promise<void> {
  await waitRutubeProcessed(page)
  if (dryRun) {
    uploadLog(PLATFORM, 'publish', 'dryRun — не жмём Опубликовать')
    return
  }
  const publish = publishButton(page)
  uploadLog(PLATFORM, 'publish', 'клик button[type=submit] Опубликовать')
  await publish.click({ timeout: 8000 }).catch(async () => publish.click({ force: true, timeout: 5000 }))
}

async function openUploadModal(page: Page): Promise<void> {
  uploadLog(PLATFORM, 'add', 'Добавить')
  const added = await clickIfPresent(page, ['[data-testid="header-add-button"]'])
  if (!added) {
    await page.getByRole('button', { name: /^добавить$/i }).first().click({ timeout: 8000 })
  }
  const uploadVideo = page.locator('[data-testid="uploadVideo"]')
  await uploadVideo.waitFor({ state: 'visible', timeout: 10_000 })
  uploadLog(PLATFORM, 'uploadVideo', 'Загрузить видео или Shorts')
  await uploadVideo.click({ timeout: 5000 })
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  try {
    uploadLog(PLATFORM, 'goto', STUDIO)
    await safeGoto(page, STUDIO)
    await waitStudioReady(page)
    await dismissRutubePopups(page, false)
    await page.keyboard.press('Escape').catch(() => undefined)

    await openUploadModal(page)

    await attachRutubeVideo(page, payload.videoPath)

    const layout = editor(page)
    await layout.waitFor({ state: 'visible', timeout: 90_000 }).catch(() => undefined)
    const titleInput = page.locator('input[name="title"]').first()
    await titleInput.waitFor({ state: 'visible', timeout: 90_000 })
    uploadLog(PLATFORM, 'form', 'модалка video-editor-layout поверх studio')

    await fillFirst(
      page,
      ['input[name="title"]', 'input[placeholder*="назван" i]', 'textarea[name="title"]'],
      payload.title,
      20_000
    ).catch((error) => uploadLogError(PLATFORM, 'title', error))

    if (payload.description) {
      await fillFirst(
        page,
        ['textarea[name="description"]', 'textarea[placeholder*="описан" i]'],
        payload.description,
        8000
      ).catch((error) => uploadLogError(PLATFORM, 'description', error))
    }

    const opts = (payload.options || {}) as RutubePublishOptions
    await selectRutubeCategory(page, opts.category || DEFAULT_RUTUBE_CATEGORY)

    await waitRutubeProcessed(page)
    await dismissRutubePopups(page, true)

    if (payload.coverPath) {
      await attachRutubeCover(page, payload.coverPath)
    }

    await setToggle(page, ['input[name="withComments"]'], opts.comments)
    await setToggle(page, ['input[name="isAdult"]'], opts.adult)

    await clickRutubePublish(page, payload.dryRun)
    if (!payload.dryRun) await humanDelay(800, 1400)
    const url = payload.dryRun ? page.url() : await waitForPublicUrl(page, PLATFORM, 40_000)
    uploadLog(PLATFORM, 'done', url || page.url())
    return url || page.url()
  } catch (error) {
    uploadLogError(PLATFORM, 'upload', error)
    throw error
  }
}

export const rutubeAdapter: PlatformAdapter = { loginCheck, upload }
