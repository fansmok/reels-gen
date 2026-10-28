import type { Locator, Page } from 'playwright-core'
import {
  attachFile,
  clickByName,
  clickFirstOptional,
  dismissNuisances,
  fillFirst,
  humanDelay,
  I18N,
  looksLoggedOut,
  safeGoto,
  waitUntilEnabled,
  waitWhileBusy
} from './helpers'
import type { InstagramPublishOptions } from '../../shared/publish-options'
import type { PlatformAdapter, UploadPayload } from './types'
import { uploadLog, uploadLogError, uploadLogWindow } from './upload-log'

const PLATFORM = 'instagram'

const CREATE_ICONS = [
  'svg[aria-label="Новая публикация"]',
  '[aria-label="Новая публикация"]',
  'a[href="/create/select/"]',
  'a[href*="/create/"]',
  'svg[aria-label="New post"]',
  '[aria-label="New post"]',
  'svg[aria-label="Создать"]',
  '[aria-label="Создать"]',
  'svg[aria-label="Create"]',
  '[aria-label="Create"]',
  'svg[aria-label="Nueva publicación"]',
  '[aria-label="Nueva publicación"]',
  'svg[aria-label="Nouvelle publication"]',
  '[aria-label="Nouvelle publication"]',
  'svg[aria-label="Neuer Beitrag"]',
  '[aria-label="Neuer Beitrag"]',
  'svg[aria-label="Nuovo post"]',
  '[aria-label="Nuovo post"]',
  'svg[aria-label="Nova publicação"]',
  'svg[aria-label="Nowy post"]',
  'svg[aria-label="Yeni gönderi"]',
  'svg[aria-label="新しい投稿"]',
  'svg[aria-label="새 게시물"]',
  'svg[aria-label="新帖子"]',
  'svg[aria-label="Нова публікація"]',
  '[aria-label="Нова публікація"]'
]

const HOME_ICONS =
  'svg[aria-label="Home"], svg[aria-label="Главная"], svg[aria-label="Inicio"], svg[aria-label="Accueil"], svg[aria-label="Startseite"], svg[aria-label="Home page"]'
const LOGIN_FIELDS =
  'input[name="username"], input[name="email"], input[aria-label*="username" i], input[aria-label*="телефон" i], input[aria-label*="phone" i]'

const CROP_RE = /обрезать|crop|recortar|recadrer|zuschneiden|ritaglia/i
const CROP_ASPECT_SELECTOR =
  'svg[aria-label="Выбрать размер и обрезать"], svg[aria-label*="размер" i][aria-label*="обрез" i], svg[aria-label*="crop" i]'
const EDIT_RE = /редактировать|edit|editar|modifier|bearbeiten|фото обложки|cover photo/i
const DETAILS_RE = /новое видео|new reel|nuevo reel|nouveau reel|добавьте подпись|write a caption|caption|напишите подпись/i
const CREATE_DIALOG_RE =
  /создание публикации|create new post|créer une publication|nueva publicación|neue beitrag|перетащите сюда|select from computer|выбрать на компьютере|auswählen|choisir sur l'ordinateur/i
const REELS_INFO_RE = /делиться как видео reels|share as (a )?reel|видеопубликациями|reels video/i
const PROCESSING_RE =
  /обработк|обрабатывается|загрузк[аиеу]|загружается|uploading|processing|encoding|preparing|подготовк|please wait|подождите|осталось|sharing|публикуем/i
const READY_RE = /complete|готов|успешн|100\s*%|готово|reel shared|рилс опубликован/i
const SHARE_PROGRESS_RE =
  /sharing|публикуем|идёт публикация|идет публикация|your (reel|post|video) is being|sending (your )?(reel|post)|отправк[аеиу] публикац|reel is sharing|post is sharing/i
const SHARE_DONE_RE =
  /reel shared|post shared|(your )?(reel|post|video) has been shared|рилс опубликован|ролик опубликован|публикация отправлена|видео опубликовано|пост опубликован|your reel is now|shared to your|reel is live|you shared (a )?(reel|post)/i
const SHARE_SEE_RE = /see (reel|post)|view reel|смотреть (рилс|публикац|видео)|открыть рилс/i
const WIZARD_ERROR_RE =
  /не удалось|couldn't|could not|try again|что-то пошло не так|file too|слишком больш|unsupported|can't upload|не получилось/i
const JUNK_TAB_RE =
  /help\.instagram|instagram\.com\/help|instagram\.com\/ads|adsmanager|ads\.facebook|business\.facebook|about\.instagram|about\.meta|l\.instagram\.com|facebook\.com\/help|privacycenter|meta\.com\/help|\/legal\/|cookie.?policy|calendly|academy/i
