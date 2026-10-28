import { basename, extname, join } from 'path'
import { TG_EXTRA_UPLOADERS, telegramArmed, type TelegramTrigger } from '../shared/generator'
import { getPlatform } from '../shared/platforms'
import { enabledTargets, parseTargetId, targetLabel } from '../shared/targets'
import type { TargetId, TelegramStatus, VideoJob, YoutubeProfileInfo } from '../shared/types'
import { getAutomationStatus, runIncomingPair, stopAutomation, type IncomingMedia } from './automation'
import { generatorInfo, saveGeneratorSettings } from './generator'
import { getRunner, isQueueRunning } from './scheduler'
import { getGeneratorSettings, getPersisted } from './store'
import { downloadTelegramFile, TelegramApiError, telegramCall } from './tg-fetch'
import { getPlatformProfiles } from './yt-plain'

/**
 * Загрузка из Telegram работает, когда в «Источнике» выбран этот пункт.
 * Верх: ссылка или видео. Если низ тоже из Telegram — следом ссылка, видео или кружок.
 * Склейка и заливка идут по уже сохранённым настройкам программы.
 */

const QUEUE_CAP = 20
const MAX_TG_FILE = 20 * 1024 * 1024
const YT = '(?:youtube\\.com/(?:watch\\?(?:[^#\\s]*&)?v=|shorts/|embed/|live/)|youtu\\.be/)([A-Za-z0-9_-]{6,})'
const IG = 'instagram\\.com/(?:reels?|p|tv)/([A-Za-z0-9_-]+)'

interface TgEntity {
  type: string
  offset: number
  length: number
  url?: string
}

interface TgFile {
  file_id: string
  file_size?: number
  file_name?: string
  mime_type?: string
}

interface TgMessage {
  text?: string
  caption?: string
  chat: { id: number; type: string }
  from?: { id?: number; is_bot?: boolean }
  entities?: TgEntity[]
  caption_entities?: TgEntity[]
  video?: TgFile
  video_note?: TgFile
  animation?: TgFile
  document?: TgFile
}

interface TgUpdate {
  update_id: number
  message?: TgMessage
}

interface Job {
  chatId: number
  top: IncomingMedia | null
  bottom: IncomingMedia | null
  key: string
}

const listeners = new Set<() => void>()
const queue: Job[] = []
const waitingTop = new Map<number, IncomingMedia>()
/** Верхний файл ещё без текста или текст ещё без файла. */
const draftTop = new Map<number, { media: IncomingMedia | null; note: string }>()
const MIN_NOTE = 12
let foldersAt = 0
let folder1 = ''
let folder2 = ''
let listening = false
let username = ''
let lastError = ''
let lastText = ''
let lastFinishedUrl = ''
let activeUrl = ''
let epoch = 0
let ticket = 0
let draining = false
let stopCtrl = new AbortController()
let loop: Promise<void> | null = null

