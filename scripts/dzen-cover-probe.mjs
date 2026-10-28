import { mkdirSync, writeFileSync, readdirSync } from 'fs'
import { join } from 'path'
import { chromium } from 'playwright-core'

const ROOT = 'C:\\Users\\faans\\Desktop\\РИЛС-ЗАГРУЗКА'
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'dzen')
const OUT = join(ROOT, 'scripts', 'dzen-cover.json')
const VIDEO = join(ROOT, readdirSync(ROOT).find((n) => n.toLowerCase().endsWith('.mp4')))
const COVER = join(ROOT, 'test-cover.png')
const PUBLISH_RE = /^(опубликовать|publish|выложить|поделиться)$/i
const BUSY_RE = /загрузк[аиеу]|загружается|обработк[аиеу]|обрабатывается|uploading|processing|кодирован|конвертац|осталось/i

const dump = {
  video: VIDEO,
  cover: COVER,
  session: SESSION,
  published: false,
  steps: [],
  findings: {},
  error: null
}

function save() {
  mkdirSync(join(ROOT, 'scripts'), { recursive: true })
  writeFileSync(OUT, JSON.stringify(dump, null, 2), 'utf-8')
}

async function collect(page) {
  return page.evaluate(() => {
    const attrs = (el) => {
      const html = el
      const cs = window.getComputedStyle(html)
      return {
        tag: html.tagName.toLowerCase(),
        id: html.id || null,
        name: html.getAttribute('name'),
        type: html.getAttribute('type'),
        accept: html.getAttribute('accept'),
        aria: html.getAttribute('aria-label'),
        test: html.getAttribute('data-testid') || html.getAttribute('data-test-id') || html.getAttribute('data-e2e'),
        placeholder: html.getAttribute('placeholder'),
        role: html.getAttribute('role'),
        href: html.getAttribute('href'),
        disabled: Boolean(html.disabled) || html.getAttribute('aria-disabled') === 'true',
        hidden: cs.display === 'none' || cs.visibility === 'hidden' || html.getClientRects().length === 0,
        cls: String(html.className || '').slice(0, 160),
        text: (html.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 140)
      }
    }
    const fileInputs = [...document.querySelectorAll('input[type="file"]')].map(attrs)
    const buttons = [...document.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="option"]')]
      .map(attrs)
      .filter((x) => x.text || x.aria || x.test)
      .slice(0, 220)
    const fields = [...document.querySelectorAll('input, textarea, [contenteditable="true"]')]
      .map(attrs)
      .filter((x) => x.type !== 'hidden')
      .slice(0, 80)
    const coverish = [...document.querySelectorAll('button, a, [role="button"], [role="menuitem"], label, input, img, [data-testid], [class*="cover" i], [class*="Cover"], [class*="thumb" i]')]
      .filter((el) => {
        const blob = `${el.getAttribute('aria-label') || ''} ${el.innerText || ''} ${el.getAttribute('data-testid') || ''} ${el.getAttribute('accept') || ''} ${el.className || ''} ${el.getAttribute('alt') || ''}`.toLowerCase()
        return /облож|cover|thumb|заставк|кадр|preview|poster|image|картинк|png|jpeg|jpg|фото/.test(blob)
      })
      .slice(0, 80)
      .map(attrs)
    const coverLabels = [...document.querySelectorAll('h1,h2,h3,h4,h5,label,span,div,p,button')]
      .filter((el) => /облож/i.test(el.innerText || '') && (el.innerText || '').trim().length < 90)
      .slice(0, 25)
      .map((el) => ({
        ...attrs(el),
        parentTest: el.parentElement?.getAttribute('data-testid') || el.parentElement?.getAttribute('data-test-id'),
        parentCls: String(el.parentElement?.className || '').slice(0, 120),
        html: el.outerHTML.slice(0, 500)
      }))
    return {
      url: location.href,
      title: document.title,
      fileInputs,
      buttons,
      fields,
      coverish,
      coverLabels
    }
  })
}

async function snap(page, name, extra = {}) {
  const data = await collect(page).catch((error) => ({ error: String(error), url: page.url() }))
  dump.steps.push({ name, at: new Date().toISOString(), ...data, ...extra })
  save()
  console.log(`[dzen-probe] ${name} | ${page.url()}`)
}

