import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'pinterest')
const OUT_DIR = join(ROOT, 'scripts', 'pinterest-live')
const OUT = join(OUT_DIR, 'live.json')
const STEALTH = `(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true })
  } catch {}
  try {
    if (!window.chrome) window.chrome = {}
    if (!window.chrome.runtime) window.chrome.runtime = { connect: () => ({}), sendMessage: () => {} }
  } catch {}
})()`

mkdirSync(OUT_DIR, { recursive: true })

const log = []
function step(name, detail) {
  const row = { t: new Date().toISOString(), name, detail: detail ?? null }
  log.push(row)
  console.log(`[pinterest-live] ${name}${detail ? ' | ' + String(detail).slice(0, 400) : ''}`)
}

function pickMedia() {
  const files = readdirSync(ROOT)
  const video = files.find((n) => n.toLowerCase().endsWith('.mp4'))
  const cover =
    files.find((n) => n.toLowerCase() === 'test-cover.png') || files.find((n) => n.toLowerCase().endsWith('.png'))
  if (!video) throw new Error('нет mp4')
  return { videoPath: join(ROOT, video), coverPath: cover ? join(ROOT, cover) : null, video, cover }
}

async function dumpUi(page, label) {
  const data = await page
    .evaluate(() => {
      const vis = (el) => {
        const s = getComputedStyle(el)
        const r = el.getBoundingClientRect()
        return s.display !== 'none' && s.visibility !== 'hidden' && r.width + r.height > 2
      }
      const els = [...document.querySelectorAll('button, a, [role="button"], [role="menuitem"], input, [data-test-id]')]
        .slice(0, 220)
        .map((el) => ({
          tag: el.tagName.toLowerCase(),
          id: el.id || '',
          test: el.getAttribute('data-test-id') || el.getAttribute('data-testid') || '',
          aria: el.getAttribute('aria-label') || '',
          accept: el.getAttribute('accept') || '',
          type: el.getAttribute('type') || '',
          href: el.getAttribute('href') || '',
          text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 90),
          visible: vis(el)
        }))
        .filter((x) => x.text || x.aria || x.test || x.accept)
      const files = [...document.querySelectorAll('input[type="file"]')].map((el) => ({
        id: el.id,
        test: el.getAttribute('data-test-id'),
        accept: el.getAttribute('accept'),
        aria: el.getAttribute('aria-label')
      }))
      const iframes = [...document.querySelectorAll('iframe')].slice(0, 12).map((el) => ({
        src: (el.getAttribute('src') || '').slice(0, 160),
        title: el.getAttribute('title') || ''
      }))
      return { url: location.href, title: document.title, els, files, iframes }
    })
    .catch((e) => ({ error: e.message, url: page.url() }))
  return { label, ...data }
}

async function shot(page, name) {
  await page.screenshot({ path: join(OUT_DIR, `${name}.png`), fullPage: false }).catch(() => undefined)
}

const report = { startedAt: new Date().toISOString(), published: false, snapshots: [], pages: [], media: pickMedia() }
step('media', `${report.media.video} / ${report.media.cover}`)

const context = await chromium.launchPersistentContext(SESSION, {
  channel: 'chrome',
  headless: false,
  viewport: null,
  locale: 'ru-RU',
  timezoneId: 'Europe/Moscow',
  args: ['--disable-blink-features=AutomationControlled', '--start-maximized'],
  ignoreDefaultArgs: [
    '--enable-automation',
    '--disable-extensions',
    '--disable-component-extensions-with-background-pages',
    '--disable-default-apps',
    '--disable-sync',
    '--metrics-recording-only'
  ]
})
await context.addInitScript(STEALTH)
const page = context.pages()[0] ?? (await context.newPage())

