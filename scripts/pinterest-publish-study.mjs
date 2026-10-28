import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { chromium } from 'playwright-core'

const ROOT = join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
const SESSION = join(process.env.APPDATA || '', 'reels-uploader', 'sessions', 'pinterest')
const OUT_DIR = join(ROOT, 'scripts', 'pinterest-study')
const VIDEO = join(ROOT, 'Человек-Паук1.mp4')
mkdirSync(OUT_DIR, { recursive: true })

const log = []
const step = (name, detail) => {
  const row = { t: new Date().toISOString(), name, detail: detail ?? null }
  log.push(row)
  console.log(`[study] ${name}${detail ? ' | ' + String(detail).slice(0, 500) : ''}`)
}

const report = {
  startedAt: new Date().toISOString(),
  url: 'https://ru.pinterest.com/pin-creation-tool/',
  published: false,
  network: [],
  snapshots: []
}

function trackNetwork(page) {
  page.on('response', async (res) => {
    const url = res.url()
    if (
      !/pinterest\.(com|ru)/i.test(url) ||
      !/resource|graphql|create|publish|story|pin|upload|video/i.test(url)
    ) {
      return
    }
    if (/\.(js|css|png|jpg|webp|woff2|svg|ico)(\?|$)/i.test(url)) return
    const item = {
      t: new Date().toISOString(),
      status: res.status(),
      method: res.request().method(),
      url: url.slice(0, 280)
    }
    try {
      const ct = res.headers()['content-type'] || ''
      if (/json/i.test(ct) && res.status() < 500) {
        const text = await res.text().catch(() => '')
        item.body = text.slice(0, 600)
      }
    } catch {
      /* ignore */
    }
    report.network.push(item)
    if (/create|publish|storypin|v3\/pins/i.test(url)) {
      step('net', `${item.status} ${item.method} ${item.url}`)
    }
  })
}

async function dump(page, label) {
  const data = await page
    .evaluate(() => {
      const vis = (el) => {
        const s = getComputedStyle(el)
        const r = el.getBoundingClientRect()
        return s.display !== 'none' && s.visibility !== 'hidden' && r.width + r.height > 2
      }
      const wrap = document.querySelector('[data-test-id="storyboard-creation-nav-done"]')
      const btn = wrap?.querySelector('button') || wrap
      let hit = null
      if (btn) {
        const r = btn.getBoundingClientRect()
        const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
        hit = top
          ? {
              tag: top.tagName,
              id: top.id,
              test: top.getAttribute('data-test-id'),
              cls: String(top.className || '').slice(0, 80),
              text: (top.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60),
              isButton: top === btn || btn.contains(top)
            }
          : null
      }
      const statusEls = [...document.querySelectorAll('[data-test-id*="saving"], [data-test-id*="status"]')].map(
        (el) => ({
          test: el.getAttribute('data-test-id'),
          text: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 80),
          vis: vis(el)
        })
      )
      const alerts = [...document.querySelectorAll('[role="alert"], [role="status"], [data-test-id*="toast"]')].map(
        (el) => (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160)
      )
      const dialogs = [...document.querySelectorAll('[role="dialog"]')].map((el) =>
        (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 220)
      )
      const buttons = [...document.querySelectorAll('button, [role="button"]')]
        .filter(vis)
        .slice(0, 40)
        .map((el) => ({
          test: el.getAttribute('data-test-id') || '',
          text: (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 70),
          disabled: !!el.disabled,
          aria: el.getAttribute('aria-disabled')
        }))
      const bodyHit = /Saving|Saved|Сохран|Publish|Опубликовать|published|Processing|Uploading/i.test(
        document.body.innerText
      )
        ? (document.body.innerText.match(/Saving[^\n]{0,20}|Saved[^\n]{0,20}|Сохран[^\n]{0,20}|Publish[^\n]{0,20}|published[^\n]{0,40}|Processing[^\n]{0,20}|Uploading[^\n]{0,20}/gi) ||
            []
          ).slice(0, 12)
        : []
      return {
        url: location.href,
        title: document.title,
        header: (
          document.querySelector('[data-test-id="storyboard-create-header-heading"]')?.innerText || ''
        )
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 120),
        files: [...document.querySelectorAll('input[type="file"]')].map((el) => ({
          id: el.id,
          test: el.getAttribute('data-test-id'),
          accept: (el.getAttribute('accept') || '').slice(0, 160)
        })),
        btn: btn
          ? {
              tag: btn.tagName,
              text: (btn.innerText || '').replace(/\s+/g, ' ').trim(),
              disabled: btn.disabled,
              aria: btn.getAttribute('aria-disabled'),
              wrap: wrap ? (wrap.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120) : null
            }
          : null,
        hit,
        statusEls,
        alerts,
        dialogs,
        buttons,
        bodyHit
      }
    })
    .catch((e) => ({ error: e.message, url: page.url() }))
  report.snapshots.push({ label, t: new Date().toISOString(), ...data })
  step('dump', `${label} url=${data.url || page.url()}`)
  return data
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
await context.addInitScript(`(() => {
  try { Object.defineProperty(Navigator.prototype, 'webdriver', { get: () => undefined, configurable: true }) } catch {}
})()`)
const page = context.pages()[0] ?? (await context.newPage())
trackNetwork(page)

