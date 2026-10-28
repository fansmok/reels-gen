import type { Locator, Page } from 'playwright-core'
import {
  attachFile,
  clickFirstOptional,
  clickText,
  dismissNuisances,
  humanDelay,
  looksLoggedOut,
  resolvePublishedUrl,
  safeGoto,
  setToggle
} from './helpers'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'
import {
  clampTiktokCaption,
  parseTiktokHashtags,
  type TiktokPublishOptions
} from '../../shared/publish-options'
import type { PlatformAdapter, UploadPayload } from './types'

const STUDIO = 'https://www.tiktok.com/tiktokstudio'
const UPLOAD = 'https://www.tiktok.com/tiktokstudio/upload'
const POST_BTN = '[data-e2e="post_video_button"]'
const STATUS = '[data-e2e="upload_status_container"]'
const COVER = '[data-e2e="cover_container"]'

const ERROR_MODAL_RE = /что-то пошло не так|something went wrong|something[’']s wrong|произошла ошибка/i
const COPYRIGHT_RE = /автоматическую проверку контента|automatic content check|copyright check/i
const RETRY_LABELS = ['Повторить попытку', 'Retry', 'Try again', 'Try Again', 'OK']
const EXTRA_PAGE_RE =
  /ads\.tiktok|pangle|business\.tiktok|tiktokads|academy|calendly|help\.tiktok|support\.tiktok|creator-rewards|live\.tiktok|\/learn|adsmanager/i

function snippet(text: string): string {
  return text.replace(/\s+/g, ' ').trim().slice(0, 200)
}

function parseStatus(status: string): { done: boolean; busy: boolean } {
  const s = status.toLowerCase()
  const done = /загружено|uploaded/.test(s) && !/остал/.test(s)
  if (done) return { done: true, busy: false }
  const busy =
    /остал|uploading|processing|encoding|checking your video|идёт загрузка|видео загружается/.test(s) ||
    (/\d+([.,]\d+)?\s*%/.test(s) && !/100\s*%/.test(s))
  return { done: false, busy }
}

const seenExtraUrls = new Set<string>()

async function closeExtraWindows(page: Page): Promise<void> {
  if (page.isClosed()) return
  for (const extra of page.context().pages()) {
    if (extra === page || extra.isClosed()) continue
    const url = extra.url()
    if (!url || url === 'about:blank') continue
    const keep = /tiktokstudio/i.test(url) || /\/login/i.test(url)
    if (EXTRA_PAGE_RE.test(url) && !keep) {
      uploadLogWindow('tiktok', url, 'closed')
      await extra.close().catch(() => undefined)
      continue
    }
    if (!seenExtraUrls.has(url)) {
      seenExtraUrls.add(url)
      uploadLogWindow('tiktok', url, 'ignored')
    }
  }
}

async function dismissErrorModals(page: Page): Promise<boolean> {
  if (page.isClosed()) return false
  const overlay = page.locator('.TUXModal-overlay, [class*="TUXModal"], [class*="common-modal-body"]').first()
  const errorText = page.getByText(ERROR_MODAL_RE).first()
  const overlayVisible = await overlay.isVisible().catch(() => false)
  const errorVisible = await errorText.isVisible().catch(() => false)
  const overlayCopy = overlayVisible ? await overlay.innerText().catch(() => '') : ''
  const looksError = errorVisible || (overlayVisible && ERROR_MODAL_RE.test(overlayCopy))
  if (!looksError) return false

  const detail = snippet(
    errorVisible ? (await errorText.innerText().catch(() => overlayCopy)) || overlayCopy : overlayCopy
  )
  uploadLog('tiktok', 'error-modal', detail || 'Что-то пошло не так')
  const retried = await clickText(page, [...RETRY_LABELS, 'Закрыть', 'Close'], 2500)
  await page.keyboard.press('Escape').catch(() => undefined)
  uploadLog('tiktok', 'error-modal', retried ? 'закрыл Retry' : 'закрыл Escape')
  await humanDelay(250, 500)
  return true
}

async function dismissCopyrightModal(page: Page): Promise<boolean> {
  if (page.isClosed()) return false
  const copy = page.getByText(COPYRIGHT_RE).first()
  if (!(await copy.isVisible().catch(() => false))) return false
  uploadLog('tiktok', 'modal', 'проверка контента — закрываю Отмена, не трогаю обложку')
  const dialog = page.locator('.TUXModal, [class*="common-modal"]').filter({ hasText: COPYRIGHT_RE }).first()
  const cancel = dialog.getByRole('button', { name: /^(отмена|cancel)$/i }).first()
  if (await cancel.isVisible().catch(() => false)) {
    await cancel.click({ timeout: 2500 }).catch(() => cancel.click({ force: true }))
  } else {
    await page.locator('.common-modal-close, [class*="common-modal-close"]').first().click({ timeout: 2000 }).catch(() => undefined)
    await page.keyboard.press('Escape').catch(() => undefined)
  }
  await humanDelay(300, 500)
  return true
}

async function dismissBlockingOverlays(page: Page): Promise<void> {
  await dismissErrorModals(page)
  await dismissCopyrightModal(page)
  await dismissNuisances(page)
  await closeExtraWindows(page)
}

async function armModalHandlers(page: Page): Promise<void> {
  const locators = [
    page.getByText(ERROR_MODAL_RE),
    page.locator('.TUXModal-overlay, [class*="TUXModal"], [class*="common-modal-body"]').filter({
      hasText: ERROR_MODAL_RE
    }),
    page.getByText(COPYRIGHT_RE)
  ]
  for (const locator of locators) {
    try {
      await page.addLocatorHandler(
        locator.first(),
        async () => {
          await dismissErrorModals(page)
          await dismissCopyrightModal(page)
        },
        { times: 12 }
      )
    } catch {
      /* нет addLocatorHandler */
    }
  }
}

async function isPostEnabled(page: Page): Promise<boolean> {
  const post = page.locator(POST_BTN).first()
  if ((await post.count().catch(() => 0)) === 0) return false
  if (!(await post.isVisible().catch(() => false))) return false
  const disabled = await post.isDisabled().catch(() => true)
  const aria = await post.getAttribute('aria-disabled').catch(() => null)
  return !disabled && aria !== 'true'
}

async function waitTikTokReady(page: Page, timeout = 180_000): Promise<void> {
  uploadLog('tiktok', 'wait-ready', 'жду Загружено + Post enabled (не 99% с «Осталась»)')
  const deadline = Date.now() + timeout
  let lastStatus = ''
  let idleHits = 0
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await dismissBlockingOverlays(page)

    const status = snippet((await page.locator(STATUS).innerText().catch(() => '')) || '')
    if (status && status !== lastStatus) {
      uploadLog('tiktok', 'status', status)
      lastStatus = status
    }
    const { done, busy } = parseStatus(status)
    if (/ошибк|error|fail|не удалось|не получилось/i.test(status) && !done) {
      uploadLog('tiktok', 'status-error', status)
      await clickText(page, RETRY_LABELS, 3000)
      await page.keyboard.press('Escape').catch(() => undefined)
      idleHits = 0
    }

    const postReady = await isPostEnabled(page)
    if (done && postReady && !busy) {
      idleHits += 1
      if (idleHits >= 2) {
        uploadLog('tiktok', 'wait-ready', 'загрузка завершена: Загружено, Post доступен')
        return
      }
    } else {
      idleHits = 0
    }
    await humanDelay(400, 700)
  }
  throw new Error('Видео ещё загружается или обрабатывается в TikTok. Дождитесь готовности и повторите.')
}