async function clickSafe(page, texts, { exact = false, timeout = 6000 } = {}) {
  for (const text of texts) {
    const btn = page.getByRole('button', exact ? { name: text, exact: true } : { name: new RegExp(text, 'i') }).first()
    if (await btn.isVisible({ timeout: 800 }).catch(() => false)) {
      const label = `${await btn.innerText().catch(() => '')} ${await btn.getAttribute('aria-label')}`.trim()
      if (PUBLISH_RE.test(label)) {
        console.log(`[dzen-probe] SKIP publish-like: ${label}`)
        continue
      }
      await btn.click({ timeout }).catch(() => btn.click({ force: true }))
      return text
    }
    const byText = page.getByText(text, { exact }).first()
    if (await byText.isVisible({ timeout: 500 }).catch(() => false)) {
      const label = (await byText.innerText().catch(() => '')).trim()
      if (PUBLISH_RE.test(label)) continue
      await byText.click({ timeout }).catch(() => byText.click({ force: true }))
      return text
    }
  }
  return null
}

async function waitProcessed(page, ms = 180_000) {
  const deadline = Date.now() + ms
  let idle = 0
  while (Date.now() < deadline) {
    const publish = page.locator('[data-testid="publish-btn"], button:has-text("Опубликовать")').first()
    const title = page.locator('input[name="title"], textarea[name="title"], input[placeholder*="заголов" i], input[placeholder*="назван" i]').first()
    const body = await page.locator('body').innerText().catch(() => '')
    const titleReady = await title.isVisible().catch(() => false)
    const enabled =
      (await publish.isVisible().catch(() => false)) &&
      !(await publish.isDisabled().catch(() => true)) &&
      (await publish.getAttribute('aria-disabled').catch(() => null)) !== 'true'
    const busy = BUSY_RE.test(body) && !/готов|100\s*%|успешн/i.test(body)
    if (titleReady && enabled && !busy) {
      idle += 1
      if (idle >= 4) return 'publish-enabled'
    } else idle = 0
    await page.waitForTimeout(500)
  }
  return 'timeout'
}

async function attachCover(page, coverPath) {
  const result = { method: null, chooser: false, notes: [] }
  const imageInputs = page.locator(
    'input[type="file"][accept*="image"], input[type="file"][accept*="png"], input[type="file"][accept*="jpeg"], input[type="file"][accept*="jpg"]'
  )
  const imageCount = await imageInputs.count()
  result.notes.push(`image-inputs=${imageCount}`)
  if (imageCount > 0) {
    await imageInputs.last().setInputFiles(coverPath)
    result.method = 'setInputFiles-image-accept'
    return result
  }

  const clicked =
    (await clickSafe(page, ['Загрузить обложку', 'Загрузить картинку', 'Выбрать обложку', 'Загрузить свою'], { exact: true })) ||
    (await clickSafe(page, ['Обложка'], { exact: true })) ||
    (await page
      .locator('[data-testid*="cover" i], [data-testid*="thumb" i], [aria-label*="облож" i], [aria-label*="cover" i], [class*="cover" i] button, [class*="Cover"] button')
      .first()
      .click({ timeout: 4000 })
      .then(() => 'cover-widget')
      .catch(() => null))
  if (clicked) result.notes.push(`clicked=${clicked}`)
  await page.waitForTimeout(800)

  const after = page.locator(
    'input[type="file"][accept*="image"], input[type="file"][accept*="png"], input[type="file"][accept*="jpeg"]'
  )
  if ((await after.count()) > 0) {
    await after.last().setInputFiles(coverPath)
    result.method = 'click-then-setInputFiles'
    return result
  }

  const allFiles = page.locator('input[type="file"]')
  const n = await allFiles.count()
  for (let i = 0; i < n; i++) {
    const acc = ((await allFiles.nth(i).getAttribute('accept')) || '').toLowerCase()
    const aria = ((await allFiles.nth(i).getAttribute('aria-label')) || '').toLowerCase()
    if (/video|mp4/.test(acc) && !/image|png|jpe?g/.test(acc)) continue
    if (/облож|cover|image|png|jpe?g|картин/.test(`${acc} ${aria}`) || !acc) {
      try {
        await allFiles.nth(i).setInputFiles(coverPath)
        result.method = `setInputFiles-nth-${i}`
        result.notes.push(`accept=${acc}`)
        return result
      } catch (error) {
        result.notes.push(`nth-${i}-fail=${error.message}`)
      }
    }
  }

  const chooserPromise = page.waitForEvent('filechooser', { timeout: 12_000 }).catch(() => null)
  const uploadBtn =
    (await clickSafe(page, ['Загрузить', 'Выбрать файл', 'Загрузить файл', 'Upload', 'Выбрать изображение'], { timeout: 4000 })) ||
    (await clickSafe(page, ['Обложка'], { exact: true }))
  const chooser = await chooserPromise
  if (chooser) {
    result.chooser = true
    await chooser.setFiles(coverPath)
    result.method = `filechooser-after-${uploadBtn}`
    return result
  }
  result.method = 'failed'
  return result
}