const CREATE_MENU_RE = /^(post|публикаци[яю]|reel|рилс|reels|nueva publicaci[oó]n|nouveau|neuer beitrag|nuovo post)$/i
const NOTIF_RE = /turn on notif|включить уведомлен|notifications|push.?notif/i
const COOKIE_RE = /cookie|файлы cookie|cookies/i

const extraPagesArmed = new WeakSet<object>()

type WizardStep = 'select' | 'reels-info' | 'crop' | 'edit' | 'caption' | 'unknown'

function wizard(page: Page): Locator {
  return page.locator('[role="dialog"]').last()
}

async function wizardText(page: Page): Promise<string> {
  const root = wizard(page)
  const heading = await root.locator('h1, [role="heading"]').first().innerText().catch(() => '')
  const body = await root.innerText().catch(() => '')
  return `${heading}\n${body}`
}

async function wizardHeading(page: Page): Promise<string> {
  return wizard(page).locator('h1, [role="heading"]').first().innerText().catch(() => '')
}

function isJunkTab(url: string): boolean {
  return JUNK_TAB_RE.test(url)
}

async function closeJunkTabs(page: Page): Promise<void> {
  if (page.isClosed()) return
  for (const opened of page.context().pages()) {
    if (opened === page || opened.isClosed()) continue
    const url = opened.url()
    if (!url || url === 'about:blank' || url === 'about:srcdoc') continue
    if (isJunkTab(url)) {
      uploadLogWindow(PLATFORM, url, 'closed')
      await opened.close().catch(() => undefined)
    }
  }
}

function armExtraPages(page: Page): void {
  const ctx = page.context()
  if (extraPagesArmed.has(ctx)) return
  extraPagesArmed.add(ctx)
  ctx.on('page', (opened) => {
    void (async () => {
      await opened.waitForLoadState('domcontentloaded').catch(() => undefined)
      await opened.waitForURL((u) => u.href !== 'about:blank', { timeout: 8000 }).catch(() => undefined)
      if (opened.isClosed() || page.isClosed()) return
      const url = opened.url()
      uploadLogWindow(PLATFORM, url, 'opened')
      if (opened === page) {
        uploadLogWindow(PLATFORM, url, 'ignored')
        return
      }
      if (isJunkTab(url)) {
        await opened.close().catch(() => undefined)
        uploadLogWindow(PLATFORM, url, 'closed')
        return
      }
      uploadLogWindow(PLATFORM, url, 'ignored')
    })()
  })
}

async function dismissIg(page: Page): Promise<void> {
  if (page.isClosed()) return
  await dismissNuisances(page)

  const cookieDlg = page.getByRole('dialog').filter({ hasText: COOKIE_RE }).first()
  if (await cookieDlg.isVisible().catch(() => false)) {
    const accept = cookieDlg.getByRole('button', { name: I18N.acceptCookies }).first()
    if (await accept.isVisible().catch(() => false)) {
      await accept.click({ timeout: 1500 }).catch(() => undefined)
      uploadLog(PLATFORM, 'dismiss', 'cookies')
    }
  }

  const notifDlg = page.getByRole('dialog').filter({ hasText: NOTIF_RE }).first()
  if (await notifDlg.isVisible().catch(() => false)) {
    const notNow = notifDlg.getByRole('button', { name: I18N.notNow }).first()
    if (await notNow.isVisible().catch(() => false)) {
      await notNow.click({ timeout: 1500 }).catch(() => undefined)
      uploadLog(PLATFORM, 'dismiss', 'уведомления — Not now')
    }
  }

  const notNow = page.getByRole('button', { name: I18N.notNow }).first()
  if (await notNow.isVisible().catch(() => false)) {
    const label = `${await notNow.innerText().catch(() => '')}`.trim()
    if (!/share|поделить|опублик|next|далее/i.test(label)) {
      await notNow.click({ timeout: 1200 }).catch(() => undefined)
      uploadLog(PLATFORM, 'dismiss', label || 'Not now')
    }
  }

  await closeJunkTabs(page)
}

async function armIgHandlers(page: Page): Promise<void> {
  try {
    await page.addLocatorHandler(page.getByRole('dialog').filter({ hasText: COOKIE_RE }).first(), async () => {
      await dismissIg(page)
    })
    await page.addLocatorHandler(page.getByRole('dialog').filter({ hasText: NOTIF_RE }).first(), async () => {
      await dismissIg(page)
    })
    await page.addLocatorHandler(page.getByRole('button', { name: I18N.notNow }).first(), async () => {
      await dismissIg(page)
    })
  } catch {
    /* нет addLocatorHandler */
  }
}