function coverEditor(page: Page): Locator {
  return page.locator('.Dialog__content, [class*="CoverEditor"]').filter({
    hasText: /изменить обложку|edit cover|change cover|загрузить обложку|upload cover/i
  }).first()
}

async function attachTikTokCover(page: Page, coverPath: string): Promise<void> {
  uploadLog('tiktok', 'cover', 'открываю .cover-container / .edit-container, не видео-input')
  await dismissBlockingOverlays(page)
  const thumb = page.locator(`${COVER} .cover-container, .cover-container`).first()
  const edit = page.locator(`${COVER} .edit-container`).first()
  await thumb.waitFor({ state: 'visible', timeout: 20_000 })
  await thumb.hover().catch(() => undefined)
  await thumb.click({ timeout: 8000 }).catch(async () => thumb.click({ timeout: 4000, force: true }))
  await humanDelay(400, 800)
  const editor = coverEditor(page)
  if (!(await editor.isVisible().catch(() => false)) && (await edit.isVisible().catch(() => false))) {
    await edit.click({ timeout: 4000, force: true })
  }
  await editor.waitFor({ state: 'visible', timeout: 15_000 })
  uploadLog('tiktok', 'cover', 'редактор: ImageUpload PNG, FramePicker не трогаю')

  const imageInput = editor.locator(
    'input[type="file"][accept*="image/png"], input[type="file"][accept*="image"]:not([accept*="video"]), .ImageUpload__uploadArea input[type="file"]'
  )
  if ((await imageInput.count()) > 0) {
    await imageInput.last().setInputFiles(coverPath)
    uploadLog('tiktok', 'cover', 'PNG через input accept=image/jpeg,image/png,image/jpg')
  } else {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 12_000 })
    await editor.locator('.ImageUpload__uploadArea, [aria-label="Upload cover image"]').first().click({ timeout: 5000 })
    await (await chooserPromise).setFiles(coverPath)
    uploadLog('tiktok', 'cover', 'PNG через filechooser ImageUpload')
  }

  await editor
    .locator('.ImageUpload__preview, [aria-label="Uploaded cover image"]')
    .first()
    .waitFor({ state: 'visible', timeout: 15_000 })
  uploadLog('tiktok', 'cover', 'превью своей обложки есть, Сохранить в диалоге')

  const save = editor.getByRole('button', { name: /^(сохранить|save|done|готово)$/i }).first()
  await save.click({ timeout: 8000 })
  await editor.waitFor({ state: 'hidden', timeout: 20_000 }).catch(() => undefined)
}

