import type { Locator, Page } from 'playwright-core'
import { setTimeout as sleep } from 'node:timers/promises'
import {
  attachFile,
  clickByName,
  clickFirstOptional,
  clickIfPresent,
  clickText,
  dismissNuisances,
  fillFirst,
  humanDelay,
  I18N,
  looksLoggedOut,
  safeGoto,
  waitForPublicUrl,
  waitUntilEnabled
} from './helpers'
import {
  DZEN_COMMENT_AUDIENCE_LABELS,
  parseHashtags,
  type DzenCommentAudience,
  type DzenPublishOptions
} from '../../shared/publish-options'
import type { PlatformAdapter, UploadPayload } from './types'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'

const PLATFORM = 'dzen'
const HOME = 'https://dzen.ru'
const PUBLISH_SEL = '[data-testid="publish-btn"]'
const ADD_SEL = '[data-testid="add-publication-button"]'
const VIDEO_FILE_SEL = [
  'input[name="video-popup__file"]',
  'input.video-editor--video-upload-dialog__file-3F',
  'input[type="file"][accept*="video"]',
  'input[type="file"][accept*="mp4"]'
]
const COVER_FILE_SEL =
  '.video-editor--video-cover-custom-item__videoCoverCustomItem input[type="file"][accept*="image"], input[type="file"][accept="image/png,image/jpeg"]'
const DESC_SEL = ['.video-editor--publication-settings .ql-editor', '.ql-editor']
const FAIL_RE = /что-то пошло не так|ошибка загрузки|не удалось загрузить|unsupported format|файл слишком/i
const PASSPORT_RE = /passport\.yandex|id\.vk\.com|sso\.passport|oauth\.yandex|passport\.vk/i
const EXTRA_CLOSE_RE =
  /\/help(?:\/|$)|help\.dzen|dzen\.ru\/help|support\.|feedback|ticket|ads\.yandex|direct\.yandex|vk\.com\/ads|реклам|promo|academy|calendly|partners|landing|metrika\.yandex|dzen\.ru\/adv|dzen\.ru\/premium|vse-o-dzen|about\.dzen|yandex\.ru\/support/i

function inStudio(page: Page): boolean {
  try {
    const { hostname, pathname } = new URL(page.url())
    const host = hostname.replace(/^www\./, '').toLowerCase()
    return host === 'dzen.ru' && /\/profile\/editor\/[^/]+/i.test(pathname)
  } catch {
    return false
  }
}

function inVideoEditor(page: Page): boolean {
  return /videoEditorPublicationId=/i.test(page.url())
}

function isPassportUrl(url: string): boolean {
  return PASSPORT_RE.test(url)
}

function assertNotPassport(page: Page): void {
  const url = page.url()
  if (!isPassportUrl(url) && !looksLoggedOut(url)) return
  uploadLog(PLATFORM, 'passport', url)
  throw new Error('Дзен требует вход через Яндекс ID или VK ID')
}

async function isEnabled(locator: Locator): Promise<boolean> {
  if ((await locator.count().catch(() => 0)) === 0) return false
  if (!(await locator.isVisible().catch(() => false))) return false
  const disabled = await locator.isDisabled().catch(() => true)
  const aria = await locator.getAttribute('aria-disabled').catch(() => null)
  return !disabled && aria !== 'true'
}

function publishButton(page: Page): Locator {
  return page.locator(PUBLISH_SEL).first()
}

async function closeExtraPages(main: Page): Promise<void> {
  if (main.isClosed()) return
  for (const extra of main.context().pages()) {
    if (extra === main || extra.isClosed()) continue
    const url = extra.url()
    if (isPassportUrl(url)) {
      uploadLogWindow(PLATFORM, url, 'ignored')
      uploadLog(PLATFORM, 'passport', `вкладка ${url}`)
      continue
    }
    if (EXTRA_CLOSE_RE.test(url)) {
      uploadLog(PLATFORM, 'extra-window', `закрываю ${url}`)
      uploadLogWindow(PLATFORM, url, 'closed')
      await extra.close().catch(() => undefined)
    }
  }
}

function watchExtraPages(main: Page): () => void {
  const context = main.context()
  const onPage = (extra: Page): void => {
    void (async () => {
      await extra.waitForLoadState('domcontentloaded').catch(() => undefined)
      await humanDelay(150, 350)
      if (extra.isClosed() || extra === main) return
      const url = extra.url()
      if (isPassportUrl(url)) {
        uploadLogWindow(PLATFORM, url, 'ignored')
        uploadLog(PLATFORM, 'passport', `редирект ${url}`)
        return
      }
      if (EXTRA_CLOSE_RE.test(url)) {
        uploadLog(PLATFORM, 'extra-window', `закрываю ${url}`)
        uploadLogWindow(PLATFORM, url, 'closed')
        await extra.close().catch(() => undefined)
        return
      }
      uploadLogWindow(PLATFORM, url, 'opened')
    })()
  }
  context.on('page', onPage)
  return () => {
    context.off('page', onPage)
  }
}

