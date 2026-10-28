import { spawnSync, type ChildProcessWithoutNullStreams } from 'child_process'
import { app } from 'electron'
import { mkdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import type {
  GeneratedItem,
  GenerateResult,
  GeneratorInfo,
  GeneratorRun,
  GeneratorSettings,
  LinkTopResult,
  StickerPackInfo
} from '../shared/generator'
import { mergeGeneratorSettings } from '../shared/generator'
import type { KiePack, KiePackResult } from '../shared/kie-pack'
import { PLATFORM_IDS } from '../shared/platforms'
import { planVariantTargets, platformsOfTargets } from '../shared/targets'
import type { NewVideoPayload, PlatformId, PlatformOverride, TargetId, VideoJob } from '../shared/types'
import { runBridge, spawnBridge } from './python'
import { addJobBatch } from './scheduler'
import { getGeneratorSettings, getPersisted, patchPersisted } from './store'

const SCRIPT = 'reels_bridge.py'
const LOG_LIMIT = 400

let run: GeneratorRun = { running: false, task: '', progress: 0, log: [] }
let child: ChildProcessWithoutNullStreams | null = null
const listeners = new Set<(run: GeneratorRun) => void>()
let flushTimer: NodeJS.Timeout | null = null

export function getGeneratorRun(): GeneratorRun {
  return run
}

export function onGeneratorRunChange(cb: (run: GeneratorRun) => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function notify(): void {
  if (flushTimer) return
  flushTimer = setTimeout(() => {
    flushTimer = null
    for (const cb of listeners) cb(run)
  }, 120)
}

function patchRun(patch: Partial<GeneratorRun>): void {
  run = { ...run, ...patch }
  notify()
}

function appendLog(line: string): void {
  const text = line.trimEnd()
  if (!text) return
  const log = run.log.length >= LOG_LIMIT ? run.log.slice(run.log.length - LOG_LIMIT + 1) : run.log.slice()
  log.push(text)
  run = { ...run, log }
  notify()
}

function optsFile(settings: object): string {
  const dir = join(app.getPath('temp'), 'reels-uploader')
  mkdirSync(dir, { recursive: true })
  const file = join(dir, `gen_opts_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.json`)
  writeFileSync(file, JSON.stringify(settings), 'utf-8')
  return file
}

/** Настройки мастера + ключ Kie и служебные поля для Python. */
function withExtras(settings: GeneratorSettings, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { ...settings, kieApiKey: getPersisted().settings.kieApiKey ?? '', ...extra }
}

export function saveGeneratorSettings(patch: Partial<GeneratorSettings>): GeneratorSettings {
  const merged = mergeGeneratorSettings({ ...getGeneratorSettings(), ...patch })
  patchPersisted({ generator: merged })
  return merged
}

function ensureIdle(task: string, keepLog = false): void {
  if (run.running) throw new Error(`Генератор занят: ${run.task || 'идёт операция'}. Дождитесь окончания или остановите.`)
  run = { running: true, task, progress: 0, log: keepLog ? run.log : [], startedAt: new Date().toISOString(), result: run.result }
  notify()
}

function finish(patch: Partial<GeneratorRun>): void {
  patchRun({ running: false, task: '', finishedAt: new Date().toISOString(), ...patch })
}

/** Короткие команды моста (info, превью, стикеры, Kie): лог — в общий журнал генератора. */
async function quick<T>(command: string, settings: GeneratorSettings | null, extra: Record<string, unknown>, task: string, timeoutMs: number): Promise<T> {
  ensureIdle(task)
  try {
    const args = [command]
    if (settings) args.push('--opts', optsFile(withExtras(settings, extra)))
    const data = await runBridge<T>(SCRIPT, args, { timeoutMs, onLog: appendLog })
    finish({ progress: 1 })
    return data
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    finish({ error: message })
    throw error
  }
}

export function generatorInfo(): Promise<GeneratorInfo> {
  return runBridge<GeneratorInfo>(SCRIPT, ['info'], { timeoutMs: 60_000 })
}

export function previewCta(settings: GeneratorSettings): Promise<{ image: string; slogan: string; tgCall: string }> {
  return quick('preview-cta', settings, {}, 'превью CTA', 180_000)
}

export function previewBanner(settings: GeneratorSettings): Promise<{ image: string; pauseAt: number; text: string }> {
  return quick('preview-banner', settings, {}, 'превью баннера', 120_000)
}

export function previewCover(settings: GeneratorSettings): Promise<{ image: string; video: string; phrase: string; disabled?: boolean }> {
  return quick('preview-cover', settings, {}, 'превью обложки', 120_000)
}

export function loadStickers(settings: GeneratorSettings, force = false): Promise<StickerPackInfo> {
  return quick('stickers', settings, { force }, 'стикер-пак', 300_000)
}

export function kieTitles(settings: GeneratorSettings): Promise<{ titles: string[]; source: string }> {
  return quick('kie-titles', settings, {}, 'заголовки Kie', 180_000)
}

export function linkTop(settings: GeneratorSettings): Promise<LinkTopResult> {
  return quick('link-top', settings, {}, 'ролик по ссылке', 15 * 60_000)
}

/** Длинные задачи с прогрессом: генерация и Whisper. Останавливаются через cancelGenerator(). */
function longTask<T>(command: string, settings: GeneratorSettings, extra: Record<string, unknown>, task: string): Promise<T> {
  ensureIdle(task)
  return new Promise<T>((resolve, reject) => {
    let data: T | undefined
    let hasResult = false
    let errorMessage = ''
    let cancelled = false
    try {
      child = spawnBridge(SCRIPT, [command, '--opts', optsFile(withExtras(settings, extra))], {
        onLog: appendLog,
        onMessage: (msg) => {
          if (msg.type === 'progress') patchRun({ progress: Number((msg as { value: number }).value) || 0 })
          else if (msg.type === 'result') {
            data = (msg as { data: T }).data
            hasResult = true
          } else if (msg.type === 'error') errorMessage = String((msg as { message: string }).message)
        }
      })
    } catch (error) {
      finish({ error: error instanceof Error ? error.message : String(error) })
      reject(error)
      return
    }
    const proc = child
    proc.on('error', (error) => {
      child = null
      finish({ error: error.message })
      reject(error)
    })
    proc.on('close', (code) => {
      if (child === proc) child = null
      if (hasResult) {
        finish({ progress: 1 })
        resolve(data as T)
        return
      }
      const message = cancelled ? 'Остановлено' : errorMessage || run.log.slice(-2).join(' | ') || `Python завершился с кодом ${code}`
      finish({ error: message })
      reject(new Error(message))
    })
    ;(proc as ChildProcessWithoutNullStreams & { markCancelled?: () => void }).markCancelled = () => {
      cancelled = true
    }
  })
}

export async function generate(settings: GeneratorSettings, files?: string[], extra: Record<string, unknown> = {}): Promise<GenerateResult> {
  const payload = files?.length ? { files, ...extra } : extra
  const result = await longTask<GenerateResult>('generate', settings, payload, files?.length ? 'подготовка роликов' : 'генерация')
  patchRun({ result: result.items })
  return result
}

interface PackResponse {
  packs: Record<string, KiePack>
  sources: Record<string, 'kie' | 'local'>
}

interface PackBase {
  uid?: string
  title: string
  description: string
  hashtags: string
  platforms?: PlatformId[]
}

async function runPack(bases: PackBase[], platforms: PlatformId[], extra: { transcript?: string; tgLink?: string; theme?: string }): Promise<PackResponse> {
  const list = platforms.length ? platforms : [...PLATFORM_IDS]
  const file = optsFile({
    items: bases.map((b, i) => ({
      uid: b.uid || `item_${i + 1}`,
      title: b.title,
      description: b.description,
      hashtags: b.hashtags,
      platforms: b.platforms
    })),
    platforms: list,
    transcript: extra.transcript ?? '',
    tgLink: extra.tgLink ?? '',
    theme: extra.theme ?? '',
    kieApiKey: getPersisted().settings.kieApiKey ?? ''
  })
  return runBridge<PackResponse>('kie_bridge.py', ['pack', '--opts', file], { timeoutMs: 150_000 * Math.max(1, bases.length), onLog: appendLog })
}

function samePath(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase() && a.trim() !== ''
}

/** Текст Whisper только если он снят с текущего ролика. Иначе Kie пишет про прошлый рилс. */
function boundTranscript(settings: GeneratorSettings, items: GeneratedItem[]): string {
  const text = settings.transcript.trim()
  const video = settings.transcriptVideo.trim()
  if (!text || !video) return ''
  const tops = [settings.linkedPath, settings.topFile, ...items.map((item) => item.source)]
  if (tops.some((path) => samePath(path, video))) return text
  return ''
}

/** Тексты под площадки для готовых роликов генератора. Платформы — только те, куда реально уйдёт ролик. */
export async function packItems(
  items: GeneratedItem[],
  settings: GeneratorSettings,
  platforms: PlatformId[],
  keepLog = false,
  spoken?: string,
  perItemPlatforms?: PlatformId[][]
): Promise<GeneratedItem[]> {
  if (!items.length) return items
  ensureIdle('тексты Kie под площадки', keepLog)
  try {
    const bases = items.map((it, i) => ({
      uid: it.uid || `item_${i + 1}`,
      title: it.title,
      description: it.description,
      hashtags: it.hashtags,
      platforms: perItemPlatforms?.[i]?.length ? perItemPlatforms[i] : platforms
    }))
    const transcript = spoken !== undefined ? spoken : boundTranscript(settings, items)
    if (!transcript && settings.transcript.trim()) {
      appendLog('Текст распознавания от другого ролика — Kie опирается на заголовок этого рилса')
    }
    const res = await runPack(bases, platforms, {
      transcript,
      tgLink: settings.qr,
      theme: settings.topMode === 'link' ? settings.titleTheme : ''
    })
    const packed = items.map((it, i) => {
      const uid = it.uid || `item_${i + 1}`
      const pack = res.packs[uid]
      return pack ? { ...it, pack, packSource: res.sources[uid] ?? 'kie' } : it
    })
    finish({ progress: 1, result: packed })
    return packed
  } catch (error) {
    finish({ error: error instanceof Error ? error.message : String(error) })
    throw error
  }
}

/** Один ролик из «Нового ролика»: тексты под площадки по введённым полям. */
export async function packOne(base: PackBase & { transcript?: string; tgLink?: string }, platforms: PlatformId[]): Promise<KiePackResult> {
  ensureIdle('тексты Kie под площадки')
  try {
    const res = await runPack([{ ...base, uid: 'one' }], platforms, { transcript: base.transcript, tgLink: base.tgLink })
    finish({ progress: 1 })
    return { pack: res.packs.one ?? {}, source: res.sources.one ?? 'local' }
  } catch (error) {
    finish({ error: error instanceof Error ? error.message : String(error) })
    throw error
  }
}

function overridesFromPack(pack: KiePack | undefined, platforms: PlatformId[]): Partial<Record<PlatformId, PlatformOverride>> {
  const out: Partial<Record<PlatformId, PlatformOverride>> = {}
  if (!pack) return out
  for (const p of platforms) {
    const v = pack[p]
    if (!v) continue
    const entry: PlatformOverride = {}
    if (v.title) entry.title = v.title
    if (v.description) entry.description = v.description
    if (v.hashtags) entry.hashtags = v.hashtags
    if (Object.keys(entry).length) out[p] = entry
  }
  return out
}

/** Готовые ролики → задания. У каждого ролика свой набор направлений, без повтора на одной площадке. */
export function itemsToJobs(items: GeneratedItem[], targets: TargetId[], assignment?: TargetId[][]): VideoJob[] {
  const ready = items.filter((item) => item.video)
  const plan = assignment?.length ? assignment : planVariantTargets(targets, 1)
  const payloads: NewVideoPayload[] = ready.map((item, index) => {
    const row = plan[index % Math.max(1, plan.length)] ?? targets
    const enabledPlatforms = platformsOfTargets(row)
    return {
      videoPath: item.video,
      title: item.title || '',
      description: item.description || '',
      hashtags: item.hashtags || '',
      coverPath: item.cover || undefined,
      enabledPlatforms,
      targets: row,
      overrides: overridesFromPack(item.pack, enabledPlatforms)
    }
  })
  return payloads.length ? addJobBatch(payloads) : []
}

export async function generateToQueue(
  settings: GeneratorSettings,
  targets: TargetId[],
  files?: string[],
  options?: { extra?: Record<string, unknown>; oneReel?: boolean }
): Promise<{ result: GenerateResult; jobs: VideoJob[] }> {
  if (!targets.length) throw new Error('Не выбрано ни одного направления — отметьте каналы в «Аккаунтах» или на последнем шаге')
  const plan = planVariantTargets(targets, 1)
  const oneReel = !!options?.oneReel
  const genCount = oneReel ? 1 : Math.max(1, plan.length)
  const result = await generate({ ...settings, count: genCount }, files, options?.extra)
  appendLog(`Собрано ${result.items.length} роликов по отмеченным аккаунтам`)
  let items = result.items
  const assignment = oneReel ? items.map(() => targets) : items.map((_, index) => plan[index % Math.max(1, plan.length)] ?? targets)
  if (settings.kiePack && items.length) {
    const spoken = (result.transcript || '').trim()
    if (spoken) saveGeneratorSettings({ transcript: spoken, transcriptVideo: result.transcriptVideo || '' })
    try {
      items = await packItems(
        items,
        settings,
        platformsOfTargets(targets),
        true,
        spoken,
        assignment.map((row) => platformsOfTargets(row))
      )
      result.items = items
    } catch (error) {
      appendLog(`Kie-пакет пропущен: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
  const jobs = itemsToJobs(items, targets, assignment)
  appendLog(`В очередь добавлено заданий: ${jobs.length}`)
  return { result, jobs }
}

export function transcribe(settings: GeneratorSettings, force = false, video?: string): Promise<{ text: string; phrases: string[]; video: string }> {
  return longTask('transcribe', settings, { force, video: video ?? '' }, 'распознавание речи')
}

/** Остановить текущую операцию: убить Python вместе с ffmpeg/whisper. */
export function cancelGenerator(): void {
  const proc = child
  if (!proc || proc.killed) return
  ;(proc as ChildProcessWithoutNullStreams & { markCancelled?: () => void }).markCancelled?.()
  appendLog('Останавливаю…')
  if (process.platform === 'win32' && proc.pid) {
    spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true })
  } else if (proc.pid) {
    spawnSync('pkill', ['-P', String(proc.pid)])
    try {
      proc.kill('SIGKILL')
    } catch {
      /* процесс уже завершился */
    }
  }
}

export function isGeneratorBusy(): boolean {
  return run.running
}
