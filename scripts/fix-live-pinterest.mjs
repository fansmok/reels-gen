import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'pinterest')
const OUT = join(ROOT, 'scripts', 'fix-live', 'pinterest-publish.json')
mkdirSync(join(ROOT, 'scripts', 'fix-live'), { recursive: true })
const video = join(ROOT, readdirSync(ROOT).find((n) => n.toLowerCase().endsWith('.mp4')))
const report = { published: false, steps: [] }
const step = (name, detail) => {
  report.steps.push({ t: new Date().toISOString(), name, detail })
  console.log(`[pinterest] ${name} | ${String(detail || '').slice(0, 400)}`)
}

const context = await chromium.launchPersistentContext(SESSION, {
  channel: 'chrome',
  headless: false,
  viewport: null,
  locale: 'ru-RU',
  timezoneId: 'Europe/Moscow',
  args: ['--disable-blink-features=AutomationControlled', '--start-maximized'],
  ignoreDefaultArgs: ['--enable-automation']
})
const page = context.pages()[0] ?? (await context.newPage())
try {
  await page.goto('https://ru.pinterest.com/pin-creation-tool/', { waitUntil: 'domcontentloaded', timeout: 45_000 })
  await sleep(2000)
  const create = page.locator('[data-test-id="storyboard-create-button"]').first()
  if ((await page.locator('#storyboard-upload-input').count()) === 0 && (await create.isVisible().catch(() => false))) {
    await create.click()
    await sleep(800)
  }
  const input = page.locator('#storyboard-upload-input, [data-test-id="storyboard-upload-input"]').first()
  await input.waitFor({ state: 'attached', timeout: 25_000 })
  await input.setInputFiles(video)
  step('file', 'set')
  await page.locator('#storyboard-selector-title').waitFor({ state: 'visible', timeout: 60_000 })
  await page.locator('#storyboard-selector-title').fill('Тест (не публиковать если кнопка серая)')
  await sleep(1500)

  report.btn = await page.evaluate(() => {
    const wrap = document.querySelector('[data-test-id="storyboard-creation-nav-done"]')
    const btn = wrap?.querySelector('button') || wrap
    if (!btn) return { missing: true }
    const r = btn.getBoundingClientRect()
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
    return {
      tag: btn.tagName,
      text: (btn.innerText || '').replace(/\s+/g, ' ').trim(),
      disabled: btn.disabled,
      aria: btn.getAttribute('aria-disabled'),
      cls: String(btn.className || '').slice(0, 160),
      wrapText: wrap ? (wrap.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120) : null,
      saving: /saving|сохран/i.test(document.body.innerText),
      saved: !!document.querySelector('[data-test-id="saving-status-saved"]'),
      topAtClick: top ? `${top.tagName}.${String(top.className).slice(0, 60)} ${(top.innerText || '').slice(0, 40)}` : null
    }
  })
  step('btn', JSON.stringify(report.btn))
  await page.screenshot({ path: join(ROOT, 'scripts', 'fix-live', 'pinterest-ready.png') })

  const delayed = page.getByText(/publish at a later date|опубликовать позже/i).first()
  report.scheduleVisible = await delayed.isVisible().catch(() => false)

  const pub = page.getByRole('button', { name: /^(publish|опубликовать)$/i }).first()
  report.roleCount = await page.getByRole('button', { name: /publish|опубликовать/i }).count()
  report.roleTexts = await page.getByRole('button', { name: /publish|опубликовать/i }).evaluateAll((els) =>
    els.map((el) => ({
      text: (el.innerText || '').trim().slice(0, 40),
      disabled: el.disabled,
      aria: el.getAttribute('aria-disabled')
    }))
  )
  step('roles', JSON.stringify(report.roleTexts))
  step('publish', 'НЕ жму Publish — только дамп')
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await page.screenshot({ path: join(ROOT, 'scripts', 'fix-live', 'pinterest-error.png') }).catch(() => undefined)
} finally {
  writeFileSync(OUT, JSON.stringify(report, null, 2), 'utf-8')
  await sleep(800)
  await context.close().catch(() => undefined)
}