async function loginCheck(page: Page): Promise<boolean> {
  if (!inStudio(page)) {
    uploadLog(PLATFORM, 'login-check', 'открываю dzen.ru')
    await safeGoto(page, HOME)
  }
  uploadLog(PLATFORM, 'login-check', page.url())
  if (isPassportUrl(page.url()) || looksLoggedOut(page.url())) return false
  const avatar = page.locator('[data-testid="profile-menu-wrapper"], [data-testid="profile-avatar"]').first()
  return inStudio(page) || (await avatar.count()) > 0
}

async function openStudio(page: Page): Promise<void> {
  if (inStudio(page)) {
    if (inVideoEditor(page)) {
      const home = page.url().split('?')[0]
      uploadLog(PLATFORM, 'studio', `закрываю прошлый редактор → ${home}`)
      await safeGoto(page, home)
    } else {
      uploadLog(PLATFORM, 'studio', `уже в студии, меню профиля не трогаю | ${page.url()}`)
    }
    await dismissNuisances(page)
    await closeExtraPages(page)
    assertNotPassport(page)
    return
  }

  uploadLog(PLATFORM, 'goto', HOME)
  await safeGoto(page, HOME)
  await humanDelay(400, 800)
  await dismissNuisances(page)
  await closeExtraPages(page)
  if (isPassportUrl(page.url())) {
    uploadLog(PLATFORM, 'passport', page.url())
    throw new Error('Дзен требует вход через Яндекс ID или VK ID')
  }

  const studioLink = page.locator('a[href*="/profile/editor/"]').first()
  if (await studioLink.isVisible().catch(() => false)) {
    uploadLog(PLATFORM, 'studio', 'клик по ссылке Студия')
    await studioLink.click({ timeout: 5000 }).catch(() => undefined)
    await page.waitForURL(/\/profile\/editor\/[^/]+/i, { timeout: 15_000 }).catch(() => undefined)
  }

  if (!inStudio(page)) {
    const menu = page.locator('[data-testid="profile-menu-wrapper"]').first()
    if (await menu.isVisible().catch(() => false)) {
      uploadLog(PLATFORM, 'studio', 'меню профиля → Студия (один раз)')
      await menu.click({ timeout: 4000 }).catch(() => undefined)
      await humanDelay(300, 600)
      const opened =
        (await clickText(page, ['Студия', 'Studio'], 8000, true)) || (await clickByName(page, /^(студия|studio)$/i, 4000))
      if (opened) await page.waitForURL(/\/profile\/editor\/[^/]+/i, { timeout: 15_000 }).catch(() => undefined)
    }
  }

  await page.locator(ADD_SEL).first().waitFor({ state: 'visible', timeout: 20_000 }).catch(() => undefined)
  await humanDelay(400, 700)
  await dismissNuisances(page)
  await closeExtraPages(page)
  assertNotPassport(page)
  if (!inStudio(page)) {
    throw new Error('Не открылась Студия Дзена. Проверьте вход в аккаунт.')
  }
  uploadLog(PLATFORM, 'studio', page.url())
}

async function videoPickerReady(page: Page): Promise<boolean> {
  const input = page.locator(VIDEO_FILE_SEL.join(', ')).first()
  if ((await input.count().catch(() => 0)) > 0) return true
  const pick = page.getByRole('button', { name: /^Выбрать видео$/i }).first()
  return pick.isVisible().catch(() => false)
}

async function openUploadForm(page: Page): Promise<void> {
  if (await videoPickerReady(page)) {
    uploadLog(PLATFORM, 'create', 'форма выбора файла уже открыта')
    return
  }

  const started =
    (await clickFirstOptional(page, [ADD_SEL])) ||
    (await clickText(page, ['Создать публикацию'], 4000, true))
  if (!started) throw new Error('Не найдена кнопка создания публикации в Студии Дзена')
  uploadLog(PLATFORM, 'create', ADD_SEL)
  await humanDelay(250, 500)

  const video =
    (await clickText(page, ['Загрузить видео'], 8000, true)) ||
    (await page.getByRole('button', { name: 'Загрузить видео', exact: true }).click({ timeout: 5000 }).then(() => true).catch(() => false))
  if (!video) throw new Error('В меню создания нет пункта «Загрузить видео»')
  uploadLog(PLATFORM, 'create', 'Загрузить видео')

  await page
    .locator(`${VIDEO_FILE_SEL.join(', ')}, button:has-text("Выбрать видео")`)
    .first()
    .waitFor({ state: 'attached', timeout: 20_000 })

  if (!(await videoPickerReady(page))) {
    throw new Error('Не открылась форма загрузки видео в Студии Дзена')
  }
}

