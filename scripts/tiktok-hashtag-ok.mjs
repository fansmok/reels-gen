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
  console.log(`[tags2] ${name}${detail ? ' | ' + String(detail).slice(0, 400) : ''}`)
}

const TAGS = ['fyp', 'viral']

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
const page = context.pages()[0] ?? (await context.newPage())
const report = { ok: false, mentions: [], caption: '', steps: log }

try {
  await page.goto('https://www.tiktok.com/tiktokstudio/upload', { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await sleep(2000)
  const captionBox = page.locator('[data-e2e="caption_container"] [contenteditable="true"]').first()
  if (!(await captionBox.isVisible().catch(() => false))) {
    await page.locator('input[type="file"][accept*="video"]').first().setInputFiles(VIDEO)
    step('file', 'set')
    await captionBox.waitFor({ state: 'visible', timeout: 90_000 })
  }
  await page.keyboard.press('Escape').catch(() => undefined)
  await sleep(400)

  await captionBox.click()
  await page.keyboard.press('Control+A')
  await page.keyboard.press('Backspace')
  await page.keyboard.type('Тест описания для TikTok без названия', { delay: 1 })
  await sleep(300)
  step('caption-now', ((await captionBox.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim().slice(0, 120))
  step('caption', 'filled')
  await sleep(400)

  await captionBox.click()
  await page.keyboard.press('End')
  await page.keyboard.press('Space')

  const btn = page.locator('#web-creation-caption-hashtag-button').first()
  const items = page.locator('.hashtag-suggestion-item')

  for (const tag of TAGS) {
    await btn.click()
    step('btn', tag)
    await sleep(280)
    await page.keyboard.type(tag, { delay: 40 })
    await sleep(900)
    const count = await items.count()
    step('suggest-count', `${tag}=${count}`)
    const texts = await items.evaluateAll((els) =>
      els.slice(0, 6).map((el) => (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60))
    )
    step('suggest-texts', JSON.stringify(texts))
    await page.screenshot({ path: join(OUT_DIR, `tag-${tag}.png`) })
    const exact = items.filter({ hasText: new RegExp(`^#${tag}\\b`, 'i') }).first()
    if ((await exact.count()) > 0 && (await exact.isVisible().catch(() => false))) {
      await exact.click()
      step('pick', `exact #${tag}`)
    } else if (count > 0) {
      await items.first().click()
      step('pick', `first for #${tag}`)
    } else {
      await page.keyboard.press('Enter')
      step('pick', `enter #${tag}`)
    }
    await sleep(400)
    await page.keyboard.press('Space')
    await sleep(200)
  }

  report.mentions = await page.locator('[data-e2e="caption_container"] .mention').allInnerTexts()
  report.caption = ((await captionBox.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim()
  report.ok = report.mentions.filter((t) => t.includes('#')).length >= 2
  step('mentions', JSON.stringify(report.mentions))
  step('caption-final', report.caption)
  await page.screenshot({ path: join(OUT_DIR, 'ok-final.png') })
  step('publish', 'НЕ публикую')
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await page.screenshot({ path: join(OUT_DIR, 'ok-error.png') }).catch(() => undefined)
} finally {
  writeFileSync(join(OUT_DIR, 'ok.json'), JSON.stringify(report, null, 2), 'utf-8')
  await sleep(1200)
  await context.close().catch(() => undefined)
}
