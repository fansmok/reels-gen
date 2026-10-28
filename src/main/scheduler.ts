import { existsSync } from 'fs'
import { randomUUID } from 'crypto'
import { setTimeout as sleep } from 'node:timers/promises'
import type { BrowserContext, Page } from 'playwright-core'
import { getPlatform, hasVideoTitle, usesHashtags } from '../shared/platforms'
import { distributeTargets, parseTargetId, platformsOfTargets, targetLabel } from '../shared/targets'
import type {
  HistoryEntry,
  NewVideoPayload,
  PlatformId,
  PlatformResult,
  ProgressEvent,
  QueueRunnerStatus,
  TargetId,
  VideoJob
} from '../shared/types'
import { closeAllBrowsers, closePlatformBrowser, openPlatformBrowser } from './browser'
import { getPersisted, patchPersisted } from './store'
import { adapters } from './uploaders'
import { captureReelLink, hasChallenge, isStopError, waitIfChallenge, withRetry } from './uploaders/helpers'
import { recentUploadLogHint, uploadLog, uploadLogError } from './uploaders/upload-log'
import { mergePublishOptions, type DzenPublishOptions, type TiktokPublishOptions } from '../shared/publish-options'
import {
  allAccountProfiles,
  closeAccountProfile,
  closeAllYoutubeProfiles,
  getOpenAccountProfile,
  openAccountProfile,
  uploadLaunchMode
} from './yt-plain'

type Listener = () => void
const listeners = new Set<Listener>()
const progressListeners = new Set<(event: ProgressEvent) => void>()

let runner: QueueRunnerStatus = 'idle'
let paused = false
let stopped = false
let running = false
let stressUploads = false
const PLATFORM_UPLOAD_TIMEOUT_MS = 12 * 60_000

export function setStressUploads(value: boolean): void {
  stressUploads = value
}