export function onTelegramChange(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function notify(): void {
  for (const cb of listeners) cb()
}

export function getTelegramStatus(): TelegramStatus {
  const tg = getGeneratorSettings().tg
  return {
    enabled: tg.enabled,
    listening,
    username,
    chatId: tg.chatId,
    queued: queue.length,
    lastError,
    lastText,
    lastUrl: activeUrl || lastFinishedUrl
  }
}

export function cancelTelegramWork(): void {
  epoch += 1
  queue.length = 0
  waitingTop.clear()
  draftTop.clear()
  activeUrl = ''
  notify()
}

export function startTelegram(): void {
  applyTelegramSettings()
}

export function applyTelegramSettings(): void {
  const id = ++ticket
  stopCtrl.abort()
  const previous = loop
  loop = (async () => {
    await previous?.catch(() => undefined)
    if (id !== ticket) return
    stopCtrl = new AbortController()
    await poll(id)
  })()
}

export async function shutdownTelegram(): Promise<void> {
  ticket += 1
  cancelTelegramWork()
  stopCtrl.abort()
  await loop?.catch(() => undefined)
}

async function poll(id: number): Promise<void> {
  while (id === ticket && !stopCtrl.signal.aborted) {
    const settings = getGeneratorSettings()
    const token = settings.tg.token.trim()
    if (!settings.tg.enabled || !token || !telegramArmed(settings)) {
      listening = false
      notify()
      return
    }
    try {
      await telegramCall(token, 'deleteWebhook', { drop_pending_updates: false }, { signal: stopCtrl.signal, timeoutMs: 30_000 })
      const me = (await telegramCall(token, 'getMe', {}, { signal: stopCtrl.signal, timeoutMs: 30_000 })) as { username?: string }
      username = me.username || ''
      await prime(token)
      listening = true
      lastError = ''
      notify()
    } catch (error) {
      if (id !== ticket || stopCtrl.signal.aborted) return
      lastError = explain(error) || 'не удалось подключиться к Telegram'
      listening = false
      notify()
      await sleep(8_000)
      continue
    }

    while (id === ticket && !stopCtrl.signal.aborted) {
      const current = getGeneratorSettings()
      if (!current.tg.enabled || current.tg.token.trim() !== token || !telegramArmed(current)) return
      try {
        const updates = (await telegramCall(
          token,
          'getUpdates',
          {
            offset: current.tg.offset > 0 ? current.tg.offset : undefined,
            timeout: 25,
            allowed_updates: ['message']
          },
          { signal: stopCtrl.signal, timeoutMs: 50_000 }
        )) as TgUpdate[]
        if (lastError) {
          lastError = ''
          listening = true
          notify()
        }
        for (const update of updates) {
          if (id !== ticket || stopCtrl.signal.aborted) return
          rememberOffset(update.update_id + 1)
          await handle(update)
        }
      } catch (error) {
        if (id !== ticket || stopCtrl.signal.aborted) return
        const text = explain(error)
        if (!text) return
        lastError = text
        listening = false
        notify()
        const wait = error instanceof TelegramApiError && error.retryAfter ? error.retryAfter * 1000 : 5_000
        await sleep(wait)
        break
      }
    }
  }
}

async function prime(token: string): Promise<void> {
  if (getGeneratorSettings().tg.primed) return
  const updates = (await telegramCall(
    token,
    'getUpdates',
    { offset: -1, limit: 1, timeout: 0, allowed_updates: ['message'] },
    { signal: stopCtrl.signal, timeoutMs: 30_000 }
  )) as TgUpdate[]
  const offset = updates.length ? updates[updates.length - 1].update_id + 1 : 0
  patchTg({ primed: true, offset })
}

async function handle(update: TgUpdate): Promise<void> {
  const msg = update.message
  if (!msg || msg.chat.type !== 'private' || msg.from?.is_bot) return
  const chatId = msg.chat.id
  const text = msg.text || msg.caption || ''
  const cmd = commandOf(text)
  let intro = ''
  const extra = isExtraUploader(chatId, msg.from?.id)
  const bound = getGeneratorSettings().tg.chatId
  if (!extra && !bound) {
    patchTg({ chatId })
    intro = 'Этот чат закреплён за ботом.'
    notify()
  } else if (!extra && bound !== chatId) {
    await reply(chatId, 'Этот бот закреплён за другим чатом.')
    return
  }

  if (!telegramArmed(getGeneratorSettings())) {
    await reply(chatId, 'Загрузка через Telegram выключена. В разделе «Источник» выберите её у верхнего ролика.')
    return
  }

  if (cmd === 'status') {
    await reply(chatId, joinIntro(intro, statusText()))
    return
  }
  if (cmd === 'cancel') {
    waitingTop.delete(chatId)
    draftTop.delete(chatId)
    await reply(chatId, joinIntro(intro, 'Сбросил ожидание. Можно прислать ролик заново.'))
    return
  }
  if (cmd === 'stop') {
    await reply(chatId, 'Останавливаю сборку.')
    stopAutomation()
    return
  }
  if (cmd === 'start' || cmd === 'help') {
    await reply(chatId, joinIntro(intro, helpText()))
    return
  }

  const bottomFromBot = getGeneratorSettings().sourceMode === 'telegram'
  const url = videoUrlsFromText(messageBlob(msg))[0] || ''
  const note = noteFromMessage(msg)
  const hasFile = Boolean(pickVideoFile(msg))

  if (bottomFromBot && waitingTop.has(chatId)) {
    if (!hasFile && !url) {
      await reply(chatId, joinIntro(intro, 'Жду нижний ролик: ссылку, видео или кружок. /cancel — начать заново.'))
      return
    }
    let bottom: IncomingMedia | null
    try {
      bottom = await mediaFromMessage(msg, 'tg-bottom')
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error)
      await reply(chatId, /too big/i.test(reason) ? 'Telegram отдаёт боту файлы только до 20 МБ. Сожмите видео или пришлите ссылку.' : reason)
      return
    }
    const top = waitingTop.get(chatId)
    if (!bottom || !top) return
    waitingTop.delete(chatId)
    await enqueue(chatId, top, bottom, intro)
    return
  }

  if (!hasFile && !url && note) {
    const draft = draftTop.get(chatId) ?? { media: null, note: '' }
    draft.note = note
    if (draft.media?.kind === 'file') {
      draftTop.delete(chatId)
      await acceptTop(chatId, { ...draft.media, note }, bottomFromBot, intro)
      return
    }
    draftTop.set(chatId, draft)
    notify()
    await reply(chatId, joinIntro(intro, 'Описание принял. Теперь пришлите само видео. Ссылку можно без описания.'))
    return
  }

  if (!hasFile && !url) {
    const held = waitingTop.get(chatId)
    const draft = draftTop.get(chatId)
    const ask = draft?.media
      ? 'Видео уже есть. Напишите, о чём ролик — по этому тексту Kie сделает название и описание.'
      : draft?.note
        ? 'Описание уже есть. Пришлите само видео или ссылку.'
        : held
          ? 'Жду нижний ролик: ссылку, видео или кружок. /cancel — начать заново.'
          : helpText()
    await reply(chatId, joinIntro(intro, ask))
    return
  }

  let media: IncomingMedia | null
  try {
    media = await mediaFromMessage(msg, 'tg-top')
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    await reply(chatId, /too big/i.test(reason) ? 'Telegram отдаёт боту файлы только до 20 МБ. Сожмите видео или пришлите ссылку.' : reason)
    return
  }
  if (!media) {
    await reply(chatId, joinIntro(intro, helpText()))
    return
  }

  if (media.kind === 'url') {
    const saved = note || draftTop.get(chatId)?.note || ''
    draftTop.delete(chatId)
    await acceptTop(chatId, { ...media, note: saved }, bottomFromBot, intro)
    return
  }

  const saved = note || draftTop.get(chatId)?.note || ''
  if (!saved) {
    draftTop.set(chatId, { media, note: '' })
    notify()
    await reply(
      chatId,
      joinIntro(
        intro,
        'Видео принял. Напишите одним сообщением, о чём ролик. Можно было прислать этот текст подписью к видео или отдельным сообщением до него. По нему Kie сделает название и описание.'
      )
    )
    return
  }
  draftTop.delete(chatId)
  await acceptTop(chatId, { ...media, note: saved }, bottomFromBot, intro)
}