async function detectStep(page: Page): Promise<WizardStep> {
  const root = wizard(page)
  if (await captionBox(page).isVisible().catch(() => false)) return 'caption'
  if (await root.getByRole('button', { name: I18N.share }).first().isVisible().catch(() => false)) return 'caption'
  const text = await wizardText(page)
  if (REELS_INFO_RE.test(text)) return 'reels-info'
  if (EDIT_RE.test(text) && (await root.getByText(/фото обложки|cover photo|cover/i).first().isVisible().catch(() => false))) {
    return 'edit'
  }
  if (EDIT_RE.test(text) && !CROP_RE.test(await wizardHeading(page))) return 'edit'
  if (CROP_RE.test(text)) return 'crop'
  if (DETAILS_RE.test(text)) return 'caption'
  if (CREATE_DIALOG_RE.test(text)) return 'select'
  return 'unknown'
}

function captionBox(page: Page): Locator {
  return wizard(page)
    .locator(
      'div[role="textbox"][aria-label*="подпис" i], div[role="textbox"][aria-label*="caption" i], textarea[aria-label*="caption" i], textarea[aria-label*="подпис" i], div[aria-label*="caption" i][contenteditable="true"]'
    )
    .first()
}

async function wizardBusy(page: Page): Promise<boolean> {
  const text = await wizardText(page)
  if (WIZARD_ERROR_RE.test(text) && !PROCESSING_RE.test(text) && !SHARE_PROGRESS_RE.test(text)) return false
  if (SHARE_DONE_RE.test(text)) return false
  if ((PROCESSING_RE.test(text) || SHARE_PROGRESS_RE.test(text)) && !READY_RE.test(text) && !SHARE_DONE_RE.test(text)) {
    return true
  }
  const bar = wizard(page).locator(
    '[role="progressbar"], [aria-label*="загруз" i], [aria-label*="load" i], [aria-label*="process" i], [aria-label*="обработ" i], [aria-label*="shar" i], [aria-label*="публик" i]'
  )
  if (await bar.first().isVisible().catch(() => false)) {
    const barText = `${await bar.first().getAttribute('aria-label').catch(() => '')} ${await bar.first().innerText().catch(() => '')}`
    if (!READY_RE.test(barText) && !SHARE_DONE_RE.test(barText)) return true
  }
  return false
}

async function wizardHasMedia(page: Page): Promise<boolean> {
  const root = wizard(page)
  const video = root.locator('video').first()
  if (await video.isVisible().catch(() => false)) {
    return video
      .evaluate((el) => {
        const v = el as HTMLVideoElement
        return v.readyState >= 2 && v.videoWidth > 0
      })
      .catch(() => false)
  }
  const step = await detectStep(page)
  if (step === 'crop' || step === 'edit') {
    return root.locator('canvas').first().isVisible().catch(() => false)
  }
  return false
}

async function nextButton(page: Page): Promise<Locator> {
  return wizard(page).getByRole('button', { name: I18N.next }).first()
}

async function nextEnabled(page: Page): Promise<boolean> {
  const next = await nextButton(page)
  if (!(await next.isVisible().catch(() => false))) return false
  if (await next.isDisabled().catch(() => false)) return false
  if ((await next.getAttribute('aria-disabled').catch(() => null)) === 'true') return false
  const style = await next
    .evaluate((el) => {
      const s = getComputedStyle(el)
      return { opacity: s.opacity, pe: s.pointerEvents }
    })
    .catch(() => ({ opacity: '1', pe: 'auto' }))
  if (Number(style.opacity) < 0.45 || style.pe === 'none') return false
  return true
}

async function waitWizardIdle(page: Page, timeout = 180_000): Promise<void> {
  const deadline = Date.now() + timeout
  let idleHits = 0
  let lastNote = 0
  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await dismissIg(page)
    const busy = await wizardBusy(page)
    const step = await detectStep(page)
    const media = await wizardHasMedia(page)
    const caption = step === 'caption'
    const nextOk = (await nextEnabled(page)) || caption
    if (!busy && nextOk && (media || caption || step === 'reels-info')) {
      idleHits += 1
      if (idleHits >= 3) {
        uploadLog(PLATFORM, 'wait-processing', `готово, шаг ${step}`)
        return
      }
    } else {
      idleHits = 0
      if (Date.now() - lastNote > 4000) {
        lastNote = Date.now()
        const head = (await wizardHeading(page)).slice(0, 80)
        uploadLog(PLATFORM, 'wait-processing', busy ? `обработка… ${head}` : `ждём медиа, шаг ${step}`)
      }
    }
    await humanDelay(400, 700)
  }
  throw new Error('Instagram не обработал видео. Дождитесь готовности ролика в мастере и повторите.')
}