export function onStoreChange(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function onProgress(fn: (event: ProgressEvent) => void): () => void {
  progressListeners.add(fn)
  return () => progressListeners.delete(fn)
}

function emit(): void {
  listeners.forEach((fn) => fn())
}

function progress(event: ProgressEvent): void {
  progressListeners.forEach((fn) => fn(event))
}

export function getRunner(): QueueRunnerStatus {
  return runner
}

export function isQueueRunning(): boolean {
  return running
}

function setRunner(status: QueueRunnerStatus): void {
  runner = status
  emit()
}

function label(target: TargetId): string {
  return targetLabel(target, allAccountProfiles())
}

function platformOf(target: TargetId): PlatformId {
  return parseTargetId(target)?.platform ?? 'youtube'
}

function buildJob(payload: NewVideoPayload, targets: TargetId[]): VideoJob {
  const { targets: _ignored, ...rest } = payload
  void _ignored
  return {
    id: randomUUID(),
    ...rest,
    targets,
    enabledPlatforms: platformsOfTargets(targets),
    status: 'queued',
    results: Object.fromEntries(targets.map((id) => [id, { status: 'pending' }])),
    createdAt: new Date().toISOString()
  }
}

export function addJob(payload: NewVideoPayload): VideoJob {
  const targets = payload.targets && payload.targets.length > 0 ? [...payload.targets] : [...payload.enabledPlatforms]
  const job = buildJob(payload, targets)
  const persisted = getPersisted()
  patchPersisted({ jobs: [...persisted.jobs, job] })
  emit()
  return job
}

/**
 * Пачка роликов: по настройкам YouTube либо каждый ролик во все каналы,
 * либо раздать по каналам без повторов (не больше N на канал).
 */
export function addJobBatch(payloads: NewVideoPayload[]): VideoJob[] {
  if (payloads.length === 0) return []
  const settings = getPersisted().settings
  const baseTargets =
    payloads[0].targets && payloads[0].targets.length > 0 ? [...payloads[0].targets] : [...payloads[0].enabledPlatforms]
  const perJob = distributeTargets(payloads.length, baseTargets, {
    distribute: settings.youtubeDistribute,
    perChannel: settings.youtubePerChannel
  })
  const sameSet = (a: TargetId[]): boolean => a.length === baseTargets.length && a.every((t) => baseTargets.includes(t))
  const jobs: VideoJob[] = []
  payloads.forEach((payload, index) => {
    // своё отличающееся множество направлений у ролика уважаем, одинаковое у всех — раздаём по настройкам
    const explicit = payload.targets && payload.targets.length > 0 ? payload.targets : null
    const own = explicit && !sameSet(explicit) ? explicit : perJob[index]
    if (!own || own.length === 0) return
    jobs.push(buildJob(payload, own))
  })
  const persisted = getPersisted()
  patchPersisted({ jobs: [...persisted.jobs, ...jobs] })
  emit()
  return jobs
}

export function removeJob(id: string): void {
  const persisted = getPersisted()
  if (persisted.jobs.find((job) => job.id === id)?.status === 'uploading') return
  patchPersisted({ jobs: persisted.jobs.filter((job) => job.id !== id) })
  emit()
}

function updateJob(id: string, patch: Partial<VideoJob>): VideoJob | undefined {
  const persisted = getPersisted()
  const jobs = persisted.jobs.map((job) => (job.id === id ? { ...job, ...patch } : job))
  patchPersisted({ jobs })
  emit()
  return jobs.find((job) => job.id === id)
}

function pushHistory(entry: Omit<HistoryEntry, 'id' | 'at'>): void {
  const persisted = getPersisted()
  const full: HistoryEntry = { ...entry, id: randomUUID(), at: new Date().toISOString() }
  patchPersisted({ history: [full, ...persisted.history].slice(0, 300) })
  emit()
}

function finalizeJob(jobId: string): void {
  const finished = getPersisted().jobs.find((item) => item.id === jobId)
  const results = Object.values(finished?.results ?? {}).filter((r): r is PlatformResult => !!r)
  const hasIncomplete = results.some((r) => r.status === 'pending' || r.status === 'uploading')
  const hasError = results.some((r) => r.status === 'error')
  const hasDone = results.some((r) => r.status === 'done')
  updateJob(jobId, {
    status: hasIncomplete ? 'queued' : hasError && hasDone ? 'partial' : hasError ? 'error' : 'done'
  })
}

function recoverInterruptedJobs(): void {
  const jobs = getPersisted().jobs.map((job) => {
    const interruptedResult = job.targets.some((id) => job.results[id]?.status === 'uploading')
    if (
      !interruptedResult &&
      job.status !== 'uploading' &&
      job.status !== 'waiting' &&
      job.status !== 'paused'
    ) {
      return job
    }
    const results = { ...job.results }
    for (const id of job.targets) {
      if (results[id]?.status === 'uploading') {
        results[id] = { status: 'pending' }
      }
    }
    const statuses = job.targets.map((id) => results[id]?.status ?? 'pending')
    const hasPending = statuses.some((s) => s === 'pending' || s === 'uploading')
    const hasDone = statuses.some((s) => s === 'done')
    const hasError = statuses.some((s) => s === 'error')
    const status: VideoJob['status'] = !hasPending
      ? hasError && hasDone
        ? 'partial'
        : hasError
          ? 'error'
          : 'done'
      : 'queued'
    return { ...job, status, results }
  })
  patchPersisted({ jobs })
  emit()
}

async function waitMs(ms: number): Promise<void> {
  const end = Date.now() + ms
  while (Date.now() < end) {
    if (stopped) throw new Error('Очередь остановлена')
    while (paused && !stopped) {
      setRunner('paused')
      await sleep(250)
    }
    if (runner !== 'running' && !paused) setRunner('running')
    await sleep(200)
  }
}

async function waitUntil(iso?: string, waitingJobId?: string): Promise<boolean> {
  if (!iso) return true
  const target = new Date(iso).getTime()
  if (Number.isNaN(target) || target <= Date.now()) return true
  setRunner('waiting')
  progress({ message: `Отложенная публикация: ждём ${new Date(iso).toLocaleString('ru-RU')}`, level: 'info' })
  while (Date.now() < target) {
    if (stopped) throw new Error('Очередь остановлена')
    while (paused && !stopped) {
      setRunner('paused')
      await sleep(250)
    }
    const jobs = getPersisted().jobs
    if (waitingJobId && !jobs.some((item) => item.id === waitingJobId)) {
      setRunner('running')
      return false
    }
    const anotherReady = jobs.some((item) => {
      if (item.id === waitingJobId || (item.status !== 'queued' && item.status !== 'waiting')) return false
      if (!item.publishAt) return true
      const otherTarget = new Date(item.publishAt).getTime()
      return Number.isNaN(otherTarget) || otherTarget <= Date.now()
    })
    if (anotherReady) {
      setRunner('running')
      return false
    }
    await sleep(1000)
  }
  setRunner('running')
  return true
}

function markTarget(jobId: string, target: TargetId, patch: PlatformResult): void {
  const current = getPersisted().jobs.find((j) => j.id === jobId)
  updateJob(jobId, {
    results: { ...current?.results, [target]: patch }
  })
}

/** Открывает браузер аккаунта. Заливка — обычный Chrome этого профиля, окно не больше экрана. */
async function openTargetBrowser(target: TargetId, jobId: string): Promise<{ page: Page; context: BrowserContext }> {
  const parsed = parseTargetId(target)
  if (parsed?.channelNumber) {
    const { platform, channelNumber: number } = parsed
    const mode = uploadLaunchMode()
    let warned = false
    while (getOpenAccountProfile(platform, number)?.mode === 'login' && mode !== 'login') {
      if (stopped) throw new Error('Очередь остановлена')
      if (!warned) {
        warned = true
        progress({
          jobId,
          platform,
          target,
          message: `${label(target)}: профиль открыт для входа — закройте его окно, заливка ждёт`,
          level: 'warn'
        })
      }
      await sleep(2000)
    }
    const { context, page } = await openAccountProfile(platform, number, mode, {
      url: getPlatform(platform).uploadUrl,
      onLog: (line) => progress({ jobId, platform, target, message: `${label(target)}: ${line}`, level: 'info' })
    })
    return { context, page }
  }
  const platform = parsed?.platform ?? 'youtube'
  const { context, page } = await openPlatformBrowser(platform)
  return { context, page }
}

async function closeTargetBrowser(target: TargetId): Promise<void> {
  const parsed = parseTargetId(target)
  if (parsed?.channelNumber) {
    await closeAccountProfile(parsed.platform, parsed.channelNumber)
    return
  }
  await closePlatformBrowser(parsed?.platform ?? 'youtube')
}

function reelWords(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/ё/g, 'е')
      .split(/[^a-zа-я0-9]+/i)
      .filter((word) => word.length >= 4)
  )
}

