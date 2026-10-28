const { mkdirSync, readdirSync, writeFileSync } = require('fs')
const { join } = require('path')
const { setTimeout: sleep } = require('node:timers/promises')
const { chromium } = require('playwright-core')

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'rutube')
const OUT = join(ROOT, 'scripts', 'rutube-cover.json')
const HELP_RE = /academy|for_creators|\/info\/faq|support|help|invalid-content/i

function media() {
  const names = readdirSync(ROOT)
  const video = names.find((n) => n.toLowerCase().endsWith('.mp4'))
  const cover = names.find((n) => n.toLowerCase() === 'test-cover.png') || names.find((n) => n.toLowerCase().endsWith('.png'))
  if (!video || !cover) throw new Error('Нет тестового mp4 или png')
  return { video: join(ROOT, video), cover: join(ROOT, cover), videoName: video, coverName: cover }
}

async function closeExtras(page) {
  for (const extra of page.context().pages()) {
    if (extra === page || extra.isClosed()) continue
    const url = extra.url()
    if (HELP_RE.test(url) || /rutube\.ru\/info|rutube\.ru\/for_creators/i.test(url)) {
      await extra.close().catch(() => undefined)
    }
  }
}

function dumpCoverFn() {
  const vis = (el) => {
    const s = getComputedStyle(el)
    const r = el.getBoundingClientRect()
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width + r.height > 0
  }
  const info = (el) => {
    const html = el
    return {
      tag: html.tagName.toLowerCase(),
      role: html.getAttribute('role'),
      type: html.getAttribute('type'),
      name: html.getAttribute('name'),
      id: html.id || null,
      testid: html.getAttribute('data-testid') || html.getAttribute('data-test-id') || html.getAttribute('data-e2e'),
      aria: html.getAttribute('aria-label'),
      ariaSelected: html.getAttribute('aria-selected'),
      ariaChecked: html.getAttribute('aria-checked'),
      accept: html.getAttribute('accept'),
      text: (html.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 140),
      checked: typeof html.checked === 'boolean' ? html.checked : null,
      disabled: Boolean(html.disabled) || html.getAttribute('aria-disabled') === 'true',
      href: html.getAttribute('href'),
      cls: String(html.className || '').slice(0, 160)
    }
  }
  const smallestExact = (text) =>
    [...document.querySelectorAll('button, [role="button"], [role="tab"], [role="radio"], label, span, a, p, div, li, h1, h2, h3, h4')]
      .filter((el) => vis(el) && (el.innerText || '').replace(/\s+/g, ' ').trim() === text)
      .sort((a, b) => a.innerText.length - b.innerText.length)
      .slice(0, 8)
      .map((el) => ({
        ...info(el),
        parentTag: el.parentElement ? el.parentElement.tagName.toLowerCase() : null,
        parentRole: el.parentElement ? el.parentElement.getAttribute('role') : null,
        parentText: el.parentElement ? (el.parentElement.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160) : null
      }))

  const editor = document.querySelector('[data-testid="video-editor-layout"]')
  const headings = smallestExact('Обложка')
  const own = smallestExact('Загрузить свою')
  const frame = smallestExact('Выбрать кадр из видео')
  const bumper = smallestExact('Указать заставку')

  let section = headings[0]
    ? [...document.querySelectorAll('button, [role], label, span, a, p, div, li, h1, h2, h3, h4')].find(
        (el) => vis(el) && (el.innerText || '').replace(/\s+/g, ' ').trim() === 'Обложка'
      )
    : null
  if (section) {
    let cur = section
    for (let i = 0; i < 12 && cur.parentElement; i++) {
      cur = cur.parentElement
      const t = (cur.innerText || '').replace(/\s+/g, ' ')
      if (t.includes('Загрузить свою') || t.includes('Выбрать кадр')) {
        section = cur
        if (t.length > 800) break
      }
    }
  }

  const collect = (root) => {
    if (!root) return []
    return [...root.querySelectorAll('button, [role="button"], [role="tab"], [role="radio"], input, label')]
      .filter((el) => vis(el) || el.tagName === 'INPUT')
      .map(info)
      .filter((x) => x.text || x.aria || x.accept || x.type === 'file' || x.type === 'radio' || x.role || x.testid)
  }

  return {
    url: location.href,
    editorPresent: Boolean(editor),
    headingОбложка: headings,
    загрузитьСвою: own,
    выбратьКадр: frame,
    указатьЗаставку: bumper,
    sectionText: section ? (section.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 600) : null,
    sectionControls: collect(section),
    editorCoverControls: collect(editor).filter((x) =>
      /облож|загрузит|кадр|заставк|cover|png|image|файл|jpg|jpeg/i.test(`${x.text} ${x.aria} ${x.accept} ${x.testid}`)
    ),
    allFileInputs: [...document.querySelectorAll('input[type="file"]')].map(info),
    visibleRadios: [...document.querySelectorAll('input[type="radio"], [role="radio"]')].filter(vis).map(info),
    visibleTabs: [...document.querySelectorAll('[role="tab"]')].filter(vis).map(info),
    publish: [...document.querySelectorAll('button[type="submit"]')]
      .filter((el) => /опубликовать/i.test(el.innerText || ''))
      .map(info)
  }
}

