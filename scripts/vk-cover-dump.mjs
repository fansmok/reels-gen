import { chromium } from 'playwright-core'
import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'

const ROOT = join(process.env.USERPROFILE, 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA, 'reels-uploader', 'sessions', 'vk')
const OUT = join(ROOT, 'scripts', 'vk-cover.json')
const video = join(ROOT, readdirSync(ROOT).find((n) => n.toLowerCase().endsWith('.mp4')))
const cover = join(ROOT, 'test-cover.png')

const dump = {
  startedAt: new Date().toISOString(),
  video,
  cover,
  steps: []
}

function rec(el) {
  const html = el
  const cs = getComputedStyle(html)
  const r = html.getBoundingClientRect()
  return {
    tag: html.tagName.toLowerCase(),
    type: html.getAttribute('type'),
    id: html.id || undefined,
    name: html.getAttribute('name') || undefined,
    accept: html.getAttribute('accept') || undefined,
    aria: html.getAttribute('aria-label') || undefined,
    test:
      html.getAttribute('data-testid') ||
      html.getAttribute('data-test-id') ||
      html.getAttribute('data-e2e') ||
      undefined,
    role: html.getAttribute('role') || undefined,
    disabled: html.disabled || html.getAttribute('aria-disabled') || undefined,
    hidden: html.hidden || cs.display === 'none' || cs.visibility === 'hidden' || r.width < 1 || r.height < 1,
    cls: (html.className && String(html.className).slice(0, 140)) || undefined,
    text: (html.innerText || html.value || '').replace(/\s+/g, ' ').trim().slice(0, 120) || undefined,
    href: html.getAttribute('href') || undefined
  }
}

