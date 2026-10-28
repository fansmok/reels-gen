import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'rutube')
const OUT = join(ROOT, 'scripts', 'fix-live', 'rutube-category.json')
mkdirSync(join(ROOT, 'scripts', 'fix-live'), { recursive: true })
const video = join(ROOT, readdirSync(ROOT).find((n) => n.toLowerCase().endsWith('.mp4')))
const report = { published: false, steps: [] }
const step = (name, detail) => {
  report.steps.push({ t: new Date().toISOString(), name, detail })
  console.log(`[rutube] ${name} | ${String(detail || '').slice(0, 400)}`)
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
  await page.goto('https://studio.rutube.ru/?period=7_days&tab=main', { waitUntil: 'domcontentloaded', timeout: 45_000 })
  await page.locator('[data-testid="global-loader"]').waitFor({ state: 'hidden', timeout: 45_000 }).catch(() => undefined)
  await page.locator('[data-testid="header-add-button"]').click({ timeout: 10_000 })
  await page.locator('[data-testid="uploadVideo"]').click({ timeout: 8000 })
  await page.locator('input[type="file"][accept*="mp4"]').first().setInputFiles(video)
  await page.locator('input[name="title"]').waitFor({ state: 'visible', timeout: 90_000 })
  await sleep(1500)

  report.dom = await page.evaluate(() => {
    const layout = document.querySelector('[data-testid="video-editor-layout"]')
    if (!layout) return { error: 'no layout' }
    const nodes = [...layout.querySelectorAll('span, label, p, button, input, [role="combobox"], [aria-label]')]
      .filter((el) => {
        const t = `${el.getAttribute('aria-label') || ''} ${(el.innerText || '').trim()} ${el.getAttribute('placeholder') || ''}`
        return /категор|выбер|открыть|очистить|combobox|select/i.test(t) || el.getAttribute('role') === 'combobox'
      })
      .slice(0, 40)
      .map((el) => ({
        tag: el.tagName.toLowerCase(),
        aria: el.getAttribute('aria-label'),
        role: el.getAttribute('role'),
        ph: el.getAttribute('placeholder'),
        type: el.getAttribute('type'),
        labelled: el.getAttribute('aria-labelledby'),
        cls: String(el.className || '').slice(0, 80),
        text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80)
      }))
    const cat = [...layout.querySelectorAll('*')].find((el) => (el.childNodes[0]?.textContent || '').trim() === 'Категория' || el.textContent?.trim() === 'Категория')
    let row = cat
    for (let i = 0; i < 8 && row; i++) {
      if (row.querySelector('button[aria-label="Открыть"], input, [role="combobox"]')) break
      row = row.parentElement
    }
    return {
      nodes,
      rowHtml: row ? row.outerHTML.slice(0, 2500) : null,
      rowText: row ? (row.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200) : null
    }
  })
  await page.screenshot({ path: join(ROOT, 'scripts', 'fix-live', 'rutube-before.png') })

  const label = page.locator('[data-testid="video-editor-layout"]').getByText('Категория', { exact: true }).first()
  await label.scrollIntoViewIfNeeded()
  const open = page.locator('[data-testid="video-editor-layout"] button[aria-label="Открыть"]')
  const openCount = await open.count()
  step('open-buttons', String(openCount))
  const catOpen = label.locator('xpath=ancestor::*[.//button[@aria-label="Открыть"]][1]').getByRole('button', { name: 'Открыть' }).first()
  await catOpen.click({ timeout: 5000, force: true }).catch((e) => step('open-click-fail', e.message))
  await sleep(500)
  report.afterOpen = await page.evaluate(() => ({
    options: [...document.querySelectorAll('[role="option"], [role="listbox"] *, [class*="option"], [class*="menu"] li')]
      .map((el) => (el.innerText || '').replace(/\s+/g, ' ').trim())
      .filter((t) => t && t.length < 80)
      .slice(0, 50),
    listboxes: [...document.querySelectorAll('[role="listbox"], [class*="Menu"], [class*="dropdown"]')].map((el) =>
      (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200)
    )
  }))
  await page.keyboard.type('Разное', { delay: 30 }).catch(() => undefined)
  await sleep(400)
  const opt = page.getByRole('option', { name: 'Разное', exact: true }).first()
  if (await opt.isVisible().catch(() => false)) {
    await opt.click({ force: true })
    step('option', 'clicked role=option Разное')
  } else {
    await page.getByText('Разное', { exact: true }).last().click({ force: true, timeout: 4000 }).catch((e) => step('text-click-fail', e.message))
  }
  await sleep(500)
  report.afterSelect = (await page.locator('[data-testid="video-editor-layout"]').innerText()).replace(/\s+/g, ' ').slice(0, 400)
  await page.screenshot({ path: join(ROOT, 'scripts', 'fix-live', 'rutube-after.png') })
  step('after', report.afterSelect)
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
} finally {
  writeFileSync(OUT, JSON.stringify(report, null, 2), 'utf-8')
  await sleep(800)
  await context.close().catch(() => undefined)
}
