import { existsSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import type { CDPSession, Page } from 'playwright-core'
import {
  attachFile,
  clickByName,
  clickIfPresent,
  clickText,
  clickWhenEnabled,
  dismissNuisances,
  fillFirst,
  humanDelay,
  I18N,
  looksLikeNuisanceTab,
  looksLoggedOut,
  safeGoto,
  setToggle,
  waitForPublicUrl,
  waitUntilEnabled
} from './helpers'
import type { YoutubePublishOptions } from '../../shared/publish-options'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'
import type { PlatformAdapter, UploadPayload } from './types'

const PRECHECK_DIALOG = 'ytcp-prechecks-warning-dialog, tp-yt-paper-dialog:has(#secondary-action-button)'
const PUBLISH_ANYWAY_RE =
  /publish anyway|publish|опубликовать|опублікувати|veröffentlichen|publicar|publier|pubblica|yayınla|opublikuj|公開|게시|发布|發佈|publiceren|نشر|publicera|julkaise|publiser|δημοσι|publikovat|közzét/i
const FIX_RE = /fix|исправ|correct|bearbeiten|corregir|corriger|수정|修复|修復|düzelt|修正|reparar/i
const STUDIO = 'https://studio.youtube.com'
const FILE_UI = '#select-files-button, input[name="Filedata"], ytcp-uploads-dialog input[type="file"]'
const PROCESSING_TIMEOUT = 900_000

/** Только футер ytcp-video-upload-progress. Не брать «Загрузить файл» у значка. */
const UPLOADING_RE = /загружено:\s*\d|загрузка видео(?! завершена)|видео загружается|идёт загрузка|идет загрузка|uploading\s+\d|left to upload/i
const PROCESSING_RE =
  /скоро начнется обработка|обработка в\s*(sd|hd)|проверка:\s*\d|encoding|checking your video|hd processing|sd processing|processing will begin|осталось \d+\s*мин/i
const DONE_RE =
  /проверк[аи] завершен|checks complete|no issues found|проблем не обнаружено|finished processing|обработка завершена|processing complete/i
const FAIL_RE =
  /не удалось загрузить|upload failed|couldn['’]?t upload|processing abandoned|файл слишком большой|failed to upload|ошибка загрузки/i

async function loginCheck(page: Page): Promise<boolean> {
  await safeGoto(page, STUDIO)
  if ((await page.getByText(/ПЕРЕЙТИ В ПРИЛОЖЕНИЕ|Switch to app|unsupported browser|navegador no compatible/i).count()) > 0) {
    await safeGoto(page, 'https://studio.youtube.com/?approve_browser_access=true')
  }
  await dismissNuisances(page)
  if (looksLoggedOut(page.url())) return false
  const avatar = page.locator('#avatar-btn, img#img, ytcp-topbar img').first()
  return (await avatar.count()) > 0 || page.url().includes('studio.youtube.com')
}

async function closeExtraPages(keep: Page): Promise<void> {
  for (const extra of keep.context().pages()) {
    if (extra === keep || extra.isClosed()) continue
    const url = extra.url()
    if (!looksLikeNuisanceTab(url)) {
      uploadLogWindow('youtube', url || '(пусто)', 'ignored')
      continue
    }
    uploadLogWindow('youtube', url || '(пусто)', 'closed')
    await extra.close().catch(() => undefined)
  }
}

function watchExtraPages(keep: Page): () => void {
  const ctx = keep.context()
  const onPage = (opened: Page): void => {
    if (opened === keep) return
    void (async () => {
      await opened.waitForLoadState('domcontentloaded').catch(() => undefined)
      const url = opened.url()
      uploadLogWindow('youtube', url || '(пусто)', 'opened')
      if (!looksLikeNuisanceTab(url)) return
      await opened.close().catch(() => undefined)
      uploadLogWindow('youtube', url || '(пусто)', 'closed')
    })()
  }
  ctx.on('page', onPage)
  return () => ctx.off('page', onPage)
}

async function armPrechecksPublishHandler(page: Page): Promise<void> {
  try {
    await page.addLocatorHandler(page.locator(PRECHECK_DIALOG).first(), async () => {
      await clickPrechecksPublish(page)
    })
  } catch {
    /* старый playwright */
  }
}

async function clickPrechecksPublish(page: Page): Promise<boolean> {
  const dialog = page.locator(PRECHECK_DIALOG).first()
  if (!(await dialog.isVisible().catch(() => false))) return false
  const byId = dialog.locator('#secondary-action-button button, ytcp-button#secondary-action-button').first()
  if ((await byId.count()) > 0) {
    await byId.click({ timeout: 4000 }).catch(async () => byId.click({ force: true }))
    return true
  }
  const buttons = dialog.getByRole('button')
  const total = await buttons.count()
  for (let i = 0; i < total; i++) {
    const btn = buttons.nth(i)
    const label = `${await btn.getAttribute('aria-label')} ${await btn.innerText()}`.trim()
    if (FIX_RE.test(label)) continue
    if (PUBLISH_ANYWAY_RE.test(label)) {
      await btn.click({ timeout: 4000 }).catch(async () => btn.click({ force: true }))
      return true
    }
  }
  return false
}

async function confirmPublish(page: Page): Promise<void> {
  const done = await clickIfPresent(page, ['#done-button', 'ytcp-button#done-button'])
  if (!done) {
    const published = await clickText(page, ['Publish', 'Опубликовать', 'Save', 'Сохранить'], 5000, true)
    if (!published) throw new Error('Не найдена кнопка публикации на YouTube')
  }
  for (let i = 0; i < 4; i++) {
    const clicked = await clickPrechecksPublish(page)
    if (!clicked) {
      const stillOpen = await page.locator(PRECHECK_DIALOG).first().isVisible().catch(() => false)
      if (!stillOpen) break
    }
    await humanDelay(200, 400)
  }
}

async function clickNext(page: Page): Promise<void> {
  await waitUntilEnabled(page.locator('#next-button, ytcp-button#next-button').first(), 120_000)
  const clicked =
    (await clickWhenEnabled(page, '#next-button:not([disabled])', 20_000)) ||
    (await clickWhenEnabled(page, 'ytcp-button#next-button', 8_000)) ||
    (await clickByName(page, I18N.next, 3000)) ||
    (await clickText(page, ['Next', 'Далее', 'Siguiente', 'Weiter', 'Suivant'], 3000))
  if (!clicked) throw new Error('Не найдена кнопка «Далее» на YouTube')
}

type ProgressSnap = {
  busy: boolean
  ready: boolean
  pct: number | null
  text: string
  error?: string
}

async function readYoutubeProgress(page: Page): Promise<ProgressSnap> {
  const progress = page.locator('ytcp-video-upload-progress').first()
  const errLoc = page.locator(
    'ytcp-uploads-dialog #error-message, ytcp-uploads-dialog .error-short-message, ytcp-uploads-dialog-error'
  )
  const texts = [
    ...(await progress.allInnerTexts().catch(() => [])),
    ...(await errLoc.allInnerTexts().catch(() => []))
  ]
  const text = texts.join(' ').replace(/\s+/g, ' ').trim()

  let pct: number | null = null
  const bar = page
    .locator(
      'ytcp-video-upload-progress [role="progressbar"], ytcp-video-upload-progress tp-yt-paper-progress, ytcp-video-upload-progress #progress'
    )
    .first()
  if ((await bar.count().catch(() => 0)) > 0) {
    const now = Number((await bar.getAttribute('aria-valuenow').catch(() => null)) ?? (await bar.getAttribute('value').catch(() => null)))
    if (Number.isFinite(now)) pct = now
  }
  for (const match of text.matchAll(/(\d+)\s*%/g)) {
    pct = Math.max(pct ?? 0, Number(match[1]))
  }

  const fail = text.match(FAIL_RE)
  const uploading = UPLOADING_RE.test(text)
  const processing = PROCESSING_RE.test(text)
  const done = DONE_RE.test(text)
  const uploadBusy = uploading && !done
  const processBusy = processing && !done
  const pctBusy = pct !== null && pct < 100 && !done
  const busy = uploadBusy || processBusy || pctBusy
  const ready = !busy && done

  return {
    busy,
    ready,
    pct,
    text: text.slice(0, 240),
    error: fail?.[0]
  }
}

/** Ждём и загрузку файла, и обработку. «Далее» не жмём, пока ролик не готов. */
async function waitYoutubeProcessed(page: Page, timeout = PROCESSING_TIMEOUT): Promise<void> {
  uploadLog('youtube', 'processing wait', 'жду полную загрузку и обработку видео')
  const deadline = Date.now() + timeout
  let readyHits = 0
  let lastLogged = ''
  let seenActivity = false
  let idleWithoutWidget = 0

  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await closeExtraPages(page)

    const snap = await readYoutubeProgress(page)
    if (snap.error) throw new Error(`YouTube: ${snap.error}`)
    if (snap.busy || snap.pct !== null || DONE_RE.test(snap.text)) seenActivity = true

    const status = `${snap.pct ?? '—'}% ${snap.text || 'нет виджета прогресса'}`
    if (status !== lastLogged) {
      uploadLog('youtube', 'processing wait', snap.ready && seenActivity ? 'похоже, ролик готов' : `ещё не готов: ${status}`)
      lastLogged = status
    }

    if (seenActivity && snap.ready) {
      readyHits += 1
      if (readyHits >= 6) {
        uploadLog('youtube', 'processing wait', 'загрузка и обработка завершены')
        return
      }
    } else {
      readyHits = 0
    }

    // Короткий ролик: виджет успел исчезнуть, форма деталей уже есть.
    if (!snap.busy && !snap.text && (await page.locator('#title-textarea').first().isVisible().catch(() => false))) {
      idleWithoutWidget += 1
      if (seenActivity && idleWithoutWidget >= 8) {
        uploadLog('youtube', 'processing wait', 'виджет прогресса скрыт — считаю обработку завершённой')
        return
      }
    } else {
      idleWithoutWidget = 0
    }

    await sleep(500)
  }
  throw new Error('YouTube слишком долго загружает или обрабатывает видео. Дождитесь готовности и повторите.')
}

async function openUploadDialog(page: Page): Promise<void> {
  const fileUi = page.locator(FILE_UI).first()
  if ((await fileUi.count().catch(() => 0)) > 0) {
    uploadLog('youtube', 'create', 'диалог загрузки уже открыт')
    return
  }

  const uploadIcon = page.locator('#upload-icon, ytcp-icon-button#upload-icon').first()
  const createBtn = page.locator('button[aria-label="Создать"]').first()
  await uploadIcon.or(createBtn).waitFor({ state: 'visible', timeout: 25_000 }).catch(() => undefined)

  uploadLog('youtube', 'create', '#upload-icon aria «Добавить видео»')
  if ((await uploadIcon.count()) > 0) {
    await uploadIcon.click({ timeout: 8000, force: true })
  } else if (await createBtn.isVisible().catch(() => false)) {
    uploadLog('youtube', 'create', 'fallback: button[aria-label="Создать"] — не «Спросить у Студии»')
    await createBtn.click({ timeout: 4000 })
  } else {
    throw new Error('Не найдена кнопка «Создать» / «Добавить видео» в YouTube Studio')
  }

  const menuItem = page.locator('#text-item-0, tp-yt-paper-item#text-item-0').first()
  let menuClicked = false
  const deadline = Date.now() + 15_000
  while (Date.now() < deadline) {
    if ((await fileUi.count().catch(() => 0)) > 0) {
      uploadLog('youtube', 'create', 'диалог выбора файла открыт')
      return
    }
    if (!menuClicked && (await menuItem.isVisible().catch(() => false))) {
      uploadLog('youtube', 'create', 'меню «Создать» → только «Загрузить видео»')
      await menuItem.click({ timeout: 4000 }).catch(() => undefined)
      menuClicked = true
    }
    await sleep(200)
  }
  throw new Error('Не открылся диалог загрузки YouTube')
}

/** Живой UI: секция «Значок» → скрытый #file-loader (jpeg/png). Не жать «Выбрать из видео». */
async function attachYoutubeCover(page: Page, coverPath: string): Promise<void> {
  const editor = page.locator('ytcp-video-thumbnail-editor, ytcp-thumbnail-uploader, #file-loader').first()
  await editor.waitFor({ state: 'attached', timeout: 20_000 })
  await page.locator('ytcp-video-thumbnail-editor').first().scrollIntoViewIfNeeded().catch(() => undefined)
  await page.locator('#file-loader').first().scrollIntoViewIfNeeded().catch(() => undefined)
  await humanDelay(200, 400)

  const loader = page.locator('#file-loader').first()
  if ((await loader.count()) > 0) {
    uploadLog('youtube', 'cover', 'setInputFiles #file-loader accept=image/jpeg,image/png')
    await loader.setInputFiles(coverPath)
  } else {
    uploadLog('youtube', 'cover', 'fallback: button#select-button «Загрузить файл»')
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 8000 }).catch(() => null)
    await page.locator('button#select-button[aria-label="Загрузить файл"]').first().click({ timeout: 4000 })
    const chooser = await chooserPromise
    if (chooser) await chooser.setFiles(coverPath)
    else await page.locator('#file-loader').first().setInputFiles(coverPath)
  }

  const preview = page.locator('button#preview-button[aria-label*=".png"], button#preview-button[aria-label*=".jpg"], button#preview-button[aria-label*=".jpeg"]')
  await preview.first().waitFor({ state: 'visible', timeout: 30_000 })
  uploadLog('youtube', 'cover', `значок поставлен: ${await preview.first().getAttribute('aria-label')}`)
}