/** Пакет Kie от другого ролика не должен подменять заголовок и описание текущего. */
function overrideMatchesReel(overrideText: string, job: VideoJob): boolean {
  const foreign = reelWords(overrideText)
  if (foreign.size === 0) return true
  const reel = reelWords(`${job.title} ${job.description}`)
  if (reel.size === 0) return true
  for (const word of foreign) if (reel.has(word)) return true
  return false
}

/** Описание площадки берём только если в нём есть слова заголовка этого рилса. */
function descriptionMatchesTitle(description: string, title: string): boolean {
  const titleWords = reelWords(title)
  if (titleWords.size === 0) return false
  const words = reelWords(description)
  let hits = 0
  let longHit = false
  for (const word of titleWords) {
    if (!words.has(word)) continue
    hits += 1
    if (word.length >= 5) longHit = true
  }
  if (titleWords.size === 1) return hits === 1
  return longHit || hits >= 2
}

async function uploadOnTarget(job: VideoJob, target: TargetId): Promise<void> {
  const platform = platformOf(target)
  const adapter = adapters[platform]
  const override = job.overrides[platform] ?? {}
  const allOptions = mergePublishOptions(job.publishOptions)
  const tiktokOpts = allOptions.tiktok as TiktokPublishOptions
  const dzenOpts = allOptions.dzen as DzenPublishOptions
  const overrideText = `${override.title || ''} ${override.description || ''} ${override.hashtags || ''}`
  const trustOverride = !overrideText.trim() || overrideMatchesReel(overrideText, job)
  const titleAnchor = (job.title || job.description.split('\n')[0] || '').trim()
  const descOk = Boolean((override.description || '').trim()) && descriptionMatchesTitle(override.description || '', titleAnchor)
  if (!trustOverride || ((override.description || '').trim() && !descOk)) {
    uploadLog(platform, 'text', 'описание от другого ролика — беру текст этого рилса')
  }
  const payload = {
    videoPath: job.videoPath,
    title: hasVideoTitle(platform) ? job.title || (trustOverride ? override.title || '' : '') : '',
    description: (descOk ? override.description : '') || job.description || (platform === 'tiktok' ? tiktokOpts.description : '') || '',
    hashtags: usesHashtags(platform)
      ? (trustOverride ? override.hashtags : '') || job.hashtags || tiktokOpts.hashtags || dzenOpts.tags || ''
      : undefined,
    coverPath: override.coverPath || job.coverPath,
    options: allOptions[platform]
  }
  const name = label(target)

  updateJob(job.id, { status: 'uploading' })
  markTarget(job.id, target, { status: 'uploading' })
  uploadLog(platform, 'start', `${name}: ${payload.title || job.title}`)
  progress({
    jobId: job.id,
    platform,
    target,
    message: `Загрузка на ${name}…`,
    level: 'info'
  })

  if (stressUploads) {
    try {
      await sleep(60 + Math.floor(Math.random() * 80))
      if (stopped) throw new Error('Очередь остановлена')
      const fail = platform === 'tiktok' || platform === 'instagram'
      if (fail) throw new Error(`stress fail ${platform}`)
      markTarget(job.id, target, { status: 'done', url: `stress://${target}` })
      uploadLog(platform, 'done', `stress://${target}`)
      pushHistory({
        jobId: job.id,
        jobTitle: job.title,
        platform,
        target,
        status: 'done',
        message: 'Опубликовано',
        url: `stress://${target}`
      })
      return
    } catch (error) {
      if (isStopError(error)) {
        markTarget(job.id, target, { status: 'pending' })
        throw error
      }
      const message = error instanceof Error ? error.message : String(error)
      uploadLogError(platform, 'failed', error)
      markTarget(job.id, target, { status: 'error', error: message })
      pushHistory({ jobId: job.id, jobTitle: job.title, platform, target, status: 'error', message })
      return
    }
  }

  if (!existsSync(job.videoPath)) {
    const message = 'Файл ролика не найден на диске'
    uploadLogError(platform, 'failed', message)
    markTarget(job.id, target, { status: 'error', error: message })
    pushHistory({ jobId: job.id, jobTitle: job.title, platform, target, status: 'error', message })
    progress({ jobId: job.id, platform, target, message: `${name}: ${message}`, level: 'error' })
    return
  }

  try {
    await withRetry(async () => {
      if (stopped) throw new Error('Очередь остановлена')
      const { page } = await openTargetBrowser(target, job.id)
      try {
        if (stopped) throw new Error('Очередь остановлена')
        await waitIfChallenge(page, (message) => progress({ jobId: job.id, platform, target, message, level: 'warn' }))
        let loggedIn = false
        try {
          loggedIn = await adapter.loginCheck(page)
        } catch {
          loggedIn = false
        }
        if (!loggedIn) {
          throw new Error(`Нет сессии ${name}. Войдите на экране «Аккаунты».`)
        }
        if (stopped) throw new Error('Очередь остановлена')
        await waitIfChallenge(page, (message) => progress({ jobId: job.id, platform, target, message, level: 'warn' }))
        if (await hasChallenge(page)) {
          throw new Error('Капча не пройдена. Подтвердите в Chrome и нажмите «Повторить».')
        }
        const rawUrl = await uploadWithTimeout(target, () => adapter.upload(page, payload))
        const url = page.isClosed() ? undefined : await captureReelLink(page, platform, rawUrl).catch(() => undefined)
        uploadLog(platform, 'done', `${name}: ${url || rawUrl}`)
        markTarget(job.id, target, { status: 'done', url })
        pushHistory({
          jobId: job.id,
          jobTitle: job.title,
          platform,
          target,
          status: 'done',
          message: 'Опубликовано',
          url
        })
        progress({
          jobId: job.id,
          platform,
          target,
          message: url ? `${name}: готово — ${url}` : `${name}: готово`,
          level: 'success'
        })
      } catch (error) {
        if (stopped) throw new Error('Очередь остановлена')
        throw error
      } finally {
        await closeTargetBrowser(target)
      }
    }, 2, 800, (error) => !isPlatformTimeoutError(error))
  } catch (error) {
    if (isStopError(error)) {
      markTarget(job.id, target, { status: 'pending' })
      throw error
    }
    const message = error instanceof Error ? error.message : String(error)
    uploadLogError(platform, 'failed', error)
    markTarget(job.id, target, { status: 'error', error: message })
    pushHistory({
      jobId: job.id,
      jobTitle: job.title,
      platform,
      target,
      status: 'error',
      message
    })
    const hint = recentUploadLogHint(platform, 3)
    progress({
      jobId: job.id,
      platform,
      target,
      message: `${name}: ${message}. Идём дальше, повторить можно позже.${hint ? ` Журнал: ${hint}` : ''}`,
      level: 'error'
    })
    await closeTargetBrowser(target).catch(() => undefined)
  }
}