try {
  step('goto', 'https://ru.pinterest.com/')
  await page.goto('https://ru.pinterest.com/', { waitUntil: 'domcontentloaded', timeout: 45_000 })
  await sleep(2500)
  step('landed', page.url())
  report.snapshots.push(await dumpUi(page, 'after-home'))
  await shot(page, '01-hub')

  const recaptcha = await page.locator('iframe[src*="recaptcha"], iframe[src*="captcha"], iframe[title*="captcha" i]').count()
  step('recaptcha-iframes', String(recaptcha))

  const createCandidates = [
    '[data-test-id="header-create-menu-button"]',
    '[data-test-id="header-create-pin-button"]',
    '[data-test-id="gestalt-create-button"]',
    '[data-test-id="onboarding-module-create-pin-button"]'
  ]
  for (const sel of createCandidates) {
    const n = await page.locator(sel).count()
    const vis = n > 0 ? await page.locator(sel).first().isVisible().catch(() => false) : false
    step('create-sel', `${sel} count=${n} visible=${vis}`)
  }

  const headerCreate = page
    .locator(
      '[data-test-id="header-create-menu-button"], [data-test-id="header-create-pin-button"], [data-test-id="gestalt-create-button"]'
    )
    .first()
  if (await headerCreate.isVisible().catch(() => false)) {
    await headerCreate.click({ timeout: 5000 })
    step('click', 'шапка Создать')
    await sleep(800)
    report.snapshots.push(await dumpUi(page, 'after-header-create'))
    await shot(page, '02-create-menu')
    const pinItem = page.locator('[data-test-id="create-pin"]').first()
    const pinRole = page.getByRole('menuitem', { name: /^(пин|pin)$/i }).first()
    if (await pinItem.isVisible().catch(() => false)) {
      await pinItem.click({ timeout: 4000 })
      step('click', 'меню Пин data-test-id=create-pin')
    } else if (await pinRole.isVisible().catch(() => false)) {
      await pinRole.click({ timeout: 4000 })
      step('click', 'меню Пин role=menuitem')
    } else {
      step('click', 'Пин в меню не найден')
    }
    await sleep(2500)
    step('after-pin-menu', page.url())
    report.pages = context.pages().map((p) => p.url())
    step('tabs', report.pages.join(' | '))
    report.snapshots.push(await dumpUi(page, 'after-create-pin'))
    await shot(page, '03-after-create-pin')
  } else {
    const hubCreate = page.locator('[data-test-id="onboarding-module-create-pin-button"]').first()
    if (await hubCreate.isVisible().catch(() => false)) {
      await hubCreate.click({ timeout: 5000 })
      step('click', 'хаб Создайте пин')
      await sleep(2500)
      report.pages = context.pages().map((p) => p.url())
      step('tabs', report.pages.join(' | '))
      const last = context.pages()[context.pages().length - 1]
      step('last-tab', last.url())
      report.snapshots.push(await dumpUi(last, 'after-hub-create'))
      await last.screenshot({ path: join(OUT_DIR, '03-after-hub-create.png') }).catch(() => undefined)
    } else {
      step('click', 'кнопки Создать нет')
    }
  }

  const urls = [
    'https://ru.pinterest.com/pin-creation-tool/',
    'https://www.pinterest.com/pin-creation-tool/',
    'https://ru.pinterest.com/idea-pin-builder/'
  ]
  let builder = page
  for (const url of urls) {
    step('goto-builder', url)
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 }).catch((e) => step('goto-fail', e.message))
    await sleep(2000)
    step('builder-url', page.url())
    const input = page.locator('#storyboard-upload-input, [data-test-id="storyboard-upload-input"]').first()
    const count = await input.count()
    const accept = count ? await input.getAttribute('accept') : ''
    step('video-input', `count=${count} accept=${accept}`)
    report.snapshots.push(await dumpUi(page, `builder-${url}`))
    await shot(page, `04-builder-${urls.indexOf(url)}`)
    if (count > 0 && /video/i.test(accept || '')) {
      builder = page
      break
    }
    const createDraft = page.locator('[data-test-id="storyboard-create-button"]').first()
    if (await createDraft.isVisible().catch(() => false)) {
      await createDraft.click({ timeout: 4000 }).catch(() => undefined)
      step('click', 'storyboard-create-button Создать')
      await sleep(1500)
      const count2 = await input.count()
      const accept2 = count2 ? await input.getAttribute('accept') : ''
      step('video-input-after-create', `count=${count2} accept=${accept2}`)
      if (count2 > 0 && /video/i.test(accept2 || '')) {
        builder = page
        break
      }
    }
  }

  const input = builder.locator('#storyboard-upload-input, [data-test-id="storyboard-upload-input"]').first()
  if ((await input.count()) > 0) {
    step('setInputFiles', report.media.videoPath)
    await input.setInputFiles(report.media.videoPath)
    await sleep(3000)
    report.snapshots.push(await dumpUi(builder, 'after-file'))
    await builder.screenshot({ path: join(OUT_DIR, '05-after-file.png') }).catch(() => undefined)

    const deadline = Date.now() + 90_000
    while (Date.now() < deadline) {
      const title = builder.locator('#storyboard-selector-title').first()
      const cover = builder.locator('[data-test-id="video-cover-container-edit-cover-button"]').first()
      const pub = builder.locator('[data-test-id="storyboard-creation-nav-done"]').first()
      const titleVis = await title.isVisible().catch(() => false)
      const coverVis = await cover.isVisible().catch(() => false)
      const pubText = (await pub.innerText().catch(() => '')).slice(0, 40)
      step('wait', `title=${titleVis} cover=${coverVis} publish=${pubText}`)
      if (titleVis || coverVis) break
      await sleep(2500)
    }

    const title = builder.locator('#storyboard-selector-title').first()
    if (await title.isVisible().catch(() => false)) {
      await title.fill('Тест шортс (не публиковать)')
      step('title', 'заполнено')
    } else {
      step('title', 'поля названия нет')
    }
    report.snapshots.push(await dumpUi(builder, 'ready-dry'))
    await builder.screenshot({ path: join(OUT_DIR, '06-ready.png') }).catch(() => undefined)
  } else {
    step('file', 'storyboard-upload-input так и не появился')
  }

  step('publish', 'НЕ публикую')
  report.finishedAt = new Date().toISOString()
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await shot(page, 'error')
  try {
    report.snapshots.push(await dumpUi(page, 'error'))
  } catch {
    /* ignore */
  }
} finally {
  report.steps = log
  writeFileSync(OUT, JSON.stringify(report, null, 2), 'utf-8')
  step('write', OUT)
  await sleep(2000)
  await context.close().catch(() => undefined)
}