async function waitDzenProcessed(page: Page): Promise<void> {
  uploadLog(PLATFORM, 'processing', 'жду загрузку и редактор видео')
  await page.waitForURL(/videoEditorPublicationId=/i, { timeout: 180_000 }).catch(() => undefined)
  const editor = page.locator('.ql-editor, [class*="video-settings-cover"]').first()
  await editor.waitFor({ state: 'visible', timeout: 90_000 }).catch(() => undefined)

  const publish = publishButton(page)
  const deadline = Date.now() + 180_000
  let idleHits = 0
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await closeExtraPages(page)
    if (isPassportUrl(page.url())) {
      uploadLog(PLATFORM, 'passport', page.url())
      throw new Error('Дзен требует вход через Яндекс ID или VK ID')
    }
    const body = await page.locator('body').innerText().catch(() => '')
    if (FAIL_RE.test(body)) {
      uploadLogError(PLATFORM, 'processing', new Error(body.slice(0, 180)))
      throw new Error('Дзен не смог обработать видео')
    }
    const editorReady = await editor.isVisible().catch(() => false)
    const coverSlot = await page.locator('[class*="video-cover-custom-item"]').first().isVisible().catch(() => false)
    const publishReady = await isEnabled(publish)
    if (inVideoEditor(page) && editorReady && (publishReady || coverSlot)) {
      idleHits += 1
      if (idleHits >= 4 && (publishReady || coverSlot)) {
        uploadLog(PLATFORM, 'processing', `редактор готов | ${page.url()}`)
        return
      }
    } else {
      idleHits = 0
    }
    await sleep(400)
  }

  if (inVideoEditor(page) && (await editor.isVisible().catch(() => false))) {
    uploadLog(PLATFORM, 'processing', 'редактор открыт, публикация может быть ещё неактивна')
    return
  }
  throw new Error('Видео в Дзене ещё загружается или обрабатывается. Дождитесь готовности и повторите.')
}

async function fillMeta(page: Page, payload: UploadPayload): Promise<void> {
  const text = (payload.description || '').trim()
  if (!text) return
  uploadLog(PLATFORM, 'description', text.slice(0, 80))
  await fillFirst(page, DESC_SEL, text).catch(async () => {
    const box = page.locator('.ql-editor').first()
    if (!(await box.count())) return
    await box.click()
    const selectAll = process.platform === 'darwin' ? 'Meta+A' : 'Control+A'
    await page.keyboard.press(selectAll).catch(() => undefined)
    await page.keyboard.type(text, { delay: 12 })
  })
}

async function waitCoverSettled(page: Page): Promise<void> {
  const spinner = page.locator('[class*="video-cover-custom-item__spinnerWrapper"]')
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    const spinning = await spinner.first().isVisible().catch(() => false)
    if (!spinning) return
    await sleep(300)
  }
}

async function attachCover(page: Page, coverPath?: string): Promise<void> {
  if (!coverPath) return
  uploadLog(PLATFORM, 'cover', coverPath)
  const input = page.locator(COVER_FILE_SEL).last()
  await input.waitFor({ state: 'attached', timeout: 45_000 }).catch(() => undefined)
  if ((await input.count().catch(() => 0)) > 0) {
    await input.setInputFiles(coverPath)
    await waitCoverSettled(page)
    uploadLog(PLATFORM, 'cover', 'своя обложка через hidden input image/png,jpeg')
    return
  }

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 12_000 }).catch(() => null)
  const clicked =
    (await clickText(page, ['Добавить обложку'], 4000, true)) ||
    (await page.locator('[class*="video-cover-custom-item__emptyBlock"]').first().click({ timeout: 4000 }).then(() => true).catch(() => false))
  const chooser = await chooserPromise
  if (chooser) {
    await chooser.setFiles(coverPath)
    await waitCoverSettled(page)
    uploadLog(PLATFORM, 'cover', `своя обложка через filechooser (${clicked || 'custom-item'})`)
    return
  }
  uploadLog(PLATFORM, 'cover', 'не найден input обложки')
}