async function main() {
  const files = media()
  const log = {
    startedAt: new Date().toISOString(),
    files,
    steps: [],
    beforeOwnClick: null,
    afterOwnClick: null,
    afterFile: null,
    clicks: [],
    error: null
  }

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
  context.on('page', (p) => {
    p.waitForLoadState('domcontentloaded')
      .then(() => {
        const url = p.url()
        if (HELP_RE.test(url)) void p.close().catch(() => undefined)
      })
      .catch(() => undefined)
  })

  const page = context.pages()[0] || (await context.newPage())
  try {
    await page.goto('https://studio.rutube.ru/?period=7_days&tab=main', { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await page.locator('[data-testid="global-loader"]').waitFor({ state: 'hidden', timeout: 45_000 }).catch(() => undefined)
    await page.keyboard.press('Escape').catch(() => undefined)
    await page.locator('button[aria-label="closeIcon"]').click({ timeout: 1500 }).catch(() => undefined)
    await closeExtras(page)
    log.steps.push({ step: 'studio', url: page.url() })

    await page.locator('[data-testid="header-add-button"]').click({ timeout: 10_000 })
    log.steps.push({ step: 'add' })
    const uploadVideo = page.locator('[data-testid="uploadVideo"]')
    await uploadVideo.waitFor({ state: 'visible', timeout: 10_000 })
    const uploadLabel = ((await uploadVideo.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim()
    log.steps.push({ step: 'uploadVideo', text: uploadLabel, testid: 'uploadVideo' })
    await uploadVideo.click({ timeout: 5000 })
    await sleep(500)
    await closeExtras(page)

    const videoInput = page.locator('input[type="file"][accept*=".mp4"], input[type="file"][accept*="mp4"]').first()
    await videoInput.waitFor({ state: 'attached', timeout: 20_000 })
    const videoAccept = await videoInput.getAttribute('accept')
    log.steps.push({ step: 'video-input', accept: videoAccept })
    await videoInput.setInputFiles(files.video)

    const publish = page.locator('button[type="submit"]').filter({ hasText: /^Опубликовать$/i }).last()
    await publish.waitFor({ state: 'visible', timeout: 90_000 })
    const deadline = Date.now() + 180_000
    while (Date.now() < deadline) {
      const disabled = await publish.isDisabled().catch(() => true)
      const aria = await publish.getAttribute('aria-disabled').catch(() => null)
      log.steps.push({ step: 'publish-wait', disabled, ariaDisabled: aria, t: Date.now() })
      if (!disabled && aria !== 'true') break
      await closeExtras(page)
      await sleep(1000)
    }
    const enabled = !(await publish.isDisabled()) && (await publish.getAttribute('aria-disabled')) !== 'true'
    log.steps.push({ step: 'publish-ready', enabled, didNotClickPublish: true })
    if (!enabled) throw new Error('Опубликовать так и не стала enabled за 3 мин')

    await page.locator('[data-testid="video-editor-layout"]').waitFor({ state: 'visible', timeout: 20_000 }).catch(() => undefined)
    const heading = page.getByText('Обложка', { exact: true }).first()
    await heading.scrollIntoViewIfNeeded().catch(() => undefined)
    await sleep(400)
    log.beforeOwnClick = await page.evaluate(dumpCoverFn)
    await page.screenshot({ path: join(ROOT, 'scripts', 'rutube-cover-before.png') }).catch(() => undefined)

    const own = page.getByText('Загрузить свою', { exact: true }).first()
    const ownVisible = await own.isVisible().catch(() => false)
    log.clicks.push({
      action: 'scroll-обложка',
      headingVisible: await heading.isVisible().catch(() => false),
      ownVisible
    })
    if (!ownVisible) {
      await heading.click({ timeout: 2500 }).catch(() => undefined)
      await sleep(400)
    }

    const chooserP = page.waitForEvent('filechooser', { timeout: 8000 }).catch(() => null)
    const tab = page.getByRole('tab', { name: /^загрузить свою$/i }).first()
    const radio = page.getByRole('radio', { name: /загрузить свою/i }).first()
    const btn = page.getByRole('button', { name: /^загрузить свою$/i }).first()
    const how =
      (await tab.isVisible().catch(() => false)) && 'tab' ||
      (await radio.isVisible().catch(() => false)) && 'radio' ||
      (await btn.isVisible().catch(() => false)) && 'button' ||
      (await own.isVisible().catch(() => false)) && 'text' ||
      null
    if (!how) throw new Error('На живой странице нет «Загрузить свою»')
    const target = how === 'tab' ? tab : how === 'radio' ? radio : how === 'button' ? btn : own
    await target.scrollIntoViewIfNeeded().catch(() => undefined)
    await target.click({ timeout: 5000 }).catch(async () => target.click({ force: true, timeout: 3000 }))
    log.clicks.push({ action: 'Загрузить свою', how, skipped: 'Выбрать кадр из видео / Указать заставку' })
    await sleep(800)
    log.afterOwnClick = await page.evaluate(dumpCoverFn)

    const chooser = await chooserP
    if (chooser) {
      await chooser.setFiles(files.cover)
      log.clicks.push({ action: 'setFiles', via: 'filechooser', cover: files.coverName })
    } else {
      const image = page.locator(
        'input[type="file"][accept*="image"], input[type="file"][accept*="png"], input[type="file"][accept*="jpg"], input[type="file"][accept*="jpeg"]'
      )
      if ((await image.count()) > 0) {
        await image.last().setInputFiles(files.cover)
        log.clicks.push({
          action: 'setInputFiles',
          via: 'image-input',
          accept: await image.last().getAttribute('accept'),
          cover: files.coverName
        })
      } else {
        const again = page.waitForEvent('filechooser', { timeout: 10000 }).catch(() => null)
        const pick = page
          .locator('[data-testid="video-editor-layout"]')
          .getByRole('button', { name: /^(выбрать файл|загрузить файл|с компьютера)$/i })
          .first()
        if (await pick.isVisible().catch(() => false)) {
          await pick.click({ timeout: 4000 })
          log.clicks.push({ action: 'pick-file-button', text: await pick.innerText() })
        }
        const second = await again
        if (second) {
          await second.setFiles(files.cover)
          log.clicks.push({ action: 'setFiles', via: 'filechooser-2', cover: files.coverName })
        } else {
          log.clicks.push({ action: 'no-image-input-after-own-click' })
        }
      }
    }

    await sleep(1000)
    const cropSave = page.getByRole('button', { name: /^(сохранить|готово|применить)$/i }).last()
    if (await cropSave.isVisible().catch(() => false)) {
      const label = (await cropSave.innerText().catch(() => '')).trim()
      if (!/^опубликовать$/i.test(label)) {
        await cropSave.click({ timeout: 4000 }).catch(() => undefined)
        log.clicks.push({ action: 'crop-confirm', text: label })
      }
    }
    await sleep(800)
    log.afterFile = await page.evaluate(dumpCoverFn)
    await page.screenshot({ path: join(ROOT, 'scripts', 'rutube-cover-after.png') }).catch(() => undefined)
    log.steps.push({ step: 'done-no-publish' })
  } catch (error) {
    log.error = error instanceof Error ? error.stack || error.message : String(error)
    await page.screenshot({ path: join(ROOT, 'scripts', 'rutube-cover-error.png') }).catch(() => undefined)
    log.afterOwnClick = log.afterOwnClick || (await page.evaluate(dumpCoverFn).catch(() => null))
  } finally {
    mkdirSync(join(ROOT, 'scripts'), { recursive: true })
    writeFileSync(OUT, JSON.stringify(log, null, 2), 'utf-8')
    await context.close().catch(() => undefined)
  }
}

main().catch((error) => {
  writeFileSync(OUT, JSON.stringify({ error: String(error) }, null, 2), 'utf-8')
  console.error(error)
  process.exit(1)
})
