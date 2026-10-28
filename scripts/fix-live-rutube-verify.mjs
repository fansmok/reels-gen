import { readdirSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'rutube')
const video = join(ROOT, readdirSync(ROOT).find((n) => n.toLowerCase().endsWith('.mp4')))
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
  const field = page.locator('[data-control-name="category"]').first()
  await field.waitFor({ state: 'visible', timeout: 20_000 })
  await field.scrollIntoViewIfNeeded()
  await field.locator('[role="combobox"]').first().click({ timeout: 5000 })
  await sleep(400)
  const input = field.locator('input[type="text"]').first()
  await input.fill('Разное')
  await sleep(400)
  const option = page.getByRole('option', { name: 'Разное', exact: true }).first()
  if (await option.isVisible().catch(() => false)) {
    await option.click({ force: true })
    console.log('clicked option')
  } else {
    await page.keyboard.press('Enter')
    console.log('pressed Enter')
  }
  await sleep(600)
  const after = (await field.innerText()).replace(/\s+/g, ' ')
  console.log('AFTER', after)
  const ok = after.includes('Разное') && !/выберите категори/i.test(after)
  console.log(ok ? 'CATEGORY_OK' : 'CATEGORY_FAIL')
} catch (e) {
  console.error('ERROR', e instanceof Error ? e.message : e)
} finally {
  await context.close().catch(() => undefined)
}