async function fillTags(page: Page, raw?: string): Promise<void> {
  const tags = parseHashtags(raw)
  if (!tags.length) return
  const input = page.locator('input[placeholder="Добавьте теги"], [class*="tag-input__input"]').first()
  await input.waitFor({ state: 'visible', timeout: 15_000 })
  await input.scrollIntoViewIfNeeded().catch(() => undefined)
  for (const tag of tags) {
    await input.click({ timeout: 3000 }).catch(() => undefined)
    await humanDelay(80, 140)
    await page.keyboard.type(tag, { delay: 25 })
    await page.keyboard.press('Enter')
    await humanDelay(150, 260)
  }
  uploadLog(PLATFORM, 'tags', tags.map((tag) => `#${tag}`).join(' '))
}

async function fillCommentsTitle(page: Page, title?: string): Promise<void> {
  const value = String(title || '').trim().slice(0, 70)
  if (!value) return
  const box = page.locator('[data-testid="publication-custom-comments-title-input"]').first()
  await box.waitFor({ state: 'visible', timeout: 12_000 })
  await box.scrollIntoViewIfNeeded().catch(() => undefined)
  await box.fill(value)
  uploadLog(PLATFORM, 'comments-title', value)
}

async function selectCommentAudience(page: Page, audience?: DzenCommentAudience): Promise<void> {
  const value: DzenCommentAudience =
    audience && audience in DZEN_COMMENT_AUDIENCE_LABELS ? audience : 'everyone'
  const label = DZEN_COMMENT_AUDIENCE_LABELS[value]
  const trigger = page.locator('[data-testid="select-trigger-button-comment"]').first()
  await trigger.waitFor({ state: 'visible', timeout: 15_000 })
  await trigger.scrollIntoViewIfNeeded().catch(() => undefined)
  const current = (await trigger.innerText().catch(() => '')).replace(/\s+/g, ' ').trim()
  if (current === label) {
    uploadLog(PLATFORM, 'comments', `уже «${label}»`)
    return
  }
  uploadLog(PLATFORM, 'comments', label)
  await trigger.click({ timeout: 4000 })
  await humanDelay(150, 300)
  const option = page.getByRole('option', { name: label, exact: true }).first()
  if (await option.isVisible().catch(() => false)) {
    await option.click({ timeout: 4000 })
    return
  }
  const items = page.getByText(label, { exact: true })
  const total = await items.count().catch(() => 0)
  for (let i = total - 1; i >= 0; i--) {
    const item = items.nth(i)
    if (!(await item.isVisible().catch(() => false))) continue
    const testId = await item.getAttribute('data-testid').catch(() => null)
    if (testId === 'select-trigger-button-comment') continue
    await item.click({ timeout: 4000 })
    return
  }
  throw new Error(`Не удалось выбрать «${label}» в «Кто может комментировать»`)
}

async function fillDzenPublishOptions(page: Page, payload: UploadPayload): Promise<void> {
  const opts = (payload.options || {}) as DzenPublishOptions
  await fillTags(page, payload.hashtags || opts.tags)
  await selectCommentAudience(page, opts.commentAudience)
  await fillCommentsTitle(page, opts.commentsTitle)
}

async function publishOrDryRun(page: Page, dryRun?: boolean): Promise<void> {
  const publish = publishButton(page)
  await waitUntilEnabled(publish, 90_000).catch(() => undefined)
  if (dryRun) {
    uploadLog(PLATFORM, 'dry-run', 'публикацию не нажимаю')
    return
  }
  if (!(await isEnabled(publish))) {
    throw new Error('Кнопка «Опубликовать» в Дзене ещё неактивна')
  }
  uploadLog(PLATFORM, 'publish', page.url())
  const published =
    (await clickFirstOptional(page, [PUBLISH_SEL])) ||
    (await clickByName(page, I18N.publish, 5000))
  if (!published) await clickIfPresent(page, [PUBLISH_SEL])
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  const stopWatch = watchExtraPages(page)
  try {
    await openStudio(page)
    await dismissNuisances(page)
    await closeExtraPages(page)

    await openUploadForm(page)
    uploadLog(PLATFORM, 'file', payload.videoPath)
    await attachFile(page, payload.videoPath, [...VIDEO_FILE_SEL, 'button:has-text("Выбрать видео")'])

    await waitDzenProcessed(page)
    await dismissNuisances(page)
    await closeExtraPages(page)

    await fillMeta(page, payload)
    await attachCover(page, payload.coverPath)
    await waitCoverSettled(page)
    await fillDzenPublishOptions(page, payload)
    await publishOrDryRun(page, payload.dryRun)
    if (!payload.dryRun) await humanDelay(800, 1400)
    const url = await waitForPublicUrl(page, PLATFORM, 30_000)
    uploadLog(PLATFORM, 'done', url || page.url())
    return url || page.url()
  } catch (error) {
    uploadLogError(PLATFORM, 'upload', error)
    throw error
  } finally {
    stopWatch()
  }
}

export const dzenAdapter: PlatformAdapter = { loginCheck, upload }