async function fillDetails(page: Page, payload: UploadPayload): Promise<void> {
  try {
    await fillFirst(page, ['#title-textarea #textbox', '#title-textarea textarea', '#textbox'], payload.title, 12_000)
  } catch {
    const titleBox = page.locator('#title-textarea #textbox').first()
    if (await titleBox.count()) {
      await titleBox.click()
      await page.keyboard.press('Control+A')
      await page.keyboard.type(payload.title, { delay: 8 })
    }
  }

  if (payload.description) {
    await fillFirst(page, ['#description-textarea #textbox', '#description-textarea textarea'], payload.description, 6000).catch(
      () => undefined
    )
  }

  const opts = payload.options as YoutubePublishOptions
  if (opts.madeForKids) {
    await clickIfPresent(page, ['tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_MFK"]'])
    await clickByName(page, I18N.madeForKidsYes, 1500)
  } else {
    await clickIfPresent(page, ['tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'])
    await clickByName(page, I18N.madeForKidsNo, 1500)
    await clickText(page, ["No, it's not made for kids", 'Нет, это не детский контент', 'Нет, это видео не для детей'], 1200)
  }

  if (opts.ageRestricted && !opts.madeForKids) {
    await clickIfPresent(page, ['tp-yt-paper-radio-button[name="VIDEO_AGE_RESTRICTION_SELF"]'])
  } else {
    await clickIfPresent(page, ['tp-yt-paper-radio-button[name="VIDEO_AGE_RESTRICTION_NONE"]'])
  }

  const needMore = opts.paidPromotion || opts.alteredContent || !opts.notifySubscribers
  if (needMore) {
    await clickIfPresent(page, [
      'button[aria-label*="Show more" i]',
      'button[aria-label*="Показать дополнительные" i]',
      'ytcp-button#toggle-button'
    ])
  }

  await setToggle(
    page,
    ['#checkbox[aria-label*="рекламу" i]', '#checkbox[aria-label*="paid promotion" i]', '#checkbox[aria-label*="спонсор" i]'],
    opts.paidPromotion
  )
  if (opts.alteredContent) {
    await clickIfPresent(page, ['tp-yt-paper-radio-button[name="VIDEO_HAS_ALTERED_CONTENT_YES"]'])
  } else if (needMore) {
    await clickIfPresent(page, ['tp-yt-paper-radio-button[name="VIDEO_HAS_ALTERED_CONTENT_NO"]'])
  }
  await setToggle(
    page,
    ['#checkbox[aria-label*="фиде подписок" i]', '#checkbox[aria-label*="subscriber" i]', '#checkbox[aria-label*="уведомление" i]'],
    opts.notifySubscribers
  )
}

