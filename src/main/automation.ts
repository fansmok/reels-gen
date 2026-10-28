import { telegramArmed, type GeneratorAutomation, type GeneratorSettings } from '../shared/generator'
import { enabledTargets } from '../shared/targets'
import type { AutomationStatus, ProgressEvent } from '../shared/types'
import { cancelGenerator, generateToQueue, generatorInfo, isGeneratorBusy, saveGeneratorSettings } from './generator'
import { getRunner, isQueueRunning, startQueue, stopQueue } from './scheduler'
import { getGeneratorSettings, getPersisted } from './store'
import { getPlatformProfiles } from './yt-plain'

/**
 * Автоматизация генератора: по расписанию собрать ролики → Kie-тексты → очередь → заливка.
 * Один активный цикл; пропущенный запуск выполняется один раз при старте программы.
 */

const TICK_MS = 15_000
const HOUR = 3_600_000
const DAY = 24 * HOUR

let timer: NodeJS.Timeout | null = null
let cycleRunning = false
let startedQueue = false
let lastMessage = ''
let lastError = ''
let lastResult = ''
const listeners = new Set<() => void>()
let progressSink: ((event: ProgressEvent) => void) | null = null

export function onAutomationChange(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function setAutomationProgressSink(sink: (event: ProgressEvent) => void): void {
  progressSink = sink
}

function notify(): void {
  for (const cb of listeners) cb()
}

function say(message: string, level: ProgressEvent['level'] = 'info', scope = 'Автоматизация'): void {
  lastMessage = message
  progressSink?.({ message: `${scope}: ${message}`, level })
  notify()
}

function parseHm(text: string): { h: number; m: number } {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(text || '').trim())
  if (!match) return { h: 10, m: 0 }
  return { h: Math.min(23, Number(match[1])), m: Math.min(59, Number(match[2])) }
}

