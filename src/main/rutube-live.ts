import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { closePlatformBrowser, openPlatformBrowser } from './browser'
import { dismissNuisances, safeGoto } from './uploaders/helpers'

function media(): { video: string; cover: string } {
  const root = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
  const files = readdirSync(root)
  const video = files.find((n) => n.toLowerCase().endsWith('.mp4'))
  const cover = files.find((n) => n.toLowerCase() === 'test-cover.png') || files.find((n) => n.toLowerCase().endsWith('.png'))
  if (!video || !cover) throw new Error('Нет тестового mp4 или png')
  return { video: join(root, video), cover: join(root, cover) }
}

async function snap(page: import('playwright-core').Page, label: string): Promise<unknown> {
  const data = await page.evaluate(() => {
    const vis = (el: Element): boolean => {
      const s = getComputedStyle(el as HTMLElement)
      const r = (el as HTMLElement).getBoundingClientRect()
      return s.display !== 'none' && s.visibility !== 'hidden' && r.width + r.height > 0
    }
    const buttons = [...document.querySelectorAll('button, [role="button"], input[type="file"]')]
      .filter((el) => vis(el) || el.tagName === 'INPUT')
      .map((el) => {
        const html = el as HTMLButtonElement
        return {
          tag: html.tagName.toLowerCase(),
          text: (html.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 90),
          aria: html.getAttribute('aria-label'),
          type: html.getAttribute('type'),
          accept: html.getAttribute('accept'),
          disabled: Boolean((html as HTMLButtonElement).disabled) || html.getAttribute('aria-disabled') === 'true'
        }
      })
    return { url: location.href, buttons }
  })
  return { label, ...(data as object) }
}

export async function liveRutube(): Promise<void> {
  const outDir = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА', 'scripts', 'rutube-live')
  mkdirSync(outDir, { recursive: true })
  const files = media()
  const log: unknown[] = []
  const { page } = await openPlatformBrowser('rutube')
  await safeGoto(page, 'https://studio.rutube.ru')
  await page.locator('[data-testid="global-loader"]').waitFor({ state: 'hidden', timeout: 45_000 }).catch(() => undefined)
  await dismissNuisances(page)
  await page.keyboard.press('Escape').catch(() => undefined)
  await page.getByRole('button', { name: /^закрыть$/i }).first().click({ timeout: 1500 }).catch(() => undefined)

  await page.locator('[data-testid="header-add-button"]').click({ timeout: 10_000 })
  await page.locator('[data-testid="uploadVideo"]').click({ timeout: 8000 })
  await sleep(600)
  const fileInput = page.locator('input[type="file"][accept*="mp4"], input[type="file"][accept*=".mp4"]').first()
  if ((await fileInput.count()) > 0) {
    await fileInput.setInputFiles(files.video)
  } else {
    const chooserP = page.waitForEvent('filechooser', { timeout: 12_000 })
    await page.getByRole('button', { name: /выбрать файлы/i }).click({ timeout: 8000 })
    await (await chooserP).setFiles(files.video)
  }

  const publish = page.locator('button[type="submit"]').filter({ hasText: /^Опубликовать$/i }).last()
  await publish.waitFor({ state: 'visible', timeout: 60_000 })
  const deadline = Date.now() + 180_000
  while (Date.now() < deadline) {
    const disabled = await publish.isDisabled().catch(() => true)
    log.push({ step: 'publish-state', disabled, t: Date.now() })
    if (!disabled) break
    await sleep(1000)
  }
  log.push(await snap(page, 'ready'))

  const editCover = page.getByRole('button', { name: /редактировать обложку/i }).first()
  const pickFrame = page.getByRole('button', { name: /выбрать кадр из видео/i }).first()
  const coverTarget = (await editCover.isVisible().catch(() => false)) ? editCover : pickFrame
  const chooserP = page.waitForEvent('filechooser', { timeout: 12_000 }).catch(() => null)
  await coverTarget.click({ timeout: 8000 })
  await sleep(1000)
  log.push(await snap(page, 'cover-dialog'))
  await page.screenshot({ path: join(outDir, 'cover-dialog.png') }).catch(() => undefined)

  const uploadBtns = ['Загрузить', 'Загрузить файл', 'С компьютера', 'Выбрать файл', 'Добавить файл', 'Загрузить обложку']
  for (const name of uploadBtns) {
    const b = page.getByRole('button', { name: new RegExp(`^${name}$`, 'i') }).first()
    if (await b.isVisible().catch(() => false)) {
      await b.click().catch(() => undefined)
      log.push({ clicked: name })
      break
    }
  }
  const chooser = await chooserP
  if (chooser) {
    await chooser.setFiles(files.cover)
    log.push({ step: 'cover-chooser-ok' })
  } else {
    const img = page.locator('input[type="file"][accept*="image"], input[type="file"][accept*="png"], input[type="file"][accept*="jpg"]')
    if ((await img.count()) > 0) {
      await img.last().setInputFiles(files.cover)
      log.push({ step: 'cover-input-ok' })
    } else {
      log.push({ step: 'no-image-input' })
    }
  }
  await sleep(800)
  await page.getByRole('button', { name: /^(сохранить|готово|применить)$/i }).last().click({ timeout: 4000 }).catch(() => undefined)
  await sleep(1200)
  log.push(await snap(page, 'after-cover'))
  await page.screenshot({ path: join(outDir, 'after-cover.png') }).catch(() => undefined)

  writeFileSync(join(outDir, 'cover.json'), JSON.stringify(log, null, 2), 'utf-8')
  await closePlatformBrowser('rutube')
}