async function acceptTop(chatId: number, top: IncomingMedia, bottomFromBot: boolean, intro: string): Promise<void> {
  if (bottomFromBot) {
    waitingTop.set(chatId, top)
    notify()
    await reply(chatId, joinIntro(intro, 'Верхний ролик принял. Теперь пришлите нижний: ссылку, видео или кружок.'))
    return
  }
  await enqueue(chatId, top, null, intro)
}

async function enqueue(chatId: number, top: IncomingMedia | null, bottom: IncomingMedia | null, intro: string): Promise<void> {
  const key = `${top?.url || top?.path || ''}|${bottom?.url || bottom?.path || ''}`
  if (key === activeUrl || queue.some((job) => job.key === key)) {
    await reply(chatId, joinIntro(intro, 'Этот ролик уже стоит в работе.'))
    return
  }
  if (queue.length >= QUEUE_CAP) {
    await reply(chatId, joinIntro(intro, `Очередь полная (${QUEUE_CAP}). Дождитесь текущих роликов.`))
    return
  }
  queue.push({ chatId, top, bottom, key })
  notify()
  const body = bottom
    ? 'Оба ролика принял. Склеиваю и загружаю по сохранённым настройкам.'
    : 'Верхний ролик принял. Низ берётся из настроек, дальше склейка и заливка.'
  await reply(chatId, joinIntro(intro, body))
  void drain()
}

