import { existsSync, mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { chromium } from 'playwright-core'

const ROOT = 'C:\\Users\\faans\\Desktop\\РИЛС-ЗАГРУЗКА'
const OUT_DIR = join(ROOT, 'scripts')
const OUT = join(OUT_DIR, 'instagram-cover.json')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'instagram')
const SHARE_RE = /^(share|поделиться|compartir|partager|teilen)$/i

const log = []
function note(step, detail) {
  const row = { t: new Date().toISOString(), step, detail }
  log.push(row)
  console.log(`[ig] ${step} ${detail ?? ''}`)
}

function pickFile(exts, extraDirs = []) {
  const dirs = [ROOT, ...extraDirs]
  for (const dir of dirs) {
    if (!existsSync(dir)) continue
    const names = readdirSync(dir)
    const hit = names.find((n) => exts.some((e) => n.toLowerCase().endsWith(e)))
    if (hit) return join(dir, hit)
  }
  return ''
}

const VIDEO =
  pickFile(['.mp4', '.mov', '.webm']) ||
  pickFile(['.mp4'], ['C:\\Users\\faans\\Desktop\\рилсы'])
const COVER =
  pickFile(['.png', '.jpg', '.jpeg', '.webp']) ||
  pickFile(['.png', '.jpg', '.jpeg'], ['C:\\Users\\faans\\Desktop\\ФОТО-СНИМКИ'])

const stealth = `(() => {
  try { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true }) } catch {}
  try {
    if (!window.chrome) window.chrome = {}
    if (!window.chrome.runtime) window.chrome.runtime = { connect: () => ({}), sendMessage: () => {} }
  } catch {}
})()`

function wizard(page) {
  return page.locator('[role="dialog"]').last()
}

async function dumpUi(page, label) {
  const root = wizard(page)
  const heading = await root.locator('h1, [role="heading"]').first().innerText().catch(() => '')
  const body = (await root.innerText().catch(() => '')).replace(/\s+/g, ' ').trim().slice(0, 2500)
  const aria = await root.ariaSnapshot({ timeout: 4000 }).catch(() => '')
  const items = await page.evaluate(() => {
    const nodes = [...document.querySelectorAll('button, a, [role="button"], [role="tab"], [role="menuitem"], input, [aria-label]')]
    return nodes.slice(0, 250).map((el) => {
      const html = el
      return {
        tag: html.tagName.toLowerCase(),
        type: html.getAttribute('type') || undefined,
        accept: html.getAttribute('accept') || undefined,
        aria: html.getAttribute('aria-label') || undefined,
        role: html.getAttribute('role') || undefined,
        disabled: html.getAttribute('aria-disabled') || (html.disabled ? 'true' : undefined),
        text: (html.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80) || undefined
      }
    }).filter((x) => x.text || x.aria || x.accept || x.type === 'file')
  })
  const files = await page.evaluate(() =>
    [...document.querySelectorAll('input[type="file"]')].map((el, i) => ({
      i,
      accept: el.getAttribute('accept') || '',
      aria: el.getAttribute('aria-label') || '',
      name: el.getAttribute('name') || '',
      id: el.id || '',
      hidden: el.offsetParent === null && getComputedStyle(el).display === 'none'
    }))
  )
  const videos = await page.evaluate(() =>
    [...document.querySelectorAll('video')].map((v) => ({
      readyState: v.readyState,
      paused: v.paused,
      duration: Number.isFinite(v.duration) ? v.duration : null,
      w: v.videoWidth,
      h: v.videoHeight
    }))
  )
  const progress = await page.evaluate(() =>
    [...document.querySelectorAll('[role="progressbar"], [aria-label*="загруз" i], [aria-label*="load" i], [aria-label*="process" i]')]
      .map((el) => ({
        aria: el.getAttribute('aria-label') || '',
        text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80),
        visible: el.offsetParent !== null || getComputedStyle(el).display !== 'none'
      }))
  )
  return { label, url: page.url(), heading, body, aria, items, files, videos, progress }
}

async function dismiss(page) {
  for (const name of [/allow all cookies|разрешить все/i, /^(not now|не сейчас)$/i, /^(got it|понятно)$/i]) {
    const btn = page.getByRole('button', { name }).first()
    if (await btn.isVisible().catch(() => false)) {
      const t = (await btn.innerText().catch(() => '')).trim()
      if (SHARE_RE.test(t)) continue
      await btn.click({ timeout: 1200 }).catch(() => undefined)
      note('dismiss', t || String(name))
    }
  }
}