async function fillCaption(page: Page, payload: UploadPayload, opts: TiktokPublishOptions): Promise<void> {
  const caption = clampTiktokCaption(payload.description || opts.description)
  const box = page.locator('[data-e2e="caption_container"] [contenteditable="true"]').first()
  await box.waitFor({ state: 'visible', timeout: 20_000 })
  await box.click({ timeout: 5000 })
  const selectAll = process.platform === 'darwin' ? 'Meta+A' : 'Control+A'
  await page.keyboard.press(selectAll).catch(() => undefined)
  await page.keyboard.press('Backspace').catch(() => undefined)
  if (!caption) {
    uploadLog('tiktok', 'caption', 'описание пустое — название и имя файла не подставляю')
    return
  }
  uploadLog('tiktok', 'caption', `${caption.length} символов, без названия`)
  await page.keyboard.type(caption, { delay: 1 })
  await humanDelay(150, 280)
}

function escapeHashtag(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function pickHashtagSuggestion(page: Page, tag: string): Promise<boolean> {
  const items = page.locator('.hashtag-suggestion-item, .mention-list-popover .hashtag-suggestion-item')
  try {
    await items.first().waitFor({ state: 'visible', timeout: 6000 })
  } catch {
    await page.keyboard.press('Enter').catch(() => undefined)
    return false
  }
  const exact = items.filter({ hasText: new RegExp(`^#${escapeHashtag(tag)}(\\s|$)`, 'i') }).first()
  if ((await exact.count().catch(() => 0)) > 0 && (await exact.isVisible().catch(() => false))) {
    await exact.click({ timeout: 4000 })
    return true
  }
  const contains = items.filter({ hasText: new RegExp(`#${escapeHashtag(tag)}`, 'i') }).first()
  if ((await contains.count().catch(() => 0)) > 0 && (await contains.isVisible().catch(() => false))) {
    await contains.click({ timeout: 4000 })
    return true
  }
  await items.first().click({ timeout: 4000 })
  return true
}

async function addHashtags(page: Page, raw?: string): Promise<void> {
  const tags = parseTiktokHashtags(raw)
  if (!tags.length) return
  const btn = page.locator('#web-creation-caption-hashtag-button').first()
  if ((await btn.count().catch(() => 0)) === 0) {
    uploadLog('tiktok', 'hashtags', 'кнопка «Хэштеги» не найдена')
    return
  }
  await btn.scrollIntoViewIfNeeded().catch(() => undefined)
  const caption = page.locator('[data-e2e="caption_container"] [contenteditable="true"]').first()
  if (await caption.isVisible().catch(() => false)) {
    await caption.click({ timeout: 3000 })
    await page.keyboard.press('End').catch(() => undefined)
    const text = ((await caption.innerText().catch(() => '')) || '').replace(/\s+$/, '')
    if (text) await page.keyboard.press('Space')
  }

  for (const tag of tags) {
    await btn.click({ timeout: 4000 })
    uploadLog('tiktok', 'hashtag', `кнопка Хэштеги → #${tag}`)
    await humanDelay(220, 380)
    await page.keyboard.type(tag, { delay: 35 })
    await humanDelay(400, 700)
    const picked = await pickHashtagSuggestion(page, tag)
    uploadLog('tiktok', 'hashtag', picked ? `из списка #${tag}` : `Enter #${tag}`)
    await humanDelay(180, 280)
    await page.keyboard.press('Space')
    await humanDelay(100, 180)
  }
  const mentions = await page.locator('[data-e2e="caption_container"] .mention').allInnerTexts().catch(() => [])
  uploadLog('tiktok', 'hashtags', mentions.map((t) => t.trim()).filter(Boolean).join(' ') || tags.map((t) => `#${t}`).join(' '))
}

async function applyOptions(page: Page, opts: TiktokPublishOptions): Promise<void> {
  const audienceLabel =
    opts.audience === 'friends'
      ? /друзья|friends|amis|freunde|amigos/i
      : opts.audience === 'only_me'
        ? /только вы|only you|private|nur ich|seulement moi/i
        : /все|everyone|tout le monde|alle|todos/i
  const audienceBox = page
    .getByRole('combobox')
    .filter({ hasText: /все|друзья|только|everyone|friends|private|alle|todos/i })
    .first()
  if (await audienceBox.isVisible().catch(() => false)) {
    await audienceBox.click()
    await humanDelay(300, 600)
    await page.getByRole('option', { name: audienceLabel }).first().click().catch(() => undefined)
    uploadLog('tiktok', 'audience', opts.audience)
  }
  await setToggle(
    page,
    [
      'label:has-text("Комментарий") input',
      'label:has-text("Comment") input',
      'label:has-text("Comentario") input',
      'label:has-text("Kommentar") input'
    ],
    opts.comments
  )
  await setToggle(
    page,
    [
      'label:has-text("Повторное использование контента") input',
      'label:has-text("Duet") input',
      'label:has-text("Reuse") input',
      'label:has-text("Stitch") input'
    ],
    opts.allowReuse
  )
}

async function clickPost(page: Page): Promise<void> {
  uploadLog('tiktok', 'post', 'нажимаю Опубликовать')
  await dismissBlockingOverlays(page)
  const posted =
    (await clickFirstOptional(page, [POST_BTN])) ||
    (await clickText(page, ['Опубликовать', 'Post', 'Publish', 'Publicar'], 5000, true))
  if (posted) return
  const btn = page.locator(POST_BTN).first()
  if (await btn.count()) await btn.click()
  else throw new Error('Не найдена кнопка Post в TikTok')
}

async function waitTikTokPublished(page: Page): Promise<string | undefined> {
  const deadline = Date.now() + 90_000
  const success = page
    .getByText(/видео опубликовано|успешно опубликовано|video published|posted successfully|uploaded successfully/i)
    .first()
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    if (await dismissErrorModals(page)) {
      throw new Error('TikTok показал ошибку после нажатия «Опубликовать»')
    }
    const url = await resolvePublishedUrl(page, 'tiktok', page.url())
    if (url) return url
    if (await success.isVisible().catch(() => false)) {
      uploadLog('tiktok', 'post', 'TikTok подтвердил публикацию')
      return undefined
    }
    const leftUploadForm =
      !/tiktokstudio\/upload/i.test(page.url()) &&
      !(await page.locator(POST_BTN).isVisible().catch(() => false))
    if (leftUploadForm) {
      uploadLog('tiktok', 'post', 'форма загрузки закрылась')
      return undefined
    }
    await humanDelay(400, 700)
  }
  throw new Error('TikTok не подтвердил публикацию за 90 секунд. Площадка пропущена, очередь идёт дальше.')
}