async function drain(): Promise<void> {
  if (draining) return
  draining = true
  const my = epoch
  let toldBusy = false
  let announcedFor = ''
  try {
    while (queue.length && my === epoch) {
      const job = queue[0]
      activeUrl = job.key
      notify()
      if (announcedFor !== job.key) {
        announcedFor = job.key
        const plan = uploadPlanText()
        await reply(job.chatId, plan)
        if (my !== epoch) return
        if (!destinationLines().length) {
          queue.shift()
          activeUrl = ''
          notify()
          continue
        }
      }
      let res
      try {
        res = await runIncomingPair(job.top, job.bottom)
      } catch (error) {
        if (my !== epoch) return
        queue.shift()
        activeUrl = ''
        lastFinishedUrl = job.key
        notify()
        await reply(job.chatId, `Сборка остановилась: ${error instanceof Error ? error.message : String(error)}`)
        continue
      }
      if (my !== epoch) return
      if (res.cancelled) return
      if (res.busy) {
        if (!toldBusy) {
          toldBusy = true
          await reply(job.chatId, 'Генератор занят. Начну эту ссылку, как освободится.')
        }
        await sleep(5_000)
        continue
      }
      toldBusy = false
      queue.shift()
      activeUrl = ''
      lastFinishedUrl = job.key
      notify()
      if (!res.ok || !res.jobIds.length) {
        await reply(job.chatId, `Сборка остановилась: ${res.message}`)
        continue
      }
      await reportUploads(job.chatId, res.jobIds, my)
    }
  } finally {
    draining = false
    if (my === epoch) activeUrl = ''
    notify()
    if (queue.length) void drain()
  }
}

async function reportUploads(chatId: number, jobIds: string[], epochAt: number): Promise<void> {
  const seen = new Set<string>()
  let idleTicks = 0
  while (epochAt === epoch && !stopCtrl.signal.aborted) {
    const jobs = getPersisted().jobs.filter((item) => jobIds.includes(item.id))
    const profiles = Object.values(getPlatformProfiles()).flat()
    for (const job of jobs) {
      for (const target of job.targets) {
        const key = `${job.id}:${target}`
        if (seen.has(key)) continue
        const result = job.results[target]
        if (result?.status === 'done') {
          seen.add(key)
          await reply(chatId, uploadedText(job, target, profiles, result.url))
        } else if (result?.status === 'error' || result?.status === 'skipped') {
          seen.add(key)
          await reply(chatId, `Не загрузилось: ${describeTarget(target, profiles)}\n${result.error || 'ошибка'}`)
        }
      }
    }
    if (epochAt !== epoch || stopCtrl.signal.aborted) return
    const settled =
      jobs.length === jobIds.length &&
      jobs.every((job) =>
        job.targets.every((target) => {
          const status = job.results[target]?.status
          return status === 'done' || status === 'error' || status === 'skipped'
        })
      )
    if (settled) {
      await reply(chatId, 'Загрузка полностью закончена.')
      return
    }
    if (getRunner() === 'idle' && !isQueueRunning()) {
      idleTicks += 1
      if (idleTicks >= 3) {
        await reply(chatId, 'Загрузка остановлена.')
        return
      }
    } else {
      idleTicks = 0
    }
    await sleep(2_000)
  }
}

function uploadPlanText(): string {
  const lines = destinationLines()
  if (!lines.length) return 'Не отмечено ни одного направления в «Аккаунтах». Загрузка не начнётся.'
  return `Рилс будет загружен на:\n${lines.join('\n')}`
}

function destinationLines(): string[] {
  const profiles = Object.values(getPlatformProfiles()).flat()
  return enabledTargets(getPlatformProfiles(), getPersisted().targets).map((target) => `• ${describeTarget(target.id, profiles)}`)
}

function describeTarget(id: TargetId, profiles: YoutubeProfileInfo[]): string {
  const parsed = parseTargetId(id)
  if (!parsed) return id
  const platform = getPlatform(parsed.platform).shortName
  const label = targetLabel(id, profiles)
  if (!parsed.channelNumber) return `${platform} — основной профиль`
  if (label === `${platform} #${parsed.channelNumber}`) return `${platform} — профиль #${parsed.channelNumber}`
  return `${platform} — ${label}`
}

function uploadedText(job: VideoJob, target: TargetId, profiles: YoutubeProfileInfo[], url?: string): string {
  const title = job.title.trim() || basename(job.videoPath)
  const link = url?.trim()
  return [`Загрузилось видео «${title}»`, describeTarget(target, profiles), link || 'Ссылку площадка не вернула.'].join('\n')
}