async function clickNext(page) {
  const root = wizard(page)
  const ok = root.getByRole('button', { name: /^ok$/i }).first()
  if (await ok.isVisible().catch(() => false)) {
    await ok.click({ timeout: 4000 }).catch(() => ok.click({ force: true }))
    note('next', 'OK')
    return true
  }
  const next = root.getByRole('button', { name: /^(next|далее)$/i }).first()
  if (await next.isVisible().catch(() => false)) {
    const aria = await next.getAttribute('aria-disabled').catch(() => null)
    if (aria === 'true' || (await next.isDisabled().catch(() => false))) {
      note('next', 'disabled')
      return false
    }
    await next.click({ timeout: 4000 }).catch(() => next.click({ force: true }))
    note('next', 'Далее')
    return true
  }
  return false
}

async function waitReady(page, timeout = 180_000) {
  const deadline = Date.now() + timeout
  let idle = 0
  while (Date.now() < deadline) {
    await dismiss(page)
    const snap = await dumpUi(page, 'wait')
    const busyText = /обработк|загрузк|uploading|processing|preparing|подготовк/i.test(snap.body || '')
    const busyBar = (snap.progress || []).some((p) => p.visible)
    const videoOk = (snap.videos || []).some((v) => v.readyState >= 2 || v.w > 0)
    const next = wizard(page).getByRole('button', { name: /^(next|далее)$/i }).first()
    const nextOn = (await next.isVisible().catch(() => false)) && !(await next.isDisabled().catch(() => false)) && (await next.getAttribute('aria-disabled')) !== 'true'
    const cover = /фото обложки|cover photo|редактировать|^edit$/i.test(`${snap.heading} ${snap.body}`)
    if (!busyText && !busyBar && (videoOk || cover) && nextOn) {
      idle += 1
      if (idle >= 3) {
        note('wait-processing', `ready heading=${snap.heading}`)
        return snap
      }
    } else {
      idle = 0
      note('wait-processing', `busy=${busyText||busyBar} video=${videoOk} next=${nextOn} h=${snap.heading}`)
    }
    await page.waitForTimeout(700)
  }
  throw new Error('Instagram не обработал видео за 3 минуты')
}

mkdirSync(OUT_DIR, { recursive: true })
note('files', `video=${VIDEO || 'NONE'} cover=${COVER || 'NONE'} session=${SESSION}`)
if (!VIDEO) {
  writeFileSync(OUT, JSON.stringify({ error: 'no video', log }, null, 2), 'utf8')
  process.exit(1)
}

