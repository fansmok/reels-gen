import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'youtube')
const OUT = join(ROOT, 'scripts', 'youtube-cover.json')
const STEALTH = `(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true })
  } catch {}
})()`

const log = []
function step(name, detail) {
  const row = { t: new Date().toISOString(), name, detail: detail ?? null }
  log.push(row)
  console.log(`[cover-scout] ${name}${detail ? ' | ' + String(detail).slice(0, 300) : ''}`)
}

function pickMedia() {
  const files = readdirSync(ROOT)
  const video = files.find((n) => n.toLowerCase().endsWith('.mp4'))
  const cover = files.find((n) => n.toLowerCase() === 'test-cover.png') || files.find((n) => n.toLowerCase().endsWith('.png'))
  if (!video) throw new Error('нет mp4 в корне проекта')
  if (!cover) throw new Error('нет png в корне проекта')
  return { videoPath: join(ROOT, video), coverPath: join(ROOT, cover) }
}

async function dumpUi(page, label) {
  const buttons = await page
    .locator('button, [role="button"], ytcp-button, ytcp-icon-button, tp-yt-paper-button, tp-yt-paper-icon-button')
    .evaluateAll((els) =>
      els.slice(0, 400).map((el, i) => ({
        i,
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        aria: el.getAttribute('aria-label') || '',
        name: el.getAttribute('name') || '',
        text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160),
        visible: !!(el.offsetParent || el.getClientRects().length)
      }))
    )
    .catch(() => [])
  const files = await page
    .locator('input[type="file"]')
    .evaluateAll((els) =>
      els.map((el, i) => ({
        i,
        id: el.id || '',
        name: el.getAttribute('name') || '',
        accept: el.getAttribute('accept') || '',
        aria: el.getAttribute('aria-label') || '',
        visible: !!(el.offsetParent || el.getClientRects().length)
      }))
    )
    .catch(() => [])
  const thumb = await page
    .evaluate(() => {
      const names = [
        'ytcp-thumbnails-compact-editor',
        'ytcp-thumbnails-compact-editor-uploader-old',
        'ytcp-thumbnail-uploader',
        'ytcp-video-thumbnail-editor',
        'ytcp-video-still-picker',
        'ytcp-uploads-still-editor',
        'ytcp-thumbnail-editor',
        '#file-loader',
        '#thumbnail-editor',
        'ytcp-video-thumbnail-with-info'
      ]
      const found = []
      for (const sel of names) {
        const el = document.querySelector(sel)
        if (!el) continue
        found.push({
          sel,
          tag: el.tagName,
          id: el.id,
          text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 400)
        })
      }
      function walkShadow(node, acc, depth) {
        if (!node || depth > 8) return
        const root = node.shadowRoot
        if (root) {
          for (const el of root.querySelectorAll('button, [role="button"], input[type="file"], ytcp-button, ytcp-icon-button')) {
            acc.push({
              tag: el.tagName.toLowerCase(),
              id: el.id || '',
              name: el.getAttribute('name') || '',
              accept: el.getAttribute('accept') || '',
              aria: el.getAttribute('aria-label') || '',
              text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120)
            })
          }
          for (const child of root.querySelectorAll('*')) walkShadow(child, acc, depth + 1)
        }
      }
      const shadow = []
      for (const host of document.querySelectorAll(
        'ytcp-uploads-dialog, ytcp-thumbnails-compact-editor, ytcp-thumbnail-uploader, ytcp-video-thumbnail-editor, ytcp-thumbnails-compact-editor-uploader-old'
      )) {
        walkShadow(host, shadow, 0)
      }
      return { found, shadow: shadow.slice(0, 200) }
    })
    .catch(() => ({ found: [], shadow: [] }))
  const coverRelated = buttons.filter((b) =>
    /облож|заставк|миниатюр|значок|thumb|cover|файл|file-loader|загрузить|upload/i.test(`${b.id} ${b.aria} ${b.text} ${b.name}`)
  )
  return {
    label,
    url: page.url(),
    buttonCount: buttons.length,
    fileCount: files.length,
    buttons,
    files,
    coverRelated,
    thumbComponents: thumb.found || [],
    thumbShadow: thumb.shadow || []
  }
}