async function waitWizard(page: Page, re: RegExp, timeout = 20_000): Promise<boolean> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    await dismissIg(page)
    if (re.test(await wizardText(page))) return true
    await humanDelay(80, 140)
  }
  return false
}

async function clickWizardNextWhenReady(page: Page, timeout = 180_000): Promise<boolean> {
  await waitWizardIdle(page, timeout)
  const root = wizard(page)
  const ok = root.getByRole('button', { name: /^ok$/i }).first()
  if (await ok.isVisible().catch(() => false)) {
    await ok.click({ timeout: 4000 }).catch(() => ok.click({ force: true }))
    uploadLog(PLATFORM, 'wizard-next', 'OK')
    return true
  }
  const next = await nextButton(page)
  if (await next.isVisible().catch(() => false)) {
    if (!(await nextEnabled(page))) {
      uploadLog(PLATFORM, 'wizard-next', 'Далее ещё неактивна')
      await waitWizardIdle(page, timeout)
    }
    if (await wizardBusy(page)) {
      uploadLog(PLATFORM, 'wizard-next', 'пропуск: ролик ещё обрабатывается')
      return false
    }
    await next.click({ timeout: 4000 }).catch(() => next.click({ force: true }))
    uploadLog(PLATFORM, 'wizard-next', (await wizardHeading(page)).slice(0, 80))
    return true
  }
  return false
}

async function selectPortraitAspect(page: Page): Promise<void> {
  const cropIcon = wizard(page).locator(CROP_ASPECT_SELECTOR).first()
  await cropIcon.waitFor({ state: 'visible', timeout: 15_000 })

  const cropButton = cropIcon.locator('xpath=ancestor::*[@role="button"][1]')
  uploadLog(PLATFORM, 'crop-aspect', 'открываю «Выбрать размер и обрезать»')
  if ((await cropButton.count().catch(() => 0)) > 0) {
    await cropButton.click({ timeout: 5000 }).catch(() => cropIcon.click({ force: true }))
  } else {
    await cropIcon.click({ timeout: 5000 }).catch(() => cropIcon.click({ force: true }))
  }
  await humanDelay(250, 500)

  const ratioText = page.getByText('9:16', { exact: true }).last()
  await ratioText.waitFor({ state: 'visible', timeout: 10_000 })
  const ratioButton = ratioText.locator('xpath=ancestor::*[@role="button"][1]')
  if ((await ratioButton.count().catch(() => 0)) > 0) {
    await ratioButton.click({ timeout: 5000 }).catch(() => ratioText.click({ force: true }))
  } else {
    await ratioText.click({ timeout: 5000 }).catch(() => ratioText.click({ force: true }))
  }
  await humanDelay(400, 700)
  uploadLog(PLATFORM, 'crop-aspect', 'выбрано 9:16')
}

async function setLabeledSwitch(page: Page, label: RegExp, on: boolean): Promise<boolean> {
  const text = wizard(page).getByText(label).first()
  if (!(await text.isVisible().catch(() => false))) return false
  const row = text.locator('xpath=ancestor::*[.//*[@role="switch"] or .//input[@type="checkbox"]][1]')
  const control = (await row.getByRole('switch').count())
    ? row.getByRole('switch').first()
    : row.locator('input[type="checkbox"]').first()
  const current = await control.isChecked().catch(() => !on)
  if (current === on) return true
  await control.click({ timeout: 4000, force: true }).catch(() => undefined)
  return true
}

async function waitReady(page: Page): Promise<void> {
  await page
    .locator(`${LOGIN_FIELDS}, ${HOME_ICONS}, ${CREATE_ICONS.join(', ')}`)
    .first()
    .waitFor({ state: 'visible', timeout: 25_000 })
    .catch(() => undefined)
}

async function throwIfWizardError(page: Page): Promise<void> {
  const text = await wizardText(page)
  if (WIZARD_ERROR_RE.test(text) && !PROCESSING_RE.test(text) && !SHARE_PROGRESS_RE.test(text)) {
    const snippet = text.replace(/\s+/g, ' ').trim().slice(0, 160)
    uploadLogError(PLATFORM, 'wizard-error', snippet)
    throw new Error(`Instagram не принял видео: ${snippet}`)
  }
}