const dumps = []
let context
try {
  context = await chromium.launchPersistentContext(SESSION, {
    channel: 'chrome',
    headless: false,
    viewport: null,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    args: ['--disable-blink-features=AutomationControlled', '--start-maximized', '--disable-http3'],
    ignoreDefaultArgs: [
      '--enable-automation',
      '--disable-extensions',
      '--disable-component-extensions-with-background-pages',
      '--disable-default-apps',
      '--disable-sync',
      '--metrics-recording-only'
    ]
  })
  await context.addInitScript(stealth)
  const page = context.pages()[0] || (await context.newPage())
  page.on('dialog', (d) => void d.dismiss().catch(() => undefined))
  context.on('page', (opened) => {
    void (async () => {
      await opened.waitForLoadState('domcontentloaded').catch(() => undefined)
      const url = opened.url()
      note('window', url)
      if (/help\.instagram|\/help|\/ads|adsmanager|about\.meta|business\.facebook/i.test(url) && opened !== page) {
        await opened.close().catch(() => undefined)
        note('window-closed', url)
      }
    })()
  })

  try {
    await page.goto('https://www.instagram.com/', { waitUntil: 'domcontentloaded', timeout: 60_000 })
  } catch (e) {
    note('goto-warn', String(e.message || e))
  }
  await page.waitForTimeout(2000)
  await dismiss(page)
  dumps.push(await dumpUi(page, 'home'))

  const create = page.locator(
    '[aria-label="Новая публикация"], svg[aria-label="Новая публикация"], [aria-label="New post"], svg[aria-label="New post"]'
  ).first()
  await create.click({ timeout: 12_000 })
  note('create', 'Новая публикация')
  await page.waitForTimeout(1500)
  await dismiss(page)
  dumps.push(await dumpUi(page, 'create-dialog'))

  const videoInput = page.locator('input[type="file"][accept*="video"], input[type="file"]').first()
  await videoInput.setInputFiles(VIDEO)
  note('file', VIDEO)
  dumps.push(await dumpUi(page, 'after-attach'))
  await waitReady(page)
  dumps.push(await dumpUi(page, 'after-processing'))

  for (let i = 0; i < 6; i++) {
    const snap = await dumpUi(page, `step-${i}`)
    dumps.push(snap)
    const h = `${snap.heading}\n${snap.body}`
    note('heading', snap.heading)
    if (/фото обложки|cover photo|редактировать/i.test(h) && !/добавьте подпись|write a caption|новое видео/i.test(snap.heading)) {
      note('edit', 'reached edit/cover')
      break
    }
    if (/добавьте подпись|write a caption|новое видео/i.test(h) && (await wizard(page).getByRole('button', { name: SHARE_RE }).count())) {
      note('caption', 'reached caption without edit?')
      break
    }
    const clicked = await clickNext(page)
    if (!clicked) {
      note('next-miss', snap.heading)
      await page.waitForTimeout(1500)
      continue
    }
    await page.waitForTimeout(1200)
    await waitReady(page).catch(() => undefined)
  }

  dumps.push(await dumpUi(page, 'edit-before-cover-click'))
  const coverBtn = wizard(page).getByRole('button', { name: /фото обложки|cover photo|обложк/i }).first()
  const coverText = wizard(page).getByText(/фото обложки|cover photo/i).first()
  if (await coverBtn.isVisible().catch(() => false)) {
    await coverBtn.click({ timeout: 4000 }).catch(() => coverBtn.click({ force: true }))
    note('cover-click', 'role=button Фото обложки')
  } else if (await coverText.isVisible().catch(() => false)) {
    await coverText.click({ timeout: 4000 }).catch(() => undefined)
    note('cover-click', 'text Фото обложки')
  } else {
    note('cover-click', 'кнопка не видна — пробую input jpeg/png')
  }
  await page.waitForTimeout(1500)
  dumps.push(await dumpUi(page, 'cover-picker'))

  let coverHow = 'none'
  if (COVER) {
    const jpeg = page.locator('input[type="file"][accept="image/jpeg,image/png"], input[type="file"][accept*="image/jpeg"], input[type="file"][accept*="image/png"]')
    const n = await jpeg.count()
    note('image-inputs', String(n))
    if (n > 0) {
      await jpeg.last().setInputFiles(COVER)
      coverHow = 'setInputFiles jpeg/png'
      note('cover-set', coverHow)
    } else {
      const chooserP = page.waitForEvent('filechooser', { timeout: 10_000 }).catch(() => null)
      const pick = wizard(page).getByRole('button', { name: /выбрать на компьютере|select from computer|upload from computer/i }).last()
      if (await pick.isVisible().catch(() => false)) {
        await pick.click({ timeout: 4000 }).catch(() => undefined)
      } else {
        await wizard(page).getByText(/выбрать на компьютере|select from computer/i).last().click({ timeout: 4000 }).catch(() => undefined)
      }
      const chooser = await chooserP
      if (chooser) {
        await chooser.setFiles(COVER)
        coverHow = 'filechooser'
        note('cover-set', coverHow)
      } else {
        note('cover-fail', 'нет jpeg input и chooser')
      }
    }
    await page.waitForTimeout(2000)
    dumps.push(await dumpUi(page, 'after-cover'))
    const done = wizard(page).getByRole('button', { name: /^(done|готово)$/i }).first()
    if (await done.isVisible().catch(() => false)) {
      await done.click({ timeout: 4000 }).catch(() => undefined)
      note('cover-done', 'Готово')
      await page.waitForTimeout(1000)
      dumps.push(await dumpUi(page, 'after-cover-done'))
    }
  }

  const shareVisible = await wizard(page).getByRole('button', { name: SHARE_RE }).first().isVisible().catch(() => false)
  note('share', shareVisible ? 'visible — НЕ жмём' : 'not visible')

  const result = {
    video: VIDEO,
    cover: COVER,
    coverHow,
    shareClicked: false,
    log,
    dumps
  }
  writeFileSync(OUT, JSON.stringify(result, null, 2), 'utf8')
  note('saved', OUT)
  await page.waitForTimeout(1500)
} catch (error) {
  note('ERROR', error instanceof Error ? error.stack : String(error))
  writeFileSync(OUT, JSON.stringify({ error: String(error), log, dumps }, null, 2), 'utf8')
  throw error
} finally {
  await context?.close().catch(() => undefined)
}