function atTime(day: Date, hm: string): Date {
  const { h, m } = parseHm(hm)
  const d = new Date(day)
  d.setHours(h, m, 0, 0)
  return d
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

/** Когда следующий запуск по расписанию. `null` — выключено. */
export function nextRunAt(auto: GeneratorAutomation, now = new Date()): Date | null {
  if (!auto.enabled) return null
  const last = auto.lastRun ? new Date(auto.lastRun) : null
  const lastOk = last && !Number.isNaN(last.getTime()) ? last : null
  if (auto.mode === 'interval') {
    if (!lastOk) return now
    return new Date(lastOk.getTime() + Math.max(1, auto.intervalH) * HOUR)
  }
  if (auto.mode === 'daily') {
    const today = atTime(now, auto.time)
    if (lastOk && sameDay(lastOk, now)) return atTime(new Date(now.getTime() + DAY), auto.time)
    // сегодня ещё не запускали: если время прошло — пропущенный запуск сразу
    return today
  }
  // раз в N дней
  if (!lastOk) return atTime(now, auto.daysTime)
  const base = new Date(lastOk)
  base.setDate(base.getDate() + Math.max(1, auto.days))
  return atTime(base, auto.daysTime)
}

export function isDue(auto: GeneratorAutomation, now = new Date()): boolean {
  const next = nextRunAt(auto, now)
  return !!next && next.getTime() <= now.getTime()
}

/** Подпись «верхнего» источника: новый файл в папке 1 или другая ссылка. */
async function topSignature(settings: GeneratorSettings): Promise<string> {
  if (settings.topMode === 'telegram') return 'telegram'
  if (settings.topMode === 'link') return `link:${settings.topUrl.trim()}`
  const info = await generatorInfo()
  if (!info.tops.length) return ''
  const newest = info.tops.reduce((a, b) => (b.mtime > a.mtime ? b : a))
  if (settings.topMode === 'single') {
    const chosen = info.tops.find((t) => t.path === settings.topFile) ?? newest
    return `${chosen.path}|${chosen.size}|${chosen.mtime}`
  }
  if (settings.topMode === 'all') return info.tops.map((t) => `${t.name}|${t.size}|${t.mtime}`).join(';')
  return `${newest.path}|${newest.size}|${newest.mtime}`
}

export function getAutomationStatus(): AutomationStatus {
  const settings = getGeneratorSettings()
  const next = nextRunAt(settings.auto)
  return {
    enabled: settings.auto.enabled,
    cycleRunning,
    nextRun: next ? next.toISOString() : undefined,
    lastRun: settings.auto.lastRun || undefined,
    lastMessage,
    lastError: lastError || undefined,
    lastResult: lastResult || undefined
  }
}

/** Один цикл: генерация → тексты → очередь → заливка. Возвращает false, если цикл пропущен. */
export async function runCycle(reason: 'schedule' | 'manual' = 'schedule'): Promise<boolean> {
  if (cycleRunning) {
    say('цикл уже идёт — новый не запускаю', 'warn')
    return false
  }
  if (isGeneratorBusy()) {
    say('генератор занят вручную — жду', 'warn')
    return false
  }
  cycleRunning = true
  lastError = ''
  notify()
  const settings = getGeneratorSettings()
  try {
    const targets = enabledTargets(getPlatformProfiles(), getPersisted().targets).map((t) => t.id)
    if (!targets.length) throw new Error('не отмечено ни одного направления в «Аккаунтах»')

    let sig = ''
    if (settings.auto.onlyNew && reason === 'schedule') {
      sig = await topSignature(settings)
      if (!sig) throw new Error('папка 1 пуста — нечего генерировать')
      if (sig === settings.auto.lastTopSig) {
        saveGeneratorSettings({ auto: { ...settings.auto, lastRun: new Date().toISOString() } })
        say('нового верхнего ролика нет — пропускаю до следующего раза')
        return false
      }
    } else if (settings.auto.onlyNew) {
      sig = await topSignature(settings).catch(() => '')
    }

    say(`старт цикла (${reason === 'manual' ? 'вручную' : 'по расписанию'}): направлений ${targets.length}`)
    const { result, jobs } = await generateToQueue(settings, targets)
    lastResult = `роликов ${result.items.length}, заданий ${jobs.length}`
    saveGeneratorSettings({
      auto: { ...getGeneratorSettings().auto, lastRun: new Date().toISOString(), lastTopSig: sig || settings.auto.lastTopSig }
    })
    if (jobs.length && getRunner() === 'idle') {
      startedQueue = true
      startQueue()
      say(`в очередь ушло ${jobs.length}, заливка запущена`, 'success')
    } else if (jobs.length) {
      say(`в очередь ушло ${jobs.length}, очередь уже работает`, 'success')
    } else {
      say('роликов не получилось — заданий нет', 'warn')
    }
    return true
  } catch (error) {
    lastError = error instanceof Error ? error.message : String(error)
    saveGeneratorSettings({ auto: { ...getGeneratorSettings().auto, lastRun: new Date().toISOString() } })
    say(`ошибка: ${lastError}`, 'error')
    return false
  } finally {
    cycleRunning = false
    notify()
  }
}

export interface IncomingLinkResult {
  ok: boolean
  busy?: boolean
  cancelled?: boolean
  message: string
  videos: number
  jobs: number
  jobIds: string[]
}

/** Ролик, который пользователь прислал боту: ссылка или уже скачанный файл. */
export interface IncomingMedia {
  kind: 'url' | 'file'
  url: string
  path: string
  /** Своими словами, о чём верхний ролик. Для файла без ссылки по этому тексту Kie пишет название. */
  note?: string
}

/** Сборка из Telegram. Верх и низ подменяются только на этот прогон, остальные настройки остаются. */
export async function runIncomingPair(top: IncomingMedia | null, bottom: IncomingMedia | null): Promise<IncomingLinkResult> {
  if (cycleRunning) return { ok: false, busy: true, message: 'цикл уже идёт', videos: 0, jobs: 0, jobIds: [] }
  if (isGeneratorBusy()) return { ok: false, busy: true, message: 'генератор занят', videos: 0, jobs: 0, jobIds: [] }
  cycleRunning = true
  lastError = ''
  notify()
  const base = getGeneratorSettings()
  let settings: GeneratorSettings = {
    ...base,
    transcript: '',
    transcriptVideo: ''
  }
  if (top?.kind === 'url' && top.url) {
    settings = { ...settings, topMode: 'link', topUrl: top.url, linkedPath: '', linkedKey: '' }
  } else if (top?.kind === 'file' && top.path) {
    settings = { ...settings, topMode: 'single', topFile: top.path, topUrl: '', linkedPath: '', linkedKey: '' }
  }
  const extra: Record<string, unknown> = {}
  const note = top?.note?.trim() || ''
  if (note) extra.sourceNote = note
  if (bottom?.kind === 'url' && bottom.url) extra.bottomUrl = bottom.url
  if (bottom?.kind === 'file' && bottom.path) extra.bottomFile = bottom.path
  try {
    const targets = enabledTargets(getPlatformProfiles(), getPersisted().targets).map((t) => t.id)
    if (!targets.length) throw new Error('не отмечено ни одного направления в «Аккаунтах»')
    say(`ролик из Telegram принят, направлений ${targets.length}`, 'info', 'Telegram')
    const { result, jobs } = await generateToQueue(settings, targets, undefined, { extra, oneReel: !!bottom })
    lastResult = `роликов ${result.items.length}, заданий ${jobs.length}`
    if (jobs.length && getRunner() === 'idle') {
      startedQueue = true
      startQueue()
      say(`в очередь ушло ${jobs.length}, заливка запущена`, 'success', 'Telegram')
    } else if (jobs.length) {
      say(`в очередь ушло ${jobs.length}, очередь уже работает`, 'success', 'Telegram')
    } else {
      say('роликов не получилось — заданий нет', 'warn', 'Telegram')
    }
    return { ok: jobs.length > 0, message: lastResult, videos: result.items.length, jobs: jobs.length, jobIds: jobs.map((job) => job.id) }
  } catch (error) {
    lastError = error instanceof Error ? error.message : String(error)
    const cancelled = /останов/i.test(lastError)
    if (!cancelled) say(`ошибка: ${lastError}`, 'error', 'Telegram')
    return { ok: false, cancelled, message: lastError, videos: 0, jobs: 0, jobIds: [] }
  } finally {
    cycleRunning = false
    notify()
  }
}

async function tick(): Promise<void> {
  const settings = getGeneratorSettings()
  if (!settings.auto.enabled || cycleRunning) return
  if (telegramArmed(settings)) return
  if (!isDue(settings.auto)) return
  if (isGeneratorBusy() || (isQueueRunning() && getRunner() !== 'idle')) {
    // не наслаиваем цикл на ручную работу/заливку — проверим на следующем тике
    return
  }
  await runCycle('schedule')
}

export function startAutomation(): void {
  if (timer) return
  timer = setInterval(() => void tick(), TICK_MS)
  // пропущенный запуск — один раз при старте программы, с небольшой задержкой на подключение движка
  setTimeout(() => void tick(), 20_000)
}

let onStop: (() => void) | null = null

/** Очередь ссылок из Telegram сбрасывается вместе с остановкой цикла. */
export function setAutomationStopHook(fn: () => void): void {
  onStop = fn
}

/** Выключение автоматизации: остановить текущую генерацию и заливку, которую запустил цикл. */
export function stopAutomation(): void {
  onStop?.()
  cancelGenerator()
  if (startedQueue) {
    stopQueue()
    startedQueue = false
  }
  say('остановлено', 'warn')
}

export function shutdownAutomation(): void {
  if (timer) clearInterval(timer)
  timer = null
}