const VIDEO_INPUT_QUERY = "input[type='file'][accept*='video'], input[type='file'][name='Filedata'], input[type='file']"
const SELECT_FILES =
  'ytcp-button#select-files-button button, #select-files-button button, button[aria-label="Выбрать файлы"], button[aria-label="Select files"]'
const ATTACHED_UI = '#title-textarea #textbox, #title-textarea textarea, ytcp-uploads-progress, ytcp-video-metadata-editor'

async function waitVideoAttached(page: Page, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await page.locator(ATTACHED_UI).first().isVisible().catch(() => false)) return true
    await sleep(200)
  }
  return false
}

/** Chrome по CDP читает файл сам. setInputFiles Playwright режет ролики больше 50 МБ. */
async function setFilesOnVideoInputs(cdp: CDPSession, filePath: string): Promise<boolean> {
  let searchId = ''
  try {
    const sr = (await cdp.send('DOM.performSearch', {
      query: VIDEO_INPUT_QUERY,
      includeUserAgentShadowDOM: true
    })) as { searchId?: string; resultCount?: number }
    searchId = sr.searchId || ''
    const total = Number(sr.resultCount || 0)
    if (!searchId || total <= 0) return false
    const got = (await cdp.send('DOM.getSearchResults', {
      searchId,
      fromIndex: 0,
      toIndex: Math.min(total, 40)
    })) as { nodeIds?: number[] }
    const video: number[] = []
    const rest: number[] = []
    for (const nid of (got.nodeIds || []).filter((id) => id > 0)) {
      try {
        const raw = (await cdp.send('DOM.getAttributes', { nodeId: nid })) as { attributes?: string[] }
        const attrs = raw.attributes || []
        const map: Record<string, string> = {}
        for (let i = 0; i < attrs.length - 1; i += 2) map[String(attrs[i]).toLowerCase()] = String(attrs[i + 1]).toLowerCase()
        const accept = map.accept || ''
        const name = map.name || ''
        if (accept.includes('video') || accept.includes('.mp4') || accept.includes('quicktime') || name === 'filedata') video.push(nid)
        else if (!accept.includes('image')) rest.push(nid)
      } catch {
        rest.push(nid)
      }
    }
    for (const nid of [...video, ...rest]) {
      try {
        await cdp.send('DOM.setFileInputFiles', { nodeId: nid, files: [filePath] })
        return true
      } catch {
        /* следующий input */
      }
    }
    return false
  } catch {
    return false
  } finally {
    if (searchId) await cdp.send('DOM.discardSearchResults', { searchId }).catch(() => undefined)
  }
}