async function nativeClick(locator: Locator): Promise<boolean> {
  const handle = await locator.elementHandle().catch(() => null)
  if (!handle) return false
  await handle.evaluate((el) => (el as HTMLElement).click())
  return true
}

function shareBtn(page: Page): Locator {
  return wizard(page).getByRole('button', { name: I18N.share }).first()
}

async function pageLooksShared(page: Page): Promise<boolean> {
  const heading = (await wizardHeading(page)).trim()
  if (/^(reel shared|post shared|рилс опубликован|публикация отправлена)$/i.test(heading)) return true
  const blob = `${heading}\n${await wizardText(page)}`
  if (SHARE_DONE_RE.test(blob)) return true
  const see = page.getByRole('link', { name: SHARE_SEE_RE }).or(page.getByRole('button', { name: SHARE_SEE_RE })).first()
  if (await see.isVisible().catch(() => false)) return true
  if (await page.getByText(SHARE_DONE_RE).first().isVisible().catch(() => false)) return true
  return false
}

async function stillSharing(page: Page): Promise<boolean> {
  if (await wizardBusy(page)) return true
  const heading = (await wizardHeading(page)).trim()
  if (/^(sharing|публикуем|публикация)$/i.test(heading)) return true
  return SHARE_PROGRESS_RE.test(await wizardText(page))
}

async function publishedHrefs(page: Page): Promise<string[]> {
  const hrefs = await page
    .locator('a[href]')
    .evaluateAll((els) =>
      els
        .map((el) => (el as HTMLAnchorElement).href)
        .filter((href) => /instagram\.com\/(?:reel|p)\/[A-Za-z0-9_-]+/i.test(href) && !/\/reels\/?$/i.test(href))
    )
    .catch(() => [] as string[])
  const current = page.url()
  if (/instagram\.com\/(?:reel|p)\/[A-Za-z0-9_-]+/i.test(current)) hrefs.unshift(current)
  return [...new Set(hrefs.map((href) => href.split('?')[0]))]
}

async function publishedHref(page: Page, known: Set<string>): Promise<string | undefined> {
  return (await publishedHrefs(page)).find((href) => !known.has(href))
}

async function clickShare(page: Page): Promise<void> {
  const btn = shareBtn(page)
  if (!(await btn.isVisible().catch(() => false))) {
    const clicked = await clickByName(page, I18N.share, 8000)
    if (!clicked) throw new Error('Не найдена кнопка «Поделиться» в Instagram')
    return
  }
  await waitUntilEnabled(btn, 180_000)
  uploadLog(PLATFORM, 'share', 'native click Поделиться / Share')
  const clicked =
    (await nativeClick(btn)) ||
    (await btn
      .click({ timeout: 8000 })
      .then(() => true)
      .catch(() => false))
  if (!clicked) throw new Error('Не нажалась кнопка «Поделиться» в Instagram')
}

async function waitShareComplete(page: Page, known: Set<string>): Promise<string | undefined> {
  uploadLog(PLATFORM, 'share', 'ждём загрузку ролика и публикацию')
  const started = Date.now()
  const deadline = started + 600_000
  let sawSharing = false
  let lastNote = 0
  let lastRetry = 0
  let retried = 0
  let quietHits = 0

  while (Date.now() < deadline) {
    if (page.isClosed()) throw new Error('Окно браузера закрыто')
    await dismissIg(page)
    await throwIfWizardError(page)

    const sharing = await stillSharing(page)
    if (sharing) {
      sawSharing = true
      quietHits = 0
    }

    const heading = (await wizardHeading(page)).trim()
    const sharedScreen =
      (await pageLooksShared(page)) ||
      (sawSharing && /^(done|готово|reel shared|post shared)$/i.test(heading))

    if (sharedScreen && !sharing) {
      uploadLog(PLATFORM, 'share', 'рилс опубликован')
      const done = wizard(page).getByRole('button', { name: I18N.done }).first()
      if (await done.isVisible().catch(() => false)) {
        await nativeClick(done).catch(() => undefined)
      }
      await humanDelay(1200, 1800)
      return await publishedHref(page, known)
    }

    if (sharing && Date.now() - lastNote > 5000) {
      lastNote = Date.now()
      uploadLog(PLATFORM, 'share', `загрузка/публикация… ${heading.slice(0, 80)}`)
    }

    const shareVisible = await shareBtn(page).isVisible().catch(() => false)
    const stillCaption = (await detectStep(page)) === 'caption' && shareVisible
    if (!sharing && !sawSharing && stillCaption && Date.now() - started > 5000 && retried < 3 && Date.now() - lastRetry > 5000) {
      retried += 1
      lastRetry = Date.now()
      uploadLog(PLATFORM, 'share', `повторный клик Поделиться (${retried})`)
      await clickShare(page)
    }

    if (sawSharing && !sharing && !shareVisible) {
      quietHits += 1
      if (quietHits >= 5) {
        uploadLog(PLATFORM, 'share', 'загрузка стихла, публикация прошла')
        await humanDelay(800, 1200)
        return await publishedHref(page, known)
      }
    }

    if (sawSharing && !(await wizard(page).isVisible().catch(() => false))) {
      uploadLog(PLATFORM, 'share', 'мастер закрылся — публикация прошла')
      await humanDelay(800, 1200)
      return await publishedHref(page, known)
    }

    await humanDelay(400, 700)
  }

  throw new Error(
    'Instagram не закончил публикацию рилса. Окно нельзя закрывать, пока на экране идёт загрузка и не появится «опубликовано».'
  )
}