function helpText(): string {
  const settings = getGeneratorSettings()
  const lines = ['Программа должна быть открыта.']
  if (settings.sourceMode === 'telegram') {
    lines.unshift(
      'Сначала верхний рилс: ссылку или само видео.',
      'Если это файл, а не ссылка — напишите, о чём ролик: подписью к видео или отдельным сообщением, до или после.',
      'Потом нижний: ссылку, видео или кружок.',
      'Дальше склейка и заливка по настройкам программы.',
      '/cancel — сбросить и начать заново.'
    )
  } else if (settings.topMode === 'telegram') {
    lines.unshift(
      'Пришлите верхний рилс: ссылку YouTube/Instagram или само видео.',
      'Файл без ссылки сопроводите текстом, о чём ролик: подписью или отдельным сообщением. По нему Kie напишет название и описание.',
      'Низ, призыв и площадки берутся из настроек программы.'
    )
  } else {
    lines.unshift('Загрузка через Telegram выключена. Выберите её в разделе «Источник».')
  }
  lines.push('/status — что сейчас делается', '/stop — остановить сборку')
  return lines.join('\n')
}

function statusText(): string {
  const settings = getGeneratorSettings()
  const cycle = getAutomationStatus().cycleRunning || !!activeUrl
  const waiting = waitingTop.size
  const draft = [...draftTop.values()]
  const waitNote = draft.some((item) => item.media && !item.note)
  const waitFile = draft.some((item) => item.note && !item.media)
  const idle = settings.sourceMode === 'telegram' ? 'Жду верхний рилс: ссылку или видео с описанием. Потом попрошу нижний.' : 'Жду верхний рилс: ссылку или видео с описанием.'
  const hold = waitNote ? 'Видео есть, жду текст: о чём ролик.' : waitFile ? 'Описание есть, жду само видео.' : ''
  return [
    cycle ? 'Сейчас склеиваю ролик и ставлю его в заливку.' : hold ? hold : waiting ? `Верх принят, жду нижний ролик. Чатов: ${waiting}.` : idle,
    `В очереди: ${queue.length}.`,
    activeUrl ? `Сейчас: ${activeUrl}` : '',
    lastError ? `Последняя ошибка: ${lastError}` : ''
  ]
    .filter(Boolean)
    .join('\n')
}

async function mediaFromMessage(msg: TgMessage, prefix: string): Promise<IncomingMedia | null> {
  const file = pickVideoFile(msg)
  if (file) {
    if ((file.file_size || 0) > MAX_TG_FILE) {
      throw new Error('Telegram отдаёт боту файлы только до 20 МБ. Сожмите видео или пришлите ссылку.')
    }
    const saved = await saveTelegramVideo(file, prefix)
    return { kind: 'file', url: '', path: saved }
  }
  const url = videoUrlsFromText(messageBlob(msg))[0]
  if (!url) return null
  return { kind: 'url', url, path: '' }
}

function pickVideoFile(msg: TgMessage): TgFile | null {
  if (msg.video_note?.file_id) return msg.video_note
  if (msg.video?.file_id) return msg.video
  if (msg.animation?.file_id && isVideoDocument(msg.animation)) return msg.animation
  if (msg.document?.file_id && isVideoDocument(msg.document)) return msg.document
  return null
}

function isVideoDocument(file: TgFile): boolean {
  const mime = (file.mime_type || '').toLowerCase()
  if (mime.startsWith('video/')) return true
  const name = (file.file_name || '').toLowerCase()
  return ['.mp4', '.mov', '.webm', '.mkv', '.m4v'].some((ext) => name.endsWith(ext))
}

async function saveTelegramVideo(file: TgFile, prefix: string): Promise<string> {
  const token = getGeneratorSettings().tg.token.trim()
  const info = (await telegramCall(token, 'getFile', { file_id: file.file_id }, { signal: stopCtrl.signal, timeoutMs: 30_000 })) as { file_path?: string }
  const remote = info.file_path || ''
  if (!remote) throw new Error('Telegram не отдал файл')
  if (/file is too big/i.test(remote)) throw new Error('Telegram отдаёт боту файлы только до 20 МБ. Сожмите видео или пришлите ссылку.')
  const folder = await videoFolder(prefix === 'tg-bottom' ? 2 : 1)
  const ext = videoExt(file, remote)
  const dest = join(folder, `${prefix}-${Date.now()}${ext}`)
  try {
    await downloadTelegramFile(token, remote, dest, { signal: stopCtrl.signal, timeoutMs: 180_000 })
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    if (/too big/i.test(text)) throw new Error('Telegram отдаёт боту файлы только до 20 МБ. Сожмите видео или пришлите ссылку.')
    throw error
  }
  return dest
}

function videoExt(file: TgFile, remote: string): string {
  const fromRemote = extname(remote.split('?')[0] || '').toLowerCase()
  if (/^\.[a-z0-9]{2,5}$/.test(fromRemote)) return fromRemote
  const fromName = extname(file.file_name || '').toLowerCase()
  if (/^\.[a-z0-9]{2,5}$/.test(fromName)) return fromName
  return '.mp4'
}