async function attachYoutubeVideo(page: Page, videoPath: string): Promise<void> {
  const filePath = resolve(videoPath)
  if (!existsSync(filePath)) throw new Error(`Файл не найден: ${filePath}`)
  const mb = Math.max(1, Math.round(statSync(filePath).size / (1024 * 1024)))
  uploadLog('youtube', 'file', `${filePath} (${mb} МБ, CDP)`)

  const cdp = await page.context().newCDPSession(page)
  const opened: Array<{ backendNodeId?: number }> = []
  try {
    await cdp.send('DOM.enable')
    await cdp.send('Page.enable')
    cdp.on('Page.fileChooserOpened', (event: { backendNodeId?: number }) => {
      opened.push(event || {})
    })
    await cdp.send('Page.setInterceptFileChooserDialog', { enabled: true })

    await openUploadDialog(page)
    await page.locator(FILE_UI).first().waitFor({ state: 'attached', timeout: 15_000 })

    const fromClick = opened.at(-1)?.backendNodeId
    if (fromClick) {
      await cdp.send('DOM.setFileInputFiles', { backendNodeId: fromClick, files: [filePath] }).catch(() => undefined)
      if (await waitVideoAttached(page, 12_000)) {
        uploadLog('youtube', 'file', 'видео принято через CDP fileChooserOpened')
        return
      }
    }

    if ((await setFilesOnVideoInputs(cdp, filePath)) && (await waitVideoAttached(page, 12_000))) {
      uploadLog('youtube', 'file', 'видео принято через DOM.setFileInputFiles')
      return
    }

    const button = page.locator(SELECT_FILES).first()
    if ((await button.count().catch(() => 0)) > 0) {
      await button.click({ timeout: 4000, force: true }).catch(() => undefined)
      const deadline = Date.now() + 5000
      while (Date.now() < deadline && opened.length === 0) await sleep(80)
      const backendNodeId = opened.at(-1)?.backendNodeId
      if (backendNodeId) {
        await cdp.send('DOM.setFileInputFiles', { backendNodeId, files: [filePath] })
        if (await waitVideoAttached(page, 15_000)) {
          uploadLog('youtube', 'file', 'видео принято через кнопку «Выбрать файлы»')
          return
        }
      }
    }
  } finally {
    await cdp.send('Page.setInterceptFileChooserDialog', { enabled: false }).catch(() => undefined)
    await cdp.detach().catch(() => undefined)
  }

  if (mb < 45) {
    uploadLog('youtube', 'file', 'CDP не принял файл — пробую обычный выбор')
    await attachFile(page, filePath, [
      'ytcp-uploads-dialog input[name="Filedata"]',
      'input[name="Filedata"]',
      'ytcp-uploads-dialog input[type="file"]'
    ])
    return
  }
  throw new Error(`YouTube не принял видео ${mb} МБ. Браузер профиля открыт отдельно, обычная передача файла ограничена 50 МБ`)
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  const stopWatch = watchExtraPages(page)
  try {
    await armPrechecksPublishHandler(page)
    uploadLog('youtube', 'goto', STUDIO)
    await safeGoto(page, STUDIO)
    if ((await page.getByText(/ПЕРЕЙТИ В ПРИЛОЖЕНИЕ|Switch to app|unsupported browser/i).count()) > 0) {
      uploadLog('youtube', 'goto', 'approve_browser_access')
      await safeGoto(page, 'https://studio.youtube.com/?approve_browser_access=true')
    }
    await closeExtraPages(page)

    await attachYoutubeVideo(page, payload.videoPath)

    await page.locator('#title-textarea #textbox, #title-textarea textarea').first().waitFor({ state: 'visible', timeout: 45_000 })
    await fillDetails(page, payload)

    await waitYoutubeProcessed(page)

    uploadLog('youtube', 'cover', payload.coverPath ? payload.coverPath : 'без обложки')
    if (payload.coverPath) {
      await attachYoutubeCover(page, payload.coverPath)
    }
    await closeExtraPages(page)

    const opts = payload.options as YoutubePublishOptions
    for (let i = 0; i < 3; i++) {
      uploadLog('youtube', 'next', `шаг ${i + 1} из 3`)
      await clickNext(page)
      await closeExtraPages(page)
      await humanDelay(250, 500)
    }

    const visibilityName =
      opts.visibility === 'unlisted' ? 'UNLISTED' : opts.visibility === 'private' ? 'PRIVATE' : 'PUBLIC'
    uploadLog('youtube', 'visibility', opts.visibility)
    await clickIfPresent(page, [`tp-yt-paper-radio-button[name="${visibilityName}"]`])
    if (opts.visibility === 'public') await clickByName(page, I18N.public, 1500)
    if (opts.visibility === 'unlisted') await clickByName(page, I18N.unlisted, 1500)
    if (opts.visibility === 'private') await clickByName(page, I18N.private, 1500)

    if (!payload.dryRun) {
      uploadLog('youtube', 'publish', '#done-button')
      await confirmPublish(page)
      await humanDelay(800, 1400)
    } else {
      uploadLog('youtube', 'publish', 'dryRun — публикацию не нажимаю')
    }
    const url = await waitForPublicUrl(page, 'youtube', 40_000)
    uploadLog('youtube', 'done', url || page.url())
    return url || page.url()
  } catch (error) {
    uploadLogError('youtube', 'upload', error)
    throw error
  } finally {
    stopWatch()
    await closeExtraPages(page)
  }
}

export const youtubeAdapter: PlatformAdapter = { loginCheck, upload }