async function openCreate(page: Page): Promise<void> {
  uploadLog(PLATFORM, 'create', 'клик «Новая публикация» / Create')
  const createClicked =
    (await clickFirstOptional(page, CREATE_ICONS)) || (await clickByName(page, I18N.newPost, 5000))
  if (!createClicked) throw new Error('Не найдена кнопка «Новая публикация» в Instagram')
  await humanDelay(500, 900)

  const menuItem = page.getByRole('menuitem', { name: CREATE_MENU_RE }).first()
  if (await menuItem.isVisible().catch(() => false)) {
    uploadLog(PLATFORM, 'create-menu', (await menuItem.innerText().catch(() => 'Post')).slice(0, 40))
    await menuItem.click({ timeout: 4000 }).catch(() => menuItem.click({ force: true }))
    await humanDelay(400, 800)
  }

  if (await waitWizard(page, CREATE_DIALOG_RE, 10_000)) {
    uploadLog(PLATFORM, 'create-dialog', await wizardHeading(page))
    return
  }

  uploadLog(PLATFORM, 'create', 'диалог не открылся — повторный клик')
  await clickByName(page, I18N.newPost, 4000)
  await humanDelay(500, 900)
  if (!(await waitWizard(page, CREATE_DIALOG_RE, 12_000))) {
    throw new Error('Не открылось окно создания публикации в Instagram')
  }
  uploadLog(PLATFORM, 'create-dialog', await wizardHeading(page))
}

async function listWizardFiles(page: Page): Promise<Array<{ i: number; accept: string; aria: string }>> {
  return page.evaluate(() =>
    [...document.querySelectorAll('input[type="file"]')].map((el, i) => ({
      i,
      accept: el.getAttribute('accept') || '',
      aria: el.getAttribute('aria-label') || ''
    }))
  )
}

function jpegCoverInput(page: Page): Locator {
  return page.locator(
    'input[type="file"][accept="image/jpeg,image/png"], input[type="file"][accept="image/png,image/jpeg"], input[type="file"][accept*="image/jpeg"][accept*="image/png"]'
  )
}