try {
  step('goto', 'https://ru.pinterest.com/pin-creation-tool/')
  await page.goto('https://ru.pinterest.com/pin-creation-tool/', { waitUntil: 'domcontentloaded', timeout: 45_000 })
  await sleep(2500)
  step('landed', page.url())
  await dump(page, 'open')
  await page.screenshot({ path: join(OUT_DIR, '01-open.png') })

  const create = page.locator('[data-test-id="storyboard-create-button"]').first()
  const createVis = await create.isVisible().catch(() => false)
  const inputCount = await page.locator('#storyboard-upload-input, [data-test-id="storyboard-upload-input"]').count()
  step('create-new', `visible=${createVis} input=${inputCount}`)
  if (createVis) {
    await create.click({ timeout: 5000 })
    step('click', 'storyboard-create-button новый черновик')
    await sleep(1500)
    await dump(page, 'after-create-new')
    await page.screenshot({ path: join(OUT_DIR, '02-new-draft.png') })
  }

  const input = page.locator('#storyboard-upload-input, [data-test-id="storyboard-upload-input"]').first()
  await input.waitFor({ state: 'attached', timeout: 25_000 })
  const accept = await input.getAttribute('accept')
  step('input', `accept=${accept}`)
  await input.setInputFiles(VIDEO)
  step('file', VIDEO)
  await sleep(2000)
  await dump(page, 'after-file')
  await page.screenshot({ path: join(OUT_DIR, '03-after-file.png') })

  const title = page.locator('#storyboard-selector-title').first()
  await title.waitFor({ state: 'visible', timeout: 90_000 })
  await title.fill('Тест публикации pin-creation-tool')
  step('title', 'заполнено')

  const desc = page.locator('[data-test-id="editor-with-mentions"] [contenteditable="true"]').first()
  if (await desc.isVisible().catch(() => false)) {
    await desc.fill('Описание теста конструктора пинов')
    step('desc', 'заполнено')
  }

  step('wait-saved', 'ждём Saved / нет Saving… и hit=button')
  const deadline = Date.now() + 120_000
  let ready = null
  while (Date.now() < deadline) {
    ready = await page.evaluate(() => {
      const wrap = document.querySelector('[data-test-id="storyboard-creation-nav-done"]')
      const btn = wrap?.querySelector('button')
      const body = document.body.innerText || ''
      const saving = /Saving|Сохранен|Сохранение|Сохраняем/i.test(body) && !/Saved|Сохранено/i.test(body)
      const savedEl = !!document.querySelector('[data-test-id="saving-status-saved"]')
      const savedText = /Saved|Сохранено/i.test(body)
      let hitIsBtn = false
      if (btn) {
        const r = btn.getBoundingClientRect()
        const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
        hitIsBtn = !!(top && (top === btn || btn.contains(top)))
      }
      return {
        saving,
        savedEl,
        savedText,
        hitIsBtn,
        disabled: btn ? btn.disabled : true,
        text: btn ? (btn.innerText || '').trim() : '',
        bodyHits: (body.match(/Saving[^\n]{0,24}|Saved[^\n]{0,24}|Сохран[^\n]{0,24}/g) || []).slice(0, 8)
      }
    })
    step('ready?', JSON.stringify(ready))
    if (ready && !ready.saving && !ready.disabled && ready.hitIsBtn && (ready.savedEl || ready.savedText || ready.text)) {
      await sleep(800)
      const again = await page.evaluate(() => /Saving…|Saving\.\.\.|Сохранение/i.test(document.body.innerText || ''))
      if (!again) break
    }
    await sleep(1200)
  }
  await dump(page, 'before-publish')
  await page.screenshot({ path: join(OUT_DIR, '04-before-publish.png') })

  const wrap = page.locator('[data-test-id="storyboard-creation-nav-done"]').first()
  step('publish', 'native click на обёртку storyboard-creation-nav-done')
  await wrap.evaluate((el) => {
    const btn = el.querySelector('button') || el
    btn.click()
  })
  await sleep(1500)
  await dump(page, '1.5s-after-click')
  await page.screenshot({ path: join(OUT_DIR, '05-after-click.png') })

  for (let i = 0; i < 12; i++) {
    await sleep(2000)
    const snap = await dump(page, `after-${(i + 1) * 2}s`)
    const joined = JSON.stringify(snap).toLowerCase()
    if (/published|пин опубликован|your pin|pin created|черновик удал/i.test(joined)) {
      report.published = true
      step('success-ui', `на ${(i + 1) * 2}s`)
      break
    }
  }
  await page.screenshot({ path: join(OUT_DIR, '06-final.png') })
  report.finalUrl = page.url()
  report.tabs = context.pages().map((p) => p.url())
} catch (e) {
  report.error = e instanceof Error ? e.message : String(e)
  step('ERROR', report.error)
  await page.screenshot({ path: join(OUT_DIR, 'error.png') }).catch(() => undefined)
} finally {
  report.steps = log
  report.finishedAt = new Date().toISOString()
  writeFileSync(join(OUT_DIR, 'study.json'), JSON.stringify(report, null, 2), 'utf-8')
  step('write', join(OUT_DIR, 'study.json'))
  await sleep(2500)
  await context.close().catch(() => undefined)
}