const stealth = `(() => {
  try { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true }) } catch {}
})()`

const context = await chromium.launchPersistentContext(SESSION, {
  channel: 'chrome',
  headless: false,
  viewport: null,
  locale: 'ru-RU',
  timezoneId: 'Europe/Moscow',
  args: ['--disable-blink-features=AutomationControlled', '--start-maximized'],
  ignoreDefaultArgs: ['--enable-automation']
})
await context.addInitScript(stealth)
const page = context.pages()[0] ?? (await context.newPage())

context.on('page', (extra) => {
  void extra.waitForLoadState('domcontentloaded').then(async () => {
    const url = extra.url()
    dump.steps.push({ name: 'extra-page', url, at: new Date().toISOString() })
    save()
    if (/help|ads\.|advert|promo|academy|support|metrika|direct\.yandex/i.test(url)) {
      await extra.close().catch(() => undefined)
    }
  })
})

async function findStudioLinks(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('a, [role="link"], [role="menuitem"]')]
      .map((el) => ({
        href: el.getAttribute('href'),
        text: (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80)
      }))
      .filter((x) => /студ|studio|editor|канал|публикац/i.test(`${x.href} ${x.text}`))
      .slice(0, 40)
  )
}

try {
  await page.goto('https://dzen.ru', { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await page.waitForTimeout(2000)
  dump.findings.homeUrl = page.url()
  if (/passport|id\.vk/i.test(page.url())) {
    dump.error = `login-required ${page.url()}`
    save()
    throw new Error(dump.error)
  }
  await snap(page, 'home', { studioLinks: await findStudioLinks(page) })

  const profile =
    (await page.locator('[data-testid="profile-menu-wrapper"]').click({ timeout: 4000 }).then(() => 'profile-menu-wrapper').catch(() => null)) ||
    (await page.locator('[aria-label="Меню профиля"], [aria-label="Profile menu"], [aria-label*="profile" i]').first().click({ timeout: 3000 }).then(() => 'aria-profile').catch(() => null))
  dump.findings.profileClick = profile
  await page.waitForTimeout(700)
  await snap(page, 'after-profile-menu', { studioLinks: await findStudioLinks(page) })

  const studioFromMenu =
    (await clickSafe(page, ['Студия', 'Studio', 'Студия Дзена'], { exact: true, timeout: 5000 })) ||
    (await page.locator('a[href*="/editor"], a[href*="profile/editor"], a[href*="studio"]').first().click({ timeout: 4000 }).then(() => 'href-editor').catch(() => null))
  dump.findings.studioMenuClick = studioFromMenu
  await page.waitForTimeout(1500)

  if (!/\/editor|\/studio|\/profile\/editor|\/media/i.test(page.url())) {
    await page.goto('https://dzen.ru/editor', { waitUntil: 'domcontentloaded', timeout: 45_000 }).catch(() => undefined)
    await page.waitForTimeout(1500)
  }
  if (!/\/editor|\/studio|\/profile\/editor|\/media/i.test(page.url()) && !/не найдена|not found/i.test(await page.title())) {
    await page.goto('https://dzen.ru/profile/editor/', { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => undefined)
    await page.waitForTimeout(1000)
  }

  dump.findings.studioUrl = page.url()
  dump.findings.studioTitle = await page.title()
  if (/passport|id\.vk/i.test(page.url())) {
    dump.error = `login-required ${page.url()}`
    save()
    throw new Error(dump.error)
  }
  await snap(page, 'studio-home')

  const add =
    (await page.locator('[data-testid="add-publication-button"]').click({ timeout: 5000 }).then(() => 'add-publication-button').catch(() => null)) ||
    (await page.locator('button[aria-label*="Создать" i], a[aria-label*="Создать" i]').first().click({ timeout: 4000 }).then(() => 'aria-create').catch(() => null)) ||
    (await clickSafe(page, ['Создать публикацию', 'Новая публикация'])) ||
    (await clickSafe(page, ['Создать'])) ||
    (await page.locator('button:has-text("Загрузить видео"), a:has-text("Загрузить видео")').first().click({ timeout: 3000 }).then(() => 'direct-upload-video').catch(() => null))
  dump.findings.createClick = add
  await page.waitForTimeout(800)
  await snap(page, 'after-create-click', { createClick: add })

  const videoItem =
    (await clickSafe(page, ['Загрузить видео'], { exact: true, timeout: 8000 })) ||
    (await clickSafe(page, ['Upload video'], { exact: true })) ||
    (await clickSafe(page, ['Ролик', 'Короткое видео'], { exact: true }))
  dump.findings.uploadMenuClick = videoItem
  await page.waitForTimeout(1200)
  await snap(page, 'after-upload-menu', { uploadMenuClick: videoItem })

  const videoInput = page.locator('input[type="file"][accept*="video"], input[type="file"][accept*="mp4"], input[type="file"]').first()
  await videoInput.waitFor({ state: 'attached', timeout: 20_000 }).catch(() => undefined)
  if ((await page.locator('input[type="file"]').count()) === 0) {
    const pick = await clickSafe(page, ['Выбрать видео', 'Выбрать файл', 'Загрузить'])
    dump.findings.pickVideoClick = pick
    await page.waitForTimeout(500)
  }
  const files = page.locator('input[type="file"]')
  let attached = false
  const fileCount = await files.count()
  for (let i = 0; i < fileCount; i++) {
    const acc = ((await files.nth(i).getAttribute('accept')) || '').toLowerCase()
    if (/image|png|jpe?g/.test(acc) && !/video|mp4/.test(acc)) continue
    try {
      await files.nth(i).setInputFiles(VIDEO)
      attached = true
      dump.findings.videoInput = { i, accept: acc }
      break
    } catch (error) {
      dump.findings.videoAttachError = error.message
    }
  }
  if (!attached) {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 15_000 })
    await clickSafe(page, ['Выбрать видео', 'Выбрать файл', 'Загрузить'])
    const chooser = await chooserPromise
    await chooser.setFiles(VIDEO)
    dump.findings.videoInput = { method: 'filechooser' }
  }
  await snap(page, 'after-video-file')

  const ready = await waitProcessed(page)
  dump.findings.processing = ready
  await snap(page, 'after-processing', { processing: ready })

  const coverResult = await attachCover(page, COVER)
  dump.findings.cover = coverResult
  await page.waitForTimeout(1500)
  await snap(page, 'after-cover', { cover: coverResult })

  const confirm = await clickSafe(page, ['Готово', 'Применить', 'Сохранить', 'Done', 'Apply'], { exact: true, timeout: 4000 })
  dump.findings.coverConfirm = confirm
  if (confirm) {
    await page.waitForTimeout(800)
    await snap(page, 'after-cover-confirm', { coverConfirm: confirm })
  }

  dump.findings.finalUrl = page.url()
  dump.findings.didNotPublish = true
} catch (error) {
  dump.error = error instanceof Error ? error.message : String(error)
  await snap(page, 'error', { error: dump.error }).catch(() => undefined)
} finally {
  save()
  await context.close().catch(() => undefined)
}
console.log(`[dzen-probe] wrote ${OUT}`)
console.log(JSON.stringify(dump.findings, null, 2))