async function attachCoverOnEdit(page: Page, coverPath: string): Promise<void> {
  uploadLog(PLATFORM, 'cover', 'шаг edit — Фото обложки / cover photo')
  const root = wizard(page)
  const filesBefore = await listWizardFiles(page)
  uploadLog(PLATFORM, 'cover-inputs', JSON.stringify(filesBefore))

  const coverOpen = root
    .getByRole('button', { name: /фото обложки|cover photo|edit cover|обложк/i })
    .or(root.getByRole('tab', { name: /фото обложки|cover photo|обложк/i }))
    .first()
  if (await coverOpen.isVisible().catch(() => false)) {
    await coverOpen.click({ timeout: 4000 }).catch(() => coverOpen.click({ force: true }))
    uploadLog(PLATFORM, 'cover', 'клик «Фото обложки»')
    await humanDelay(500, 900)
  } else {
    const text = root.getByText(/фото обложки|cover photo/i).first()
    if (await text.isVisible().catch(() => false)) {
      await text.click({ timeout: 3000 }).catch(() => undefined)
      uploadLog(PLATFORM, 'cover', 'клик текста «Фото обложки»')
      await humanDelay(500, 900)
    }
  }

  const jpeg = jpegCoverInput(page)
  const jpegCount = await jpeg.count()
  uploadLog(PLATFORM, 'cover-inputs', `jpeg/png inputs=${jpegCount} after tab`)
  if (jpegCount > 0) {
    await jpeg.last().setInputFiles(coverPath)
    uploadLog(PLATFORM, 'cover', 'setInputFiles accept=image/jpeg,image/png')
  } else {
    const onCoverUi = /фото обложки|cover photo|редактировать|^edit$/i.test(await wizardText(page))
    if (!onCoverUi) {
      uploadLog(PLATFORM, 'cover', 'нет jpeg input и не шаг обложки — не жму «Выбрать на компьютере» (это видео)')
    } else {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 12_000 }).catch(() => null)
    const pick = root
      .getByRole('button', { name: /выбрать на компьютере|select from computer|upload (from |a )?computer|загрузить с компьютера/i })
      .last()
    const pickText = root.getByText(/выбрать на компьютере|select from computer/i).last()
    const opened =
      (await pick.isVisible().catch(() => false)
        ? await pick.click({ timeout: 4000 }).then(() => true).catch(() => false)
        : false) ||
      (await pickText.isVisible().catch(() => false)
        ? await pickText.click({ timeout: 4000 }).then(() => true).catch(() => false)
        : false)
    const chooser = await chooserPromise
    if (chooser) {
      const accept = await chooser
        .element()
        .getAttribute('accept')
        .catch(() => '')
      uploadLog(PLATFORM, 'cover', `filechooser accept=${accept || '?'}`)
      await chooser.setFiles(coverPath)
      uploadLog(PLATFORM, 'cover', 'обложка через filechooser после «Фото обложки»')
    } else {
      uploadLog(PLATFORM, 'cover', opened ? 'chooser не открылся' : 'нет jpeg input и кнопки выбора')
    }
    }
  }

  await humanDelay(800, 1400)
  const done = wizard(page).getByRole('button', { name: I18N.done }).first()
  if (await done.isVisible().catch(() => false)) {
    await done.click({ timeout: 4000 }).catch(() => undefined)
    uploadLog(PLATFORM, 'cover', 'Готово')
  }
  await humanDelay(400, 800)
}

async function loginCheck(page: Page): Promise<boolean> {
  armExtraPages(page)
  await armIgHandlers(page)
  uploadLog(PLATFORM, 'login-check', 'открываю instagram.com')
  await safeGoto(page, 'https://www.instagram.com/')
  await waitReady(page)
  await dismissIg(page)
  if (looksLoggedOut(page.url()) || page.url().includes('/accounts/login')) {
    uploadLog(PLATFORM, 'login-check', 'не вошёл')
    return false
  }
  if ((await page.locator(LOGIN_FIELDS).count()) > 0 && (await page.locator(HOME_ICONS).count()) === 0) {
    uploadLog(PLATFORM, 'login-check', 'форма входа')
    return false
  }
  const create = page.locator(CREATE_ICONS.join(', ')).first()
  const home = page.locator(HOME_ICONS).first()
  const ok = (await create.count()) > 0 || (await home.count()) > 0
  uploadLog(PLATFORM, 'login-check', ok ? 'сессия есть' : 'нет иконок ленты')
  return ok
}