async function videoFolder(which: 1 | 2): Promise<string> {
  if (!folder1 || !folder2 || Date.now() - foldersAt > 60_000) {
    const info = await generatorInfo()
    folder1 = info.folder1
    folder2 = info.folder2
    foldersAt = Date.now()
  }
  const folder = which === 2 ? folder2 : folder1
  if (!folder) throw new Error('Папка для ролика не найдена. Проверьте движок в настройках.')
  return folder
}

async function reply(chatId: number, text: string): Promise<void> {
  const token = getGeneratorSettings().tg.token.trim()
  if (!token || stopCtrl.signal.aborted) return
  const clean = text.trim().slice(0, 3500)
  if (!clean) return
  try {
    await telegramCall(token, 'sendMessage', { chat_id: chatId, text: clean }, { signal: stopCtrl.signal, timeoutMs: 30_000 })
    lastText = clean
    notify()
  } catch (error) {
    if (stopCtrl.signal.aborted) return
    const textError = explain(error)
    if (!textError) return
    lastError = textError
    notify()
  }
}

function isExtraUploader(chatId: number, fromId?: number): boolean {
  return TG_EXTRA_UPLOADERS.includes(chatId) || (fromId != null && TG_EXTRA_UPLOADERS.includes(fromId))
}

function joinIntro(intro: string, body: string): string {
  return intro ? `${intro}\n\n${body}` : body
}

function patchTg(patch: Partial<TelegramTrigger>): void {
  const tg = getGeneratorSettings().tg
  saveGeneratorSettings({ tg: { ...tg, ...patch } })
}

function rememberOffset(offset: number): void {
  const tg = getGeneratorSettings().tg
  if (tg.offset === offset) return
  saveGeneratorSettings({ tg: { ...tg, offset } })
}

function commandOf(text: string): string {
  const match = /^\/([a-z0-9_]+)(?:@\w+)?(?:\s|$)/i.exec(text.trim())
  return match ? match[1].toLowerCase() : ''
}

function noteFromMessage(msg: TgMessage): string {
  const raw = (msg.text || msg.caption || '').trim().replace(/^\/[a-z0-9_]+(?:@\w+)?/i, '')
  const plain = raw.replace(new RegExp(`${YT}|${IG}`, 'gi'), ' ').replace(/https?:\/\/\S+/gi, ' ').replace(/\s+/g, ' ').trim()
  return plain.length >= MIN_NOTE ? plain : ''
}

function messageBlob(msg: TgMessage): string {
  return [msg.text || '', msg.caption || '', ...entityBits(msg.text || '', msg.entities), ...entityBits(msg.caption || '', msg.caption_entities)].join('\n')
}

function entityBits(text: string, entities: TgEntity[] | undefined): string[] {
  const out: string[] = []
  for (const ent of entities || []) {
    if (ent.type === 'text_link' && ent.url) out.push(ent.url)
    else if (ent.type === 'url') out.push(text.slice(ent.offset, ent.offset + ent.length))
  }
  return out
}

export function videoUrlsFromText(text: string): string[] {
  const found: string[] = []
  const seen = new Set<string>()
  for (const match of text.matchAll(new RegExp(`${YT}|${IG}`, 'gi'))) {
    const url = match[1] ? `https://www.youtube.com/watch?v=${match[1]}` : match[2] ? `https://www.instagram.com/reel/${match[2]}/` : ''
    if (!url || seen.has(url)) continue
    seen.add(url)
    found.push(url)
  }
  return found
}

function explain(error: unknown): string {
  if (error instanceof TelegramApiError) {
    if (error.code === 401) return 'Токен бота не подошёл. Проверьте его у BotFather.'
    if (error.code === 409) return 'Этого бота уже слушает другая программа. Закройте второй экземпляр.'
    return error.message
  }
  if (error instanceof Error && error.name === 'AbortError') return ''
  return error instanceof Error ? error.message : String(error)
}

function sleep(ms: number): Promise<void> {
  const signal = stopCtrl.signal
  return new Promise((resolve) => {
    const timer = setTimeout(finish, ms)
    function finish(): void {
      clearTimeout(timer)
      signal.removeEventListener('abort', finish)
      resolve()
    }
    if (signal.aborted) finish()
    else signal.addEventListener('abort', finish, { once: true })
  })
}