function pendingTargets(job: VideoJob): TargetId[] {
  return job.targets.filter((id) => {
    const status = job.results[id]?.status
    return !status || status === 'pending'
  })
}

function nextRunnableJob(jobs: VideoJob[]): VideoJob | undefined {
  const candidates = jobs.filter((item) => item.status === 'queued' || item.status === 'waiting')
  const now = Date.now()
  const ready = candidates.find((item) => {
    if (!item.publishAt) return true
    const target = new Date(item.publishAt).getTime()
    return Number.isNaN(target) || target <= now
  })
  if (ready) return ready
  return candidates
    .filter((item) => item.publishAt && !Number.isNaN(new Date(item.publishAt).getTime()))
    .sort((a, b) => new Date(a.publishAt!).getTime() - new Date(b.publishAt!).getTime())[0]
}

function markUnexpectedTargetError(job: VideoJob, target: TargetId, error: unknown): void {
  const current = getPersisted().jobs.find((item) => item.id === job.id)
  if (current?.results[target]?.status === 'error') return
  const platform = platformOf(target)
  const message = error instanceof Error ? error.message : String(error)
  uploadLogError(platform, 'unexpected-failed', error)
  markTarget(job.id, target, { status: 'error', error: message })
  pushHistory({
    jobId: job.id,
    jobTitle: job.title,
    platform,
    target,
    status: 'error',
    message
  })
}

