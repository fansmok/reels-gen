import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'tiktok')
const OUT_DIR = join(ROOT, 'scripts', 'tiktok-hashtags')
const VIDEO = join(ROOT, 'Человек-Паук1.mp4')
mkdirSync(OUT_DIR, { recursive: true })

const log = []
const step = (name, detail) => {
  const row = { t: new Date().toISOString(), name, detail: detail ?? null }
  log.push(row)
  console.log(`[tags] ${name}${detail ? ' | ' + String(detail).slice(0, 500) : ''}`)
}

async function dumpSuggest(page, label) {
  return page.evaluate((lab) => {
    const vis = (el) => {
      const s = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return s.display !== 'none' && s.visibility !== 'hidden' && r.width + r.height > 2
    }
    const btn = document.querySelector('#web-creation-caption-hashtag-button, button[aria-label="Хэштег"], button[aria-label="Hashtag"]')
    const caption = document.querySelector('[data-e2e="caption_container"] [contenteditable="true"], [data-e2e="caption_container"] [role="textbox"]')
    const candidates = [...document.querySelectorAll('[role="listbox"], [role="option"], [class*="mention"], [class*="hashtag"], [class*="HashTag"], [class*="suggestion"], [class*="caption-"]')]
      .filter(vis)
      .slice(0, 80)
      .map((el) => ({
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        role: el.getAttribute('role') || '',
        test: el.getAttribute('data-e2e') || el.getAttribute('data-testid') || '',
        cls: String(el.className || '').slice(0, 120),
        text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80)
      }))
    return {
      label: lab,
      url: location.href,
      btn: btn
        ? { id: btn.id, aria: btn.getAttribute('aria-label'), text: (btn.innerText || '').trim() }
        : null,
      caption: caption ? (caption.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200) : null,
      candidates
    }
  })
}

const report = { steps: [], snapshots: [], published: false }
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
await context.addInitScript(`(() => {
  try { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true }) } catch {}
})()`)
const page = context.pages()[0] ?? (await context.newPage())

try {
  step('goto', 'https://www.tiktok.com/tiktokstudio/upload')
  await page.goto('https://www.tiktok.com/tiktokstudio/upload', { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await sleep(2500)
  step('landed', page.url())
  await page.screenshot({ path: join(OUT_DIR, '01-upload.png') })

  const captionReady = page.locator('[data-e2e="caption_container"] [contenteditable="true"]').first()
  if (!(await captionReady.isVisible().catch(() => false))) {
    const input = page.locator('input[type="file"][accept*="video"]').first()
    await input.waitFor({ state: 'attached', timeout: 25_000 })
    await input.setInputFiles(VIDEO)
    step('file', 'set')
    const deadline = Date.now() + 120_000
    while (Date.now() < deadline) {
      const ready = await captionReady.isVisible().catch(() => false)
      const post = page.locator('[data-e2e="post_video_button"]').first()
      const enabled = ready && !(await post.isDisabled().catch(() => true))
      step('wait', `caption=${ready} postEnabled=${enabled}`)
      if (ready) break
      await sleep(2000)
    }
  }

  await page.keyboard.press('Escape').catch(() => undefined)
  await sleep(500)
  report.snapshots.push(await dumpSuggest(page, 'before'))
  await page.screenshot({ path: join(OUT_DIR, '02-before.png') })

  const btn = page.locator('#web-creation-caption-hashtag-button, button[aria-label="Хэштег"], button[aria-label="Hashtag"]').first()
  step('btn-count', String(await btn.count()))
  step('btn-text', ((await btn.innerText().catch(() => '')) || '').slice(0, 80))
  await btn.scrollIntoViewIfNeeded()
  await btn.click({ timeout: 5000 })
  step('click', 'hashtag button')
  await sleep(800)
  report.snapshots.push(await dumpSuggest(page, 'after-click'))
  await page.screenshot({ path: join(OUT_DIR, '03-after-click.png') })

  await page.keyboard.type('fyp', { delay: 40 })
  step('type', 'fyp')
  await sleep(1200)
  report.snapshots.push(await dumpSuggest(page, 'after-type-fyp'))
  await page.screenshot({ path: join(OUT_DIR, '04-after-type.png') })

  const option = page.locator('[role="option"], [role="listbox"] [role="option"]').first()
  const optionVis = await option.isVisible().catch(() => false)
  step('role-option', String(optionVis))
  if (optionVis) {
    const t = (await option.innerText().catch(() => '')).slice(0, 80)
    step('option-text', t)
    await option.click({ timeout: 4000 })
    step('click', 'role=option')
  } else {
    const any = page.locator('[class*="mention"] [class*="item"], [class*="hashtag"] li, [class*="suggestion"] li, [class*="HashTag"] *').first()
    if (await any.isVisible().catch(() => false)) {
      step('alt', ((await any.innerText().catch(() => '')) || '').slice(0, 80))
      await any.click({ timeout: 4000 })
      step('click', 'alt suggestion')
    } else {
      await page.keyboard.press('Enter')
      step('click', 'Enter fallback')
    }
  }
  await sleep(800)
  report.snapshots.push(await dumpSuggest(page, 'after-pick-1'))
  await page.screenshot({ path: join(OUT_DIR, '05-after-pick.png') })

  await page.keyboard.press('Space')
  await sleep(300)
  await btn.click({ timeout: 4000 })
  await sleep(400)
  await page.keyboard.type('viral', { delay: 40 })
  await sleep(1200)
  report.snapshots.push(await dumpSuggest(page, 'second-type'))
  const opt2 = page.locator('[role="option"]').first()
  if (await opt2.isVisible().catch(() => false)) {
    await opt2.click({ timeout: 4000 })
    step('click', 'second option')
  } else {
    await page.keyboard.press('Enter')
    step('click', 'second Enter')
  }
  await sleep(600)
  const caption = await page.locator('[data-e2e="caption_container"]').innerText().catch(() => '')
  step('caption-final', caption.replace(/\s+/g, ' ').trim().slice(0, 300))
  report.snapshots.push(await dumpSuggest(page, 'final'))
  await page.screenshot({ path: join(OUT_DIR, '06-final.png') })
  step('publish', 'НЕ публикую')
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await page.screenshot({ path: join(OUT_DIR, 'error.png') }).catch(() => undefined)
} finally {
  report.steps = log
  writeFileSync(join(OUT_DIR, 'study.json'), JSON.stringify(report, null, 2), 'utf-8')
  step('write', join(OUT_DIR, 'study.json'))
  await sleep(1500)
  await context.close().catch(() => undefined)
}
