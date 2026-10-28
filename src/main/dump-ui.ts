import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { closePlatformBrowser, openPlatformBrowser } from './browser'
import { dismissNuisances, safeGoto } from './uploaders/helpers'
import type { PlatformId } from '../shared/types'

async function dumpButtons(page: import('playwright-core').Page): Promise<unknown[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll('button, a, [role="button"], [role="menuitem"], input, [data-test-id], [data-testid]')]
      .slice(0, 180)
      .map((el) => {
        const html = el as HTMLElement
        return {
          tag: html.tagName.toLowerCase(),
          id: html.id,
          test: html.getAttribute('data-test-id') || html.getAttribute('data-testid') || html.getAttribute('data-e2e'),
          aria: html.getAttribute('aria-label'),
          text: (html.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80),
          href: html.getAttribute('href'),
          type: html.getAttribute('type'),
          name: html.getAttribute('name')
        }
      })
      .filter((x) => x.text || x.aria || x.test || x.id)
  )
}

export async function dumpPlatforms(): Promise<void> {
  const out: Record<string, unknown> = {}
  const jobs: Array<{ id: PlatformId; url: string; label: string }> = [
    { id: 'rutube', url: 'https://studio.rutube.ru', label: 'studio' }
  ]
  for (const job of jobs) {
    const { page } = await openPlatformBrowser(job.id)
    await safeGoto(page, job.url)
    await dismissNuisances(page)
    if (job.id === 'rutube') {
      await page.locator('[data-testid="global-loader"]').waitFor({ state: 'hidden', timeout: 45_000 }).catch(() => undefined)
      await page.locator('[data-testid="header-add-button"]').click({ timeout: 8000 })
      await page.locator('[data-testid="uploadVideo"]').waitFor({ state: 'visible', timeout: 10_000 })
      await page.locator('[data-testid="uploadVideo"]').click()
      const video = readdirSync(join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')).find((n) =>
        n.toLowerCase().endsWith('.mp4')
      )
      if (video) {
        const filePath = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА', video)
        const input = page.locator('input[type="file"]').first()
        await input.setInputFiles(filePath).catch(async () => {
          const chooser = page.waitForEvent('filechooser', { timeout: 12_000 })
          await page.getByText(/загрузить|выбрать файл|select file/i).first().click({ timeout: 5000 }).catch(() => undefined)
          await (await chooser).setFiles(filePath)
        })
        await page.locator('input[name="title"]').waitFor({ state: 'visible', timeout: 90_000 }).catch(() => undefined)
        await page.waitForTimeout(2000)
      }
    }
    if (job.id === 'pinterest') {
      await page.waitForTimeout(2000)
      await page.locator('[data-test-id="onboarding-module-create-pin-button"]').click({ timeout: 8000, force: true }).catch(() => undefined)
      await page.waitForTimeout(2500)
      const pages = page.context().pages()
      const last = pages[pages.length - 1]
      out[`${job.id}-after-create`] = { url: last.url(), title: await last.title(), items: await dumpButtons(last) }
    }
    out[`${job.id}-${job.label}`] = { url: page.url(), title: await page.title(), items: await dumpButtons(page) }
    await closePlatformBrowser(job.id)
  }
  const dir = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА', 'scripts')
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'ui-dump.json'), JSON.stringify(out, null, 2), 'utf-8')
}