async function snapshot(page, label) {
  const data = await page.evaluate((recordSrc) => {
    const rec = eval(`(${recordSrc})`)
    const modal =
      document.querySelector('[data-testid="modalbox"]') ||
      document.querySelector('[role="dialog"]') ||
      document.body
    const all = [...document.querySelectorAll('input,button,a,[role="button"],[contenteditable="true"],textarea,[data-testid],[aria-label]')]
    const interesting = all
      .map(rec)
      .filter((x) => {
        const blob = JSON.stringify(x).toLowerCase()
        return /облож|cover|thumb|застав|кадр|file|upload|клип|опубл|описан|video|image|png|jpeg|выбр|загруз/i.test(blob)
      })
      .slice(0, 120)
    const files = [...document.querySelectorAll('input[type="file"]')].map(rec)
    const coverish = all
      .map(rec)
      .filter((x) => /облож|cover|thumb|застав|кадр|miniatura/i.test(JSON.stringify(x).toLowerCase()))
    const publish = document.querySelector('[data-testid="clips-uploadForm-publish-button"]')
    return {
      url: location.href,
      title: document.title,
      modalText: (modal.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 1500),
      publish: publish
        ? rec(publish)
        : null,
      files,
      coverish,
      interesting
    }
  }, rec.toString())
  dump.steps.push({ label, at: new Date().toISOString(), ...data })
  console.log('STEP', label, 'url=', data.url, 'files=', data.files.length, 'coverish=', data.coverish.length)
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
context.on('page', (p) => {
  void (async () => {
    await p.waitForLoadState('domcontentloaded').catch(() => undefined)
    const u = p.url()
    if (/ads\.vk|help\.vk|\/support|\/faq|\/help|vkads|advert/i.test(u)) {
      console.log('CLOSE extra', u)
      await p.close().catch(() => undefined)
    }
  })()
})

const page = context.pages()[0] ?? (await context.newPage())
page.on('dialog', (d) => void d.dismiss())

try {
  await page.goto('https://vk.ru/clips', { waitUntil: 'domcontentloaded', timeout: 60_000 }).catch(() => undefined)
  await page.waitForTimeout(2500)
  await snapshot(page, 'clips-home')

  const add =
    page.locator('[data-testid="clips-publish-button"]').first()
  if (await add.isVisible().catch(() => false)) {
    await add.click({ timeout: 8000 })
  } else {
    await page.getByRole('button', { name: /добавить клип|создать клип/i }).first().click({ timeout: 8000 })
  }
  await page.locator('[data-testid="modalbox"], input[type="file"]').first().waitFor({ state: 'attached', timeout: 20_000 })
  await page.waitForTimeout(1200)
  await snapshot(page, 'modal-before-video')

  const videoInput = page
    .locator('[data-testid="modalbox"] input[type="file"][accept*="video"], [data-testid="video_upload_select_file"], input[type="file"][accept*="video"]')
    .first()
  await videoInput.waitFor({ state: 'attached', timeout: 15_000 })
  await videoInput.setInputFiles(video)
  await snapshot(page, 'just-after-video')

  const publish = page.locator('[data-testid="clips-uploadForm-publish-button"]').first()
  const deadline = Date.now() + 180_000
  while (Date.now() < deadline) {
    const text = (await page.locator('[data-testid="modalbox"]').first().innerText().catch(() => '')).replace(/\s+/g, ' ')
    const disabled = (await publish.isDisabled().catch(() => true)) || (await publish.getAttribute('aria-disabled')) === 'true'
    const busy = /загрузк|обработк|uploading|processing|осталось/i.test(text) && !/готов|успешн|100\s*%/i.test(text)
    if (!busy && !disabled && (await publish.count()) > 0) break
    await page.waitForTimeout(800)
  }
  await snapshot(page, 'after-processing')

  const modal = page.locator('[data-testid="modalbox"]').first()
  const coverBtn = modal.getByRole('button', { name: /облож|cover|застав|выбрать обложку|загрузить облож/i }).first()
  const coverText = modal.getByText(/выбрать обложку|загрузить облож|обложка|cover/i).first()
  const coverInput = modal.locator('input[aria-label*="облож" i], input[aria-label*="cover" i], input[type="file"][accept*="image"]').first()

  dump.coverProbe = {
    buttonVisible: await coverBtn.isVisible().catch(() => false),
    buttonText: await coverBtn.innerText().catch(() => ''),
    buttonAria: await coverBtn.getAttribute('aria-label').catch(() => null),
    textVisible: await coverText.isVisible().catch(() => false),
    text: await coverText.innerText().catch(() => ''),
    inputCount: await coverInput.count().catch(() => 0),
    inputAria: await coverInput.getAttribute('aria-label').catch(() => null),
    inputAccept: await coverInput.getAttribute('accept').catch(() => null),
    inputTest: await coverInput.getAttribute('data-testid').catch(() => null)
  }

  if (dump.coverProbe.inputCount > 0) {
    try {
      await coverInput.setInputFiles(cover)
      dump.coverProbe.setInputFiles = 'ok'
    } catch (e) {
      dump.coverProbe.setInputFiles = e instanceof Error ? e.message : String(e)
    }
    await page.waitForTimeout(1500)
    await snapshot(page, 'after-cover-setInputFiles')
  }

  if (dump.coverProbe.buttonVisible && dump.coverProbe.setInputFiles !== 'ok') {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 8_000 }).catch(() => null)
    await coverBtn.click({ timeout: 4000 })
    const chooser = await chooserPromise
    dump.coverProbe.filechooserAfterButton = Boolean(chooser)
    if (chooser) {
      await chooser.setFiles(cover)
      dump.coverProbe.chooserSetFiles = 'ok'
    }
    await page.waitForTimeout(1500)
    await snapshot(page, 'after-cover-button')
  } else if (dump.coverProbe.textVisible && dump.coverProbe.setInputFiles !== 'ok') {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 8_000 }).catch(() => null)
    await coverText.click({ timeout: 4000 })
    const chooser = await chooserPromise
    dump.coverProbe.filechooserAfterText = Boolean(chooser)
    if (chooser) {
      await chooser.setFiles(cover)
      dump.coverProbe.chooserSetFiles = 'ok'
    }
    await page.waitForTimeout(1500)
    await snapshot(page, 'after-cover-text-click')
  }

  await snapshot(page, 'final-no-publish')
  dump.finalUrl = page.url()
  dump.published = false
} catch (error) {
  dump.error = error instanceof Error ? error.message : String(error)
  console.error(dump.error)
  try {
    await snapshot(page, 'error')
  } catch {
    /* ignore */
  }
} finally {
  mkdirSync(join(ROOT, 'scripts'), { recursive: true })
  writeFileSync(OUT, JSON.stringify(dump, null, 2), 'utf-8')
  console.log('WROTE', OUT)
  await page.waitForTimeout(1500)
  await context.close()
}
