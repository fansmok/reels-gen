import { mkdirSync, writeFileSync, readdirSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'dzen')
const OUT = join(ROOT, 'scripts', 'dzen-live', 'comments.json')
const STEALTH = `(() => { try { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true }) } catch {} })()`

mkdirSync(join(ROOT, 'scripts', 'dzen-live'), { recursive: true })
const video = join(ROOT, readdirSync(ROOT).find((n) => n.toLowerCase().endsWith('.mp4')))
const report = { published: false, steps: [], options: [], fields: [] }

function step(name, detail) {
  report.steps.push({ t: new Date().toISOString(), name, detail: detail ?? null })
  console.log(`[dzen-live] ${name}${detail ? ' | ' + String(detail).slice(0, 300) : ''}`)
}

const context = await chromium.launchPersistentContext(SESSION, {
  channel: 'chrome',
  headless: false,
  viewport: null,
  locale: 'ru-RU',
  timezoneId: 'Europe/Moscow',
  args: ['--disable-blink-features=AutomationControlled', '--start-maximized'],
  ignoreDefaultArgs: ['--enable-automation', '--disable-extensions']
})
await context.addInitScript(STEALTH)
const page = context.pages()[0] ?? (await context.newPage())

try {
  await page.goto('https://dzen.ru/', { waitUntil: 'domcontentloaded', timeout: 45_000 })
  await sleep(1500)
  step('home', page.url())
  const studio = page.locator('a[href*="/profile/editor/"]').first()
  if (await studio.isVisible().catch(() => false)) {
    await studio.click()
    await page.waitForURL(/\/profile\/editor\/[^/]+/i, { timeout: 20_000 }).catch(() => undefined)
  } else {
    await page.locator('[data-testid="profile-menu-wrapper"]').first().click({ timeout: 5000 }).catch(() => undefined)
    await page.getByText('Студия', { exact: true }).first().click({ timeout: 8000 }).catch(() => undefined)
    await page.waitForURL(/\/profile\/editor\/[^/]+/i, { timeout: 20_000 }).catch(() => undefined)
  }
  step('studio', page.url())

  let trigger = page.locator('[data-testid="select-trigger-button-comment"]').first()
  if (!(await trigger.isVisible().catch(() => false))) {
    await page.locator('[data-testid="add-publication-button"]').first().click({ timeout: 8000 })
    await sleep(400)
    await page.getByText('Загрузить видео', { exact: true }).first().click({ timeout: 8000 })
    const input = page.locator('input[name="video-popup__file"], input[type="file"][accept*="video"]').first()
    await input.waitFor({ state: 'attached', timeout: 20_000 })
    await input.setInputFiles(video)
    step('file', video)
    await page.waitForURL(/videoEditorPublicationId=/i, { timeout: 180_000 })
    await page.locator('[data-testid="select-trigger-button-comment"]').waitFor({ state: 'visible', timeout: 60_000 })
    trigger = page.locator('[data-testid="select-trigger-button-comment"]').first()
  }
  step('editor', page.url())
  report.currentComment = (await trigger.innerText().catch(() => '')).trim()
  await trigger.click({ timeout: 5000 })
  await sleep(600)
  report.options = await page.evaluate(() =>
    [...document.querySelectorAll('[role="option"], [role="menuitem"], [class*="select"] li, [class*="Menu"] [class*="item"]')]
      .map((el) => ({
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role'),
        test: el.getAttribute('data-testid'),
        aria: el.getAttribute('aria-label'),
        text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80)
      }))
      .filter((x) => x.text)
  )
  report.fields = await page.evaluate(() => {
    const tag = document.querySelector('input[placeholder="Добавьте теги"], [class*="tag-input__input"]')
    const title = document.querySelector('[data-testid="publication-custom-comments-title-input"]')
    const comment = document.querySelector('[data-testid="select-trigger-button-comment"]')
    return {
      tags: tag
        ? { tag: tag.tagName, placeholder: tag.getAttribute('placeholder'), cls: String(tag.className).slice(0, 120) }
        : null,
      commentTitle: title
        ? {
            tag: title.tagName,
            test: title.getAttribute('data-testid'),
            placeholder: title.getAttribute('placeholder'),
            max: title.getAttribute('maxlength')
          }
        : null,
      commentWho: comment
        ? { text: (comment.innerText || '').trim(), test: comment.getAttribute('data-testid') }
        : null
    }
  })
  await page.screenshot({ path: join(ROOT, 'scripts', 'dzen-live', 'comment-menu.png') }).catch(() => undefined)
  await page.keyboard.press('Escape').catch(() => undefined)
  step('options', JSON.stringify(report.options))
  step('fields', JSON.stringify(report.fields))
  step('publish', 'НЕ публикую')
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await page.screenshot({ path: join(ROOT, 'scripts', 'dzen-live', 'error.png') }).catch(() => undefined)
} finally {
  writeFileSync(OUT, JSON.stringify(report, null, 2), 'utf-8')
  await sleep(1200)
  await context.close().catch(() => undefined)
}