async function loginCheck(page: Page): Promise<boolean> {
  uploadLog('tiktok', 'login-check', STUDIO)
  await safeGoto(page, STUDIO)
  await humanDelay(200, 400)
  await dismissBlockingOverlays(page)
  if (looksLoggedOut(page.url())) {
    uploadLog('tiktok', 'login-check', 'не авторизован')
    return false
  }
  return page.url().includes('tiktokstudio') || page.url().includes('/upload')
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  try {
    seenExtraUrls.clear()
    uploadLog('tiktok', 'goto', UPLOAD)
    await safeGoto(page, UPLOAD)
    await humanDelay(1200, 2000)
    await armModalHandlers(page)
    await dismissBlockingOverlays(page)

    uploadLog('tiktok', 'file', 'видео: input[accept=video/*] / select_video_button')
    await attachFile(page, payload.videoPath, [
      'input[type="file"][accept*="video"]',
      '[data-e2e="select_video_button"]',
      '[data-e2e="select_file_item"]',
      'button[aria-label*="Select video" i]',
      'button[aria-label*="Выбрать видео" i]',
      'button:has-text("Select video")',
      'button:has-text("Выбрать видео")'
    ])
    await humanDelay(800, 1400)

    await waitTikTokReady(page)
    const opts = payload.options as TiktokPublishOptions
    await fillCaption(page, payload, opts)
    await addHashtags(page, payload.hashtags || opts.hashtags)

    if (payload.coverPath) {
      await waitTikTokReady(page)
      await attachTikTokCover(page, payload.coverPath)
    }

    await applyOptions(page, opts)
    await humanDelay(300, 600)
    await waitTikTokReady(page)

    if (payload.dryRun) {
      uploadLog('tiktok', 'dryRun', 'Опубликовать не нажимаю')
      return page.url()
    }
    await clickPost(page)
    const url = await waitTikTokPublished(page)
    uploadLog('tiktok', 'done', url || page.url())
    return url || page.url()
  } catch (error) {
    uploadLogError('tiktok', 'upload', error)
    throw error
  }
}

export const tiktokAdapter: PlatformAdapter = { loginCheck, upload }