function isPlatformTimeoutError(error: unknown): boolean {
  return error instanceof Error && error.message.startsWith('Превышено время загрузки на ')
}

async function uploadWithTimeout<T>(target: TargetId, task: () => Promise<T>): Promise<T> {
  let timeout: NodeJS.Timeout | undefined
  const operation = task()
  const guard = new Promise<never>((_, reject) => {
    timeout = setTimeout(() => {
      void closeTargetBrowser(target)
      reject(
        new Error(
          `Превышено время загрузки на ${label(target)}. Направление пропущено, очередь продолжает работу.`
        )
      )
    }, PLATFORM_UPLOAD_TIMEOUT_MS)
  })
  try {
    return await Promise.race([operation, guard])
  } finally {
    if (timeout) clearTimeout(timeout)
    void operation.catch(() => undefined)
  }
}

async function runLoop(): Promise<void> {
  if (running) return
  running = true
  stopped = false
  paused = false
  recoverInterruptedJobs()
  setRunner('running')
  try {
    while (!stopped) {
      const job = nextRunnableJob(getPersisted().jobs)
      if (!job) break

      if (job.publishAt && new Date(job.publishAt).getTime() > Date.now()) {
        updateJob(job.id, { status: 'waiting' })
        const due = await waitUntil(job.publishAt, job.id)
        if (!due) continue
      }

      const current = getPersisted().jobs.find((item) => item.id === job.id)
      if (!current || stopped) break
      updateJob(job.id, { status: 'uploading' })

      const targets = pendingTargets(current)
      if (targets.length === 0) {
        finalizeJob(job.id)
        continue
      }

      for (let i = 0; i < targets.length; i++) {
        if (stopped) throw new Error('Очередь остановлена')
        while (paused && !stopped) {
          setRunner('paused')
          await sleep(250)
        }
        setRunner('running')
        const latest = getPersisted().jobs.find((item) => item.id === current.id) ?? current
        try {
          await uploadOnTarget(latest, targets[i])
        } catch (error) {
          if (isStopError(error)) throw error
          markUnexpectedTargetError(latest, targets[i], error)
          progress({
            jobId: current.id,
            platform: platformOf(targets[i]),
            target: targets[i],
            message: error instanceof Error ? error.message : String(error),
            level: 'error'
          })
        }
        if (i < targets.length - 1) {
          const delay = getPersisted().settings.delayBetweenPlatformsMs
          progress({
            jobId: current.id,
            message: `Пауза ${Math.round(delay / 1000)} с перед следующим направлением`,
            level: 'info'
          })
          await waitMs(delay)
        }
      }

      finalizeJob(job.id)

      const remaining = getPersisted().jobs.some((item) => item.status === 'queued' || item.status === 'waiting')
      if (remaining) {
        const delay = getPersisted().settings.delayBetweenVideosMs
        progress({ message: `Пауза ${Math.round(delay / 1000)} с перед следующим роликом`, level: 'info' })
        await waitMs(delay)
      }
    }
  } catch (error) {
    if (!isStopError(error)) {
      progress({
        message: error instanceof Error ? error.message : String(error),
        level: 'error'
      })
    }
  } finally {
    recoverInterruptedJobs()
    running = false
    paused = false
    stopped = false
    setRunner('idle')
  }
}