async function progressText(page) {
  const loc = page.locator('ytcp-video-upload-progress').first()
  if ((await loc.count()) === 0) return ''
  return ((await loc.innerText().catch(() => '')) || '').replace(/\s+/g, ' ').trim().slice(0, 400)
}

async function waitProcessed(page, timeout = 600_000) {
  const doneRe =
    /проверк[аи] завершен|checks complete|no issues found|проблем не обнаружено|finished processing|обработка завершена|processing complete/i
  const uploadingRe = /загрузка\s+\d|uploading\s+\d|видео загружается|идёт загрузка|идет загрузка|left to upload/i
  const processingRe =
    /скоро начнется обработка|проверка:\s*\d|обработка(?! завершена)|processing hd|processing sd|encoding|checking your video|hd processing|sd processing|осталось \d/i
  const deadline = Date.now() + timeout
  let readyHits = 0
  let last = ''
  let seenBusy = false
  let emptyHits = 0
  while (Date.now() < deadline) {
    const text = await progressText(page)
    const pcts = [...text.matchAll(/(\d+)\s*%/g)].map((m) => Number(m[1]))
    const pct = pcts.length ? Math.max(...pcts) : null
    const done = doneRe.test(text)
    const uploading = uploadingRe.test(text)
    const processing = processingRe.test(text) && !done
    const busy = uploading || processing || (pct !== null && pct < 100 && !done)
    if (busy) seenBusy = true
    if (text !== last) {
      step('processing wait', `${pct ?? '—'}% ${text.slice(0, 200) || '(пусто)'}`)
      last = text
    }
    if (!busy && (done || (seenBusy && pct !== null && pct >= 100) || (seenBusy && !text))) {
      readyHits += 1
      if (readyHits >= 6) {
        step('processing wait', 'готово')
        return text
      }
    } else readyHits = 0
    if (!busy && !text) {
      emptyHits += 1
      if (emptyHits >= 40) {
        step('processing wait', 'нет виджета прогресса 20с — продолжаю к обложке')
        return text
      }
    } else emptyHits = 0
    await sleep(500)
  }
  step('processing wait', 'таймаут — продолжаю к обложке')
  return await progressText(page)
}

async function trySetCover(page, coverPath, report) {
  const chain = []
  const record = (action, ok, extra) => {
    const row = { action, ok, extra: extra ?? null }
    chain.push(row)
    step('cover', `${action} → ${ok}${extra ? ' | ' + extra : ''}`)
  }

  const fileLoader = page.locator('#file-loader').first()
  if ((await fileLoader.count()) > 0) {
    try {
      await fileLoader.setInputFiles(coverPath)
      record('setInputFiles #file-loader', true)
      await sleep(1200)
      return chain
    } catch (e) {
      record('setInputFiles #file-loader', false, e instanceof Error ? e.message : String(e))
    }
  } else {
    record('setInputFiles #file-loader', false, 'элемент не найден')
  }

  const imageInputs = page.locator(
    'ytcp-thumbnails-compact-editor-uploader-old input[type="file"], ytcp-thumbnail-uploader input[type="file"], input[type="file"][accept*="image"], input[type="file"]#file-loader'
  )
  const imgCount = await imageInputs.count()
  record('image file inputs count', imgCount > 0, String(imgCount))
  for (let i = 0; i < imgCount; i++) {
    try {
      await imageInputs.nth(i).setInputFiles(coverPath)
      record(`setInputFiles image-input[${i}]`, true)
      await sleep(1200)
      return chain
    } catch (e) {
      record(`setInputFiles image-input[${i}]`, false, e instanceof Error ? e.message : String(e))
    }
  }

  const clickNames = [
    /загрузить файл/i,
    /upload file/i,
    /upload thumbnail/i,
    /custom thumbnail/i,
    /своя обложка/i,
    /загрузить обложку/i,
    /изменить миниатюру/i,
    /миниатюра/i,
    /thumbnail/i
  ]
  for (const name of clickNames) {
    const btn = page.getByRole('button', { name }).first()
    if (!(await btn.isVisible().catch(() => false))) continue
    const label = `${await btn.getAttribute('aria-label')} ${(await btn.innerText().catch(() => '')).slice(0, 80)}`
    if (/справк|help|спросить|ask studio|далее|next|опублик|publish|закрыть|close/i.test(label)) continue
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 5000 }).catch(() => null)
    await btn.click({ timeout: 3000 }).catch(() => undefined)
    record(`click button ${label.trim()}`, true)
    await sleep(600)
    const after = await dumpUi(page, `after-click:${label.trim()}`)
    report.snapshots.push(after)
    const chooser = await chooserPromise
    if (chooser) {
      await chooser.setFiles(coverPath)
      record('filechooser.setFiles', true)
      await sleep(1200)
      return chain
    }
    if ((await page.locator('#file-loader').count()) > 0) {
      try {
        await page.locator('#file-loader').first().setInputFiles(coverPath)
        record('setInputFiles #file-loader after click', true)
        await sleep(1200)
        return chain
      } catch (e) {
        record('setInputFiles #file-loader after click', false, e instanceof Error ? e.message : String(e))
      }
    }
  }

  const thumbClick = page.locator(
    'ytcp-thumbnails-compact-editor, ytcp-thumbnail-uploader, #thumbnail-editor, ytcp-video-thumbnail-editor'
  ).first()
  if (await thumbClick.isVisible().catch(() => false)) {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 4000 }).catch(() => null)
    await thumbClick.click({ timeout: 3000 }).catch(() => undefined)
    record('click thumbnail editor root', true)
    const chooser = await chooserPromise
    if (chooser) {
      await chooser.setFiles(coverPath)
      record('filechooser after editor root', true)
      await sleep(1200)
      return chain
    }
  }

  record('cover not set', false, 'ни один способ не сработал')
  return chain
}