async function upload(page: Page, payload: UploadPayload): Promise<string | undefined> {
  armExtraPages(page)
  await armIgHandlers(page)
  try {
    uploadLog(PLATFORM, 'goto', 'https://www.instagram.com/')
    await safeGoto(page, 'https://www.instagram.com/')
    await waitReady(page)
    await dismissIg(page)
    if (looksLoggedOut(page.url()) || (await page.locator(LOGIN_FIELDS).count()) > 0) {
      throw new Error('Instagram не вошёл в аккаунт. Откройте «Аккаунты» и нажмите «Войти».')
    }

    await openCreate(page)
    await dismissIg(page)

    uploadLog(PLATFORM, 'file', payload.videoPath)
    await attachFile(page, payload.videoPath, [
      'input[type="file"][accept*="video"]',
      'input[type="file"]',
      'button:has-text("Select from computer")',
      'button:has-text("Выбрать на компьютере")'
    ])
    await waitWhileBusy(page, 180_000)
    await throwIfWizardError(page)
    await waitWizardIdle(page, 180_000)
    await humanDelay(400, 800)

    if ((await detectStep(page)) === 'reels-info' || REELS_INFO_RE.test(await wizardText(page))) {
      uploadLog(PLATFORM, 'wizard-step', 'reels-info')
      await clickWizardNextWhenReady(page)
      await humanDelay(600, 1000)
      await waitWizardIdle(page, 180_000)
    }

    const afterFile = await detectStep(page)
    uploadLog(PLATFORM, 'wizard-step', afterFile)
    if (afterFile === 'select' || afterFile === 'unknown') {
      if (!(await waitWizard(page, new RegExp(`${CROP_RE.source}|${EDIT_RE.source}|${DETAILS_RE.source}`, 'i'), 60_000))) {
        await throwIfWizardError(page)
        throw new Error('Instagram не открыл мастер обрезки после загрузки видео')
      }
    }

    await waitWizardIdle(page, 180_000)
    await throwIfWizardError(page)

    const cropControlVisible = await wizard(page)
      .locator(CROP_ASPECT_SELECTOR)
      .first()
      .isVisible()
      .catch(() => false)
    if ((await detectStep(page)) === 'crop' || cropControlVisible) {
      uploadLog(PLATFORM, 'wizard-step', 'crop')
      await selectPortraitAspect(page)
      await waitWizardIdle(page, 180_000)
      if (!(await clickWizardNextWhenReady(page))) throw new Error('Не найдена кнопка «Далее» на шаге обрезки')
      await humanDelay(600, 1000)
      await waitWizardIdle(page, 180_000)
    }

    let step = await detectStep(page)
    if (step !== 'edit' && step !== 'caption') {
      const deadline = Date.now() + 20_000
      while (Date.now() < deadline) {
        step = await detectStep(page)
        if (step === 'edit' || step === 'caption') break
        await humanDelay(200, 400)
      }
    }

    if (step === 'edit') {
      uploadLog(PLATFORM, 'wizard-step', 'edit')
      await waitWizardIdle(page, 180_000)
      uploadLog(PLATFORM, 'edit-inputs', JSON.stringify(await listWizardFiles(page)))
      if (payload.coverPath) {
        await attachCoverOnEdit(page, payload.coverPath)
      } else {
        uploadLog(PLATFORM, 'cover', 'нет файла обложки')
      }
      if (!(await clickWizardNextWhenReady(page))) throw new Error('Не найдена кнопка «Далее» на шаге обложки')
      await humanDelay(600, 1000)
    } else if (step === 'caption') {
      uploadLog(PLATFORM, 'wizard-step', 'edit пропущен, сразу подпись')
    }

    if ((await detectStep(page)) !== 'caption') {
      if (!(await waitWizard(page, DETAILS_RE, 20_000)) && !(await captionBox(page).isVisible().catch(() => false))) {
        throw new Error('Instagram не открыл экран подписи рилса')
      }
    }
    uploadLog(PLATFORM, 'wizard-step', 'caption')
    await waitWizardIdle(page, 60_000)

    const caption = (payload.description || '').trim()
    uploadLog(PLATFORM, 'caption', caption.slice(0, 80))
    if (caption) {
      await fillFirst(
        page,
        [
          'div[role="textbox"][aria-label*="подпис" i]',
          'div[role="textbox"][aria-label*="caption" i]',
          'textarea[aria-label*="caption" i]',
          'textarea[aria-label*="подпис" i]',
          'div[aria-label*="caption" i][contenteditable="true"]',
          'div[role="textbox"]'
        ],
        caption
      ).catch(() => undefined)
    }

    const advanced = wizard(page)
      .getByRole('button', { name: /расширенные настройки|advanced settings|ajustes avanzados|paramètres avancés/i })
      .first()
    if (await advanced.isVisible().catch(() => false)) {
      await advanced.click({ timeout: 4000 }).catch(() => undefined)
      uploadLog(PLATFORM, 'settings', 'расширенные настройки')
      await humanDelay(400, 800)
    }

    const opts = payload.options as InstagramPublishOptions
    await setLabeledSwitch(page, /выключить комментарии|turn off commenting|disable comments/i, !opts.comments)
    await setLabeledSwitch(page, /также поделиться в ленте|also share (to|on) (the )?feed|share to feed/i, opts.shareToFeed)

    await humanDelay()
    await dismissIg(page)
    if (payload.dryRun) {
      uploadLog(PLATFORM, 'share', 'dryRun — «Поделиться» не нажимаем')
      return page.url()
    }

    await waitWizardIdle(page, 180_000)
    await throwIfWizardError(page)
    const knownPublished = new Set(await publishedHrefs(page))
    await clickShare(page)
    uploadLog(PLATFORM, 'share', 'нажато, не закрываем Chrome пока рилс не уйдёт')
    const url = await waitShareComplete(page, knownPublished)
    uploadLog(PLATFORM, 'share', url || 'опубликовано')
    return url
  } catch (error) {
    uploadLogError(PLATFORM, 'upload', error)
    throw error
  }
}

export const instagramAdapter: PlatformAdapter = { loginCheck, upload }