export function retryJob(jobId: string, target?: TargetId): void {
  const persisted = getPersisted()
  const job = persisted.jobs.find((item) => item.id === jobId)
  if (!job) return
  const wanted = target
    ? job.targets.filter((id) => id === target || platformOf(id) === target)
    : job.targets.filter((id) => job.results[id]?.status === 'error')
  if (wanted.length === 0) return
  const results = { ...job.results }
  for (const id of wanted) {
    results[id] = { status: 'pending' }
  }
  updateJob(jobId, {
    status: job.status === 'uploading' ? 'uploading' : 'queued',
    results,
    error: undefined
  })
  if (!running) startQueue()
}

export function startQueue(): void {
  if (running && paused) {
    paused = false
    setRunner('running')
    return
  }
  void runLoop()
}

export function pauseQueue(): void {
  if (!running) return
  paused = true
  setRunner('paused')
}

export function resumeQueue(): void {
  if (!running) {
    startQueue()
    return
  }
  paused = false
  setRunner('running')
}

export function stopQueue(): void {
  if (!running && !paused) return
  stopped = true
  paused = false
  void closeAllBrowsers()
  void closeAllYoutubeProfiles()
  progress({ message: 'Очередь остановлена', level: 'warn' })
}

/** Дождаться, пока очередь закончит текущий прогон (для автоматизации). */
export async function waitQueueIdle(pollMs = 1000): Promise<void> {
  while (running) await sleep(pollMs)
}