async function confirmCrop(page) {
  await sleep(800)
  const ids = page.locator('#save-button, ytcp-button#save-button, #done-button:not([aria-label*="опублик" i])').first()
  if (await ids.isVisible().catch(() => false)) {
    const aria = await ids.getAttribute('aria-label')
    if (!/опублик|publish/i.test(aria || '')) {
      await ids.click({ timeout: 4000 }).catch(() => undefined)
      step('cover', 'crop save/done')
      return
    }
  }
  const btn = page.getByRole('button', { name: /^(готово|сохранить|применить|done|save|apply)$/i }).last()
  if (await btn.isVisible().catch(() => false)) {
    await btn.click({ timeout: 4000 }).catch(() => undefined)
    step('cover', 'crop confirm by name')
  }
}

const report = {
  startedAt: new Date().toISOString(),
  session: SESSION,
  media: pickMedia(),
  published: false,
  snapshots: [],
  chain: [],
  progress: [],
  error: null,
  steps: log
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
await context.addInitScript(STEALTH)
const page = context.pages()[0] ?? (await context.newPage())
context.on('page', (p) => {
  if (p === page) return
  step('window', `лишняя вкладка ${p.url()} — закрываю`)
  void p.close().catch(() => undefined)
})

try {
  step('goto', 'https://studio.youtube.com')
  await page.goto('https://studio.youtube.com', { waitUntil: 'domcontentloaded', timeout: 60_000 }).catch(async (e) => {
    if (!/ERR_HTTP_RESPONSE_CODE_FAILURE|ERR_ABORTED/i.test(String(e))) throw e
    await page.waitForLoadState('domcontentloaded').catch(() => undefined)
  })
  await sleep(1500)
  if (await page.getByText(/ПЕРЕЙТИ В ПРИЛОЖЕНИЕ|Switch to app|unsupported browser/i).count()) {
    step('goto', 'approve_browser_access')
    await page.goto('https://studio.youtube.com/?approve_browser_access=true', { waitUntil: 'domcontentloaded', timeout: 60_000 })
  }
  step('goto', page.url())

  const fileUiEarly = page.locator('#select-files-button, input[name="Filedata"], ytcp-uploads-dialog')
  if ((await fileUiEarly.count()) > 0 && (await fileUiEarly.first().isVisible().catch(() => false))) {
    step('create', 'диалог загрузки уже открыт')
  } else {
    const uploadIcon = page.locator('#upload-icon, ytcp-icon-button#upload-icon').first()
    const createBtn = page.locator('button[aria-label="Создать"]').first()
    await uploadIcon.or(createBtn).waitFor({ state: 'visible', timeout: 25_000 }).catch(() => undefined)
    if ((await uploadIcon.count()) > 0) {
      step('create', '#upload-icon aria Добавить видео')
      await uploadIcon.click({ timeout: 8000, force: true })
    } else if (await createBtn.isVisible().catch(() => false)) {
      step('create', 'button[aria-label=Создать]')
      await createBtn.click()
    } else {
      throw new Error('нет кнопки загрузки')
    }
  }
  const menu = page.locator('#text-item-0').first()
  const fileUi = page.locator('#select-files-button, input[name="Filedata"]')
  const until = Date.now() + 15_000
  while (Date.now() < until) {
    if ((await fileUi.count()) > 0) break
    if (await menu.isVisible().catch(() => false)) {
      step('create', '#text-item-0 Загрузить видео')
      await menu.click().catch(() => undefined)
    }
    await sleep(200)
  }
  await fileUi.first().waitFor({ state: 'attached', timeout: 15_000 })
  step('create', 'диалог выбора файла')

  const videoInput = page.locator('ytcp-uploads-dialog input[name="Filedata"], input[name="Filedata"]').first()
  step('file', report.media.videoPath)
  await videoInput.setInputFiles(report.media.videoPath)
  await page.locator('#title-textarea #textbox, #title-textarea textarea').first().waitFor({ state: 'visible', timeout: 45_000 })
  step('file', 'форма деталей открыта')

  const titleBox = page.locator('#title-textarea #textbox, #title-textarea textarea').first()
  await titleBox.click()
  await page.keyboard.press('Control+A')
  await titleBox.fill('Тест обложки (не публиковать)')
  await page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').first().click({ timeout: 4000 }).catch(() => undefined)

  const processed = await waitProcessed(page)
  report.progress.push(processed)

  const thumbRoot = page.locator(
    'ytcp-thumbnails-compact-editor, ytcp-video-thumbnail-editor, #thumbnail-editor, ytcp-thumbnail-uploader, ytcp-uploads-dialog'
  ).first()
  await thumbRoot.evaluate((el) => {
    const node =
      el.querySelector('ytcp-thumbnails-compact-editor, ytcp-video-thumbnail-editor, #thumbnail-editor') || el
    node.scrollIntoView({ block: 'center' })
  }).catch(() => undefined)
  await page.locator('#file-loader, ytcp-thumbnails-compact-editor').first().scrollIntoViewIfNeeded().catch(() => undefined)
  await page.getByText(/миниатюра|значок|thumbnail/i).first().scrollIntoViewIfNeeded().catch(() => undefined)
  await sleep(500)

  report.snapshots.push(await dumpUi(page, 'cover-step-before'))
  writeFileSync(OUT, JSON.stringify({ ...report, steps: log }, null, 2), 'utf-8')
  step('write', 'dump обложки')
  mkdirSync(join(ROOT, 'scripts'), { recursive: true })
  await page.screenshot({ path: join(ROOT, 'scripts', 'youtube-cover-before.png'), fullPage: false }).catch(() => undefined)

  report.chain = await trySetCover(page, report.media.coverPath, report)
  await confirmCrop(page)
  await sleep(1500)
  report.snapshots.push(await dumpUi(page, 'cover-step-after'))
  await page.screenshot({ path: join(ROOT, 'scripts', 'youtube-cover-after.png'), fullPage: false }).catch(() => undefined)

  step('publish', 'НЕ публикую — dryRun')
  report.finishedAt = new Date().toISOString()
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await page.screenshot({ path: join(ROOT, 'scripts', 'youtube-cover-error.png'), fullPage: false }).catch(() => undefined)
  try {
    report.snapshots.push(await dumpUi(page, 'error'))
  } catch {
    /* ignore */
  }
} finally {
  writeFileSync(OUT, JSON.stringify(report, null, 2), 'utf-8')
  step('write', OUT)
  await sleep(1500)
  await context.close().catch(() => undefined)
}
