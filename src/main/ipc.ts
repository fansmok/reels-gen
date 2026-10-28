import { BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { existsSync, rmSync } from 'fs'
import { mergeContentDefaults, refreshIdleComposer } from '../shared/content-defaults'
import { PLATFORM_IDS, getPlatform } from '../shared/platforms'
import { mergeComposer, mergePublishOptions } from '../shared/publish-options'
import { normalizeProxy } from '../shared/proxy'
import type {
  AccountStatus,
  AppSettings,
  AppState,
  ComposerDraft,
  ContentDefaults,
  EngineCheck,
  EnginePaths,
  NewVideoPayload,
  PlatformId,
  ProgressEvent,
  ProxyConfig,
  TargetId
} from '../shared/types'
import { closeAllBrowsers, closePlatformBrowser, getOpenContext, gotoLogin, isBrowserOpen, openPlatformBrowser, probeChrome, testProxy } from './browser'
import {
  cancelGenerator,
  generate,
  generateToQueue,
  generatorInfo,
  getGeneratorRun,
  itemsToJobs,
  kieTitles,
  linkTop,
  loadStickers,
  onGeneratorRunChange,
  packItems,
  packOne,
  previewBanner,
  previewCover,
  previewCta,
  saveGeneratorSettings,
  transcribe
} from './generator'
import type { GeneratedItem, GeneratorSettings } from '../shared/generator'
import { getAutomationStatus, onAutomationChange, runCycle, setAutomationProgressSink, setAutomationStopHook, startAutomation, stopAutomation } from './automation'
import { applyTelegramSettings, cancelTelegramWork, getTelegramStatus, onTelegramChange } from './telegram'
import { checkEngine, quickEngineCheck, runBridge } from './python'
import { targetId } from '../shared/targets'
import { toReelUrl } from './protocol'
import {
  closeAccountProfile,
  closeYoutubeProfile,
  getPlatformProfiles,
  getYoutubeProfiles,
  getYoutubeProfilesError,
  isYoutubeProfilesLoading,
  onYoutubeProfilesChange,
  openAccountKeys,
  openAccountProfile,
  openYoutubeProfile,
  openYoutubeProfileNumbers,
  refreshYoutubeProfiles
} from './yt-plain'
import {
  addJob,
  addJobBatch,
  getRunner,
  onProgress,
  onStoreChange,
  pauseQueue,
  removeJob,
  resumeQueue,
  retryJob,
  startQueue,
  stopQueue
} from './scheduler'
import { getGeneratorSettings, getPersisted, patchPersisted, sessionPath } from './store'
import { adapters } from './uploaders'
import { readUploadLog } from './uploaders/upload-log'

let chromeAvailable = false
let chromeMessage: string | undefined
let engineStatus: EngineCheck = { ok: false, problems: [] }
const checking = new Set<PlatformId>()

function engineState(): EngineCheck {
  const quick = quickEngineCheck()
  if (!quick.ok) return quick
  const profilesError = getYoutubeProfilesError()
  if (profilesError && engineStatus.ok) return { ...engineStatus, ok: false, problems: [profilesError] }
  return engineStatus
}

function accountsMap(): Record<PlatformId, AccountStatus> {
  const persisted = getPersisted()
  const result = {} as Record<PlatformId, AccountStatus>
  for (const id of PLATFORM_IDS) {
    result[id] = {
      platform: id,
      loggedIn: persisted.platforms[id].loggedIn,
      checking: checking.has(id),
      browserOpen: isBrowserOpen(id)
    }
  }
  return result
}

export function buildState(): AppState {
  const persisted = getPersisted()
  return {
    jobs: persisted.jobs,
    history: persisted.history,
    settings: persisted.settings,
    contentDefaults: mergeContentDefaults(persisted.contentDefaults),
    proxy: persisted.proxy,
    platforms: persisted.platforms,
    accounts: accountsMap(),
    composer: persisted.composer,
    runner: getRunner(),
    chromeAvailable,
    chromeMessage,
    enginePaths: persisted.enginePaths,
    engine: engineState(),
    youtubeProfiles: getYoutubeProfiles(),
    platformProfiles: getPlatformProfiles(),
    youtubeProfilesLoading: isYoutubeProfilesLoading(),
    openYoutubeProfiles: openYoutubeProfileNumbers(),
    openAccountProfiles: openAccountKeys(),
    targets: persisted.targets,
    generator: getGeneratorSettings(),
    generatorRun: getGeneratorRun(),
    automation: getAutomationStatus(),
    telegram: getTelegramStatus()
  }
}

function sendGeneratorRun(): void {
  const run = getGeneratorRun()
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('app:generator', run)
  }
}

/** Ошибку Python показываем тостом и пробрасываем в renderer как текст. */
async function guarded<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    sendProgress({ message, level: 'error' })
    throw new Error(message)
  }
}

function broadcast(): void {
  const state = buildState()
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('app:state', state)
  }
}

function sendProgress(event: ProgressEvent): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('app:progress', event)
  }
}

async function checkLogin(platform: PlatformId): Promise<boolean> {
  if (getRunner() !== 'idle') {
    return getPersisted().platforms[platform].loggedIn
  }
  checking.add(platform)
  broadcast()
  const alreadyOpen = isBrowserOpen(platform)
  try {
    let page
    if (alreadyOpen) {
      const context = getOpenContext(platform)
      page = context?.pages()[0] ?? (await context?.newPage())
      if (!page) throw new Error('Нет окна браузера')
    } else {
      page = (await openPlatformBrowser(platform)).page
    }
    const ok = await adapters[platform].loginCheck(page)
    const persisted = getPersisted()
    patchPersisted({
      platforms: {
        ...persisted.platforms,
        [platform]: { ...persisted.platforms[platform], loggedIn: ok }
      }
    })
    return ok
  } catch {
    const persisted = getPersisted()
    patchPersisted({
      platforms: {
        ...persisted.platforms,
        [platform]: { ...persisted.platforms[platform], loggedIn: false }
      }
    })
    return false
  } finally {
    checking.delete(platform)
    if (!alreadyOpen) await closePlatformBrowser(platform)
    broadcast()
  }
}

async function runEngineCheck(): Promise<EngineCheck> {
  engineStatus = await checkEngine()
  broadcast()
  return engineStatus
}

export function registerIpc(): void {
  onStoreChange(broadcast)
  onProgress(sendProgress)
  onYoutubeProfilesChange(broadcast)
  onGeneratorRunChange(sendGeneratorRun)
  onAutomationChange(broadcast)
  onTelegramChange(broadcast)
  setAutomationStopHook(cancelTelegramWork)
  setAutomationProgressSink(sendProgress)

  ipcMain.handle('app:getState', () => buildState())

  // --- генератор рилсов ---
  ipcMain.handle('gen:save', (_e, patch: Partial<GeneratorSettings>) => {
    const current = getGeneratorSettings()
    const before = current.auto.enabled
    const beforeTg = `${current.topMode}:${current.sourceMode}:${current.tg.enabled}:${current.tg.token}`
    // отметки последнего запуска ведёт автоматизация — из интерфейса их не перезаписываем
    if (patch.auto) patch = { ...patch, auto: { ...patch.auto, lastRun: current.auto.lastRun, lastTopSig: current.auto.lastTopSig } }
    if (patch.tg) {
      const nextToken = typeof patch.tg.token === 'string' ? patch.tg.token.trim() : current.tg.token
      const tokenChanged = nextToken !== current.tg.token.trim()
      patch = {
        ...patch,
        tg: {
          ...current.tg,
          enabled: typeof patch.tg.enabled === 'boolean' ? patch.tg.enabled : current.tg.enabled,
          token: nextToken,
          chatId: tokenChanged ? 0 : current.tg.chatId,
          offset: tokenChanged ? 0 : current.tg.offset,
          primed: tokenChanged ? false : current.tg.primed
        }
      }
    }
    const merged = saveGeneratorSettings(patch)
    if (before && !merged.auto.enabled) stopAutomation()
    if (`${merged.topMode}:${merged.sourceMode}:${merged.tg.enabled}:${merged.tg.token}` !== beforeTg) applyTelegramSettings()
    broadcast()
    return merged
  })
  ipcMain.handle('tg:unbind', () => {
    const tg = getGeneratorSettings().tg
    saveGeneratorSettings({ tg: { ...tg, chatId: 0 } })
    broadcast()
  })
  ipcMain.handle('auto:runNow', () => guarded(() => runCycle('manual')))
  ipcMain.handle('auto:stop', () => {
    stopAutomation()
    broadcast()
  })
  ipcMain.handle('gen:info', () => guarded(() => generatorInfo()))
  ipcMain.handle('gen:previewCta', (_e, settings: GeneratorSettings) => guarded(() => previewCta(settings)))
  ipcMain.handle('gen:previewBanner', (_e, settings: GeneratorSettings) => guarded(() => previewBanner(settings)))
  ipcMain.handle('gen:previewCover', (_e, settings: GeneratorSettings) => guarded(() => previewCover(settings)))
  ipcMain.handle('gen:stickers', (_e, settings: GeneratorSettings, force?: boolean) => guarded(() => loadStickers(settings, Boolean(force))))
  ipcMain.handle('gen:kieTitles', (_e, settings: GeneratorSettings) => guarded(() => kieTitles(settings)))
  ipcMain.handle('gen:linkTop', (_e, settings: GeneratorSettings) => guarded(() => linkTop(settings)))
  ipcMain.handle('gen:transcribe', (_e, settings: GeneratorSettings, force?: boolean) => guarded(() => transcribe(settings, Boolean(force))))
  ipcMain.handle('gen:generate', (_e, settings: GeneratorSettings, files?: string[]) =>
    guarded(async () => {
      const result = await generate(settings, files)
      sendProgress({ message: `Готово роликов: ${result.items.length}`, level: 'success' })
      return result
    })
  )
  ipcMain.handle('gen:generateToQueue', (_e, settings: GeneratorSettings, targets: TargetId[], files?: string[]) =>
    guarded(async () => {
      const out = await generateToQueue(settings, targets, files)
      sendProgress({ message: `Готово роликов: ${out.result.items.length}, загрузка запущена`, level: 'success' })
      if (out.jobs.length) startQueue()
      return out
    })
  )
  ipcMain.handle('gen:toQueue', (_e, items: GeneratedItem[], targets: TargetId[]) => {
    if (!targets.length) {
      sendProgress({ message: 'Не выбрано ни одного направления', level: 'warn' })
      return []
    }
    const jobs = itemsToJobs(items, targets)
    sendProgress({ message: `В очередь добавлено: ${jobs.length}`, level: 'success' })
    return jobs
  })
  ipcMain.handle('gen:pack', (_e, items: GeneratedItem[], settings: GeneratorSettings, platforms: PlatformId[]) =>
    guarded(async () => {
      const packed = await packItems(items, settings, platforms)
      const kie = packed.filter((i) => i.packSource === 'kie').length
      sendProgress({ message: `Тексты под площадки готовы: ${kie} от Kie${packed.length - kie ? `, ${packed.length - kie} локально` : ''}`, level: 'success' })
      return packed
    })
  )
  ipcMain.handle(
    'gen:packOne',
    (_e, base: { title: string; description: string; hashtags: string; transcript?: string; tgLink?: string }, platforms: PlatformId[]) =>
      guarded(() => packOne(base, platforms))
  )
  ipcMain.handle('gen:cancel', () => cancelGenerator())

  ipcMain.handle('engine:savePaths', async (_e, paths: EnginePaths) => {
    const clean = {} as EnginePaths
    for (const key of Object.keys(paths) as (keyof EnginePaths)[]) clean[key] = String(paths[key] ?? '').trim()
    patchPersisted({ enginePaths: { ...getPersisted().enginePaths, ...clean } })
    broadcast()
  })

  ipcMain.handle('engine:check', async () => {
    const status = await runEngineCheck()
    if (status.ok) void refreshYoutubeProfiles()
    return status
  })

  ipcMain.handle('files:pickFile', async (_e, title: string, filters?: { name: string; extensions: string[] }[]) => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    const opts: Electron.OpenDialogOptions = { title, properties: ['openFile'], filters }
    const result = win ? await dialog.showOpenDialog(win, opts) : await dialog.showOpenDialog(opts)
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('files:pickFolder', async (_e, title: string) => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    const opts: Electron.OpenDialogOptions = { title, properties: ['openDirectory'] }
    const result = win ? await dialog.showOpenDialog(win, opts) : await dialog.showOpenDialog(opts)
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('yt:refresh', async () => refreshYoutubeProfiles())

  ipcMain.handle('yt:open', async (_e, number: number) => {
    if (getRunner() !== 'idle') {
      sendProgress({ platform: 'youtube', message: 'Сначала остановите очередь, затем открывайте профиль.', level: 'warn' })
      return
    }
    try {
      sendProgress({ platform: 'youtube', message: `Открываю профиль YouTube #${number}: антидетект, прокси профиля…`, level: 'info' })
      await openYoutubeProfile(number, 'login', { url: 'https://studio.youtube.com/' })
    } catch (error) {
      sendProgress({
        platform: 'youtube',
        message: error instanceof Error ? error.message : 'Не удалось открыть профиль',
        level: 'error'
      })
    }
    broadcast()
  })

  ipcMain.handle('yt:close', async (_e, number: number) => {
    await closeYoutubeProfile(number)
    broadcast()
  })

  ipcMain.handle('yt:create', async (_e, proxy: string) => {
    try {
      const created = await runBridge<{ number: number; path: string }>('yt_bridge.py', ['create', '--platform', 'youtube', '--proxy', String(proxy || '')], {
        timeoutMs: 180_000,
        onLog: (line) => sendProgress({ platform: 'youtube', message: line, level: 'info' })
      })
      await refreshYoutubeProfiles()
      sendProgress({
        platform: 'youtube',
        message: `Аккаунт YouTube #${created.number} создан с новым отпечатком. Открываю Chrome для входа.`,
        level: 'success'
      })
      if (getRunner() === 'idle') {
        await openYoutubeProfile(created.number, 'login', { url: 'https://studio.youtube.com/' })
      }
      broadcast()
      return created
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось создать аккаунт'
      sendProgress({ platform: 'youtube', message, level: 'error' })
      throw error
    }
  })

  ipcMain.handle('yt:delete', async (_e, number: number) => {
    const id = targetId('youtube', number)
    try {
      await closeYoutubeProfile(number).catch(() => undefined)
      await runBridge('yt_bridge.py', ['delete', '--platform', 'youtube', '--acc', String(number)], {
        timeoutMs: 60_000,
        onLog: (line) => sendProgress({ platform: 'youtube', message: line, level: 'info' })
      })
      const persisted = getPersisted()
      const targets = { ...persisted.targets }
      delete targets[id]
      const jobs = persisted.jobs
        .map((job) => {
          if (!job.targets.includes(id)) return job
          const nextTargets = job.targets.filter((item) => item !== id)
          const results = { ...job.results }
          delete results[id]
          return { ...job, targets: nextTargets, results }
        })
        .filter((job) => job.targets.length > 0)
      patchPersisted({ targets, jobs })
      await refreshYoutubeProfiles()
      sendProgress({ platform: 'youtube', message: `Аккаунт YouTube #${number} удалён`, level: 'success' })
      broadcast()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить аккаунт'
      sendProgress({ platform: 'youtube', message, level: 'error' })
      throw error
    }
  })

  ipcMain.handle('accounts:create', async (_e, platform: PlatformId, proxy: string) => {
    const title = getPlatform(platform).shortName
    try {
      const created = await runBridge<{ number: number; path: string }>(
        'yt_bridge.py',
        ['create', '--platform', platform, '--proxy', String(proxy || '')],
        {
          timeoutMs: 180_000,
          onLog: (line) => sendProgress({ platform, message: line, level: 'info' })
        }
      )
      await refreshYoutubeProfiles()
      sendProgress({
        platform,
        message: `Аккаунт ${title} #${created.number} создан с новым отпечатком. Открываю Chrome для входа.`,
        level: 'success'
      })
      if (getRunner() === 'idle') {
        await openAccountProfile(platform, created.number, 'login', { url: getPlatform(platform).loginUrl })
      }
      broadcast()
      return created
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось создать аккаунт'
      sendProgress({ platform, message, level: 'error' })
      throw error
    }
  })

  ipcMain.handle('accounts:deleteProfile', async (_e, platform: PlatformId, number: number) => {
    const id = targetId(platform, number)
    const title = getPlatform(platform).shortName
    try {
      await closeAccountProfile(platform, number).catch(() => undefined)
      await runBridge('yt_bridge.py', ['delete', '--platform', platform, '--acc', String(number)], {
        timeoutMs: 60_000,
        onLog: (line) => sendProgress({ platform, message: line, level: 'info' })
      })
      const persisted = getPersisted()
      const targets = { ...persisted.targets }
      delete targets[id]
      const jobs = persisted.jobs
        .map((job) => {
          if (!job.targets.includes(id)) return job
          const nextTargets = job.targets.filter((item) => item !== id)
          const results = { ...job.results }
          delete results[id]
          return { ...job, targets: nextTargets, results }
        })
        .filter((job) => job.targets.length > 0)
      patchPersisted({ targets, jobs })
      await refreshYoutubeProfiles()
      sendProgress({ platform, message: `Аккаунт ${title} #${number} удалён`, level: 'success' })
      broadcast()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить аккаунт'
      sendProgress({ platform, message, level: 'error' })
      throw error
    }
  })

  ipcMain.handle('accounts:openProfile', async (_e, platform: PlatformId, number: number) => {
    if (getRunner() !== 'idle') {
      sendProgress({ platform, message: 'Сначала остановите очередь, затем открывайте профиль.', level: 'warn' })
      return
    }
    try {
      const title = getPlatform(platform).shortName
      sendProgress({ platform, message: `Открываю ${title} #${number}: отпечаток и прокси профиля…`, level: 'info' })
      await openAccountProfile(platform, number, 'login', { url: getPlatform(platform).loginUrl })
    } catch (error) {
      sendProgress({
        platform,
        message: error instanceof Error ? error.message : 'Не удалось открыть профиль',
        level: 'error'
      })
    }
    broadcast()
  })

  ipcMain.handle('accounts:closeProfile', async (_e, platform: PlatformId, number: number) => {
    await closeAccountProfile(platform, number)
    broadcast()
  })

  ipcMain.handle('targets:set', (_e, id: TargetId, enabled: boolean) => {
    const persisted = getPersisted()
    patchPersisted({ targets: { ...persisted.targets, [id]: Boolean(enabled) } })
    broadcast()
  })

  ipcMain.handle('queue:add', (_e, payload: NewVideoPayload) => addJob(payload))
  ipcMain.handle('queue:addBatch', (_e, payloads: NewVideoPayload[]) => addJobBatch(payloads))
  ipcMain.handle('queue:remove', (_e, id: string) => removeJob(id))
  ipcMain.handle('queue:start', () => startQueue())
  ipcMain.handle('queue:pause', () => pauseQueue())
  ipcMain.handle('queue:resume', () => resumeQueue())
  ipcMain.handle('queue:stop', () => stopQueue())
  ipcMain.handle('queue:retry', (_e, jobId: string, target?: TargetId) => retryJob(jobId, target))

  ipcMain.handle('files:pickVideo', async () => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    const result = win
      ? await dialog.showOpenDialog(win, {
          title: 'Выберите ролик',
          properties: ['openFile'],
          filters: [{ name: 'Видео', extensions: ['mp4', 'mov', 'webm', 'mkv', 'm4v'] }]
        })
      : await dialog.showOpenDialog({
          title: 'Выберите ролик',
          properties: ['openFile'],
          filters: [{ name: 'Видео', extensions: ['mp4', 'mov', 'webm', 'mkv', 'm4v'] }]
        })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('files:pickImage', async () => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    const result = win
      ? await dialog.showOpenDialog(win, {
          title: 'Выберите обложку',
          properties: ['openFile'],
          filters: [{ name: 'Изображения', extensions: ['jpg', 'jpeg', 'png', 'webp'] }]
        })
      : await dialog.showOpenDialog({
          title: 'Выберите обложку',
          properties: ['openFile'],
          filters: [{ name: 'Изображения', extensions: ['jpg', 'jpeg', 'png', 'webp'] }]
        })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('files:previewUrl', (_e, filePath: string) => toReelUrl(filePath))
  ipcMain.handle('files:openPath', (_e, target: string) => shell.openPath(target))
  ipcMain.handle('files:pickFiles', async (_e, title: string, filters?: { name: string; extensions: string[] }[]) => {
    const win = BrowserWindow.getFocusedWindow() ?? BrowserWindow.getAllWindows()[0]
    const opts: Electron.OpenDialogOptions = { title, properties: ['openFile', 'multiSelections'], filters }
    const result = win ? await dialog.showOpenDialog(win, opts) : await dialog.showOpenDialog(opts)
    return result.canceled ? [] : result.filePaths
  })

  ipcMain.handle('accounts:login', async (_e, platform: PlatformId) => {
    if (getRunner() !== 'idle') {
      sendProgress({
        platform,
        message: 'Сначала остановите очередь, затем откройте вход в аккаунт.',
        level: 'warn'
      })
      return
    }
    try {
      await gotoLogin(platform)
    } catch (error) {
      sendProgress({
        platform,
        message: error instanceof Error ? error.message : 'Не удалось открыть браузер для входа',
        level: 'error'
      })
    }
    broadcast()
  })

  ipcMain.handle('accounts:confirmLogin', async (_e, platform: PlatformId) => {
    return checkLogin(platform)
  })

  ipcMain.handle('accounts:closeBrowser', async (_e, platform: PlatformId) => {
    if (getRunner() !== 'idle') return
    await closePlatformBrowser(platform)
    broadcast()
  })

  ipcMain.handle('accounts:deleteSession', async (_e, platform: PlatformId) => {
    const title = getPlatform(platform).shortName
    if (platform === 'youtube') {
      const message = 'YouTube удаляется отдельными карточками профилей.'
      sendProgress({ platform, message, level: 'warn' })
      throw new Error(message)
    }
    if (getRunner() !== 'idle') {
      const message = 'Сначала остановите очередь, затем удаляйте аккаунт.'
      sendProgress({ platform, message, level: 'warn' })
      throw new Error(message)
    }
    const id = targetId(platform)
    try {
      await closePlatformBrowser(platform)
      const dir = sessionPath(platform)
      if (existsSync(dir)) rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
      const persisted = getPersisted()
      const targets = { ...persisted.targets }
      delete targets[id]
      const jobs = persisted.jobs
        .map((job) => {
          if (!job.targets.includes(id)) return job
          const nextTargets = job.targets.filter((item) => item !== id)
          const results = { ...job.results }
          delete results[id]
          return { ...job, targets: nextTargets, results }
        })
        .filter((job) => job.targets.length > 0)
      patchPersisted({
        targets,
        jobs,
        platforms: {
          ...persisted.platforms,
          [platform]: { ...persisted.platforms[platform], loggedIn: false }
        }
      })
      sendProgress({ platform, message: `Прежний аккаунт ${title} удалён. Вход можно сделать заново.`, level: 'success' })
      broadcast()
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Не удалось удалить аккаунт'
      sendProgress({ platform, message, level: 'error' })
      throw error
    }
  })

  ipcMain.handle('accounts:check', (_e, platform: PlatformId) => checkLogin(platform))

  ipcMain.handle('accounts:checkAll', async () => {
    for (const id of PLATFORM_IDS) {
      try {
        await checkLogin(id)
      } catch {
        /* одна площадка не должна ронять остальные */
      }
    }
  })

  ipcMain.handle('settings:save', (_e, settings: AppSettings) => {
    patchPersisted({ settings })
    broadcast()
  })

  ipcMain.handle('composer:save', (_e, composer: ComposerDraft) => {
    patchPersisted({ composer: mergeComposer({ ...getPersisted().composer, ...composer }) })
    broadcast()
  })

  ipcMain.handle('composer:saveOptions', (_e, publishOptions: Parameters<typeof mergePublishOptions>[0]) => {
    const current = getPersisted().composer
    patchPersisted({
      composer: { ...current, publishOptions: mergePublishOptions(publishOptions) }
    })
    broadcast()
  })

  ipcMain.handle('contentDefaults:save', (_e, contentDefaults: ContentDefaults) => {
    const persisted = getPersisted()
    const merged = mergeContentDefaults(contentDefaults)
    patchPersisted({
      contentDefaults: merged,
      composer: refreshIdleComposer(persisted.composer, persisted.contentDefaults, merged)
    })
    broadcast()
  })

  ipcMain.handle('proxy:save', (_e, proxy: ProxyConfig) => {
    patchPersisted({ proxy: normalizeProxy(proxy) })
    broadcast()
  })

  ipcMain.handle('proxy:setPlatform', (_e, platform: PlatformId, useProxy: boolean) => {
    const persisted = getPersisted()
    patchPersisted({
      platforms: {
        ...persisted.platforms,
        [platform]: { ...persisted.platforms[platform], useProxy }
      }
    })
    broadcast()
  })

  ipcMain.handle('proxy:test', async () => testProxy())

  ipcMain.handle('app:stress', async () => {
    const { runStressTest } = await import('./stress')
    return runStressTest()
  })

  ipcMain.handle('app:quitBrowsers', () => closeAllBrowsers())

  ipcMain.handle('log:read', () => readUploadLog(80))
}

export async function initRuntime(): Promise<void> {
  const probe = await probeChrome()
  chromeAvailable = probe.ok
  chromeMessage = probe.message
  broadcast()
  void (async () => {
    if (!quickEngineCheck().ok) return
    const status = await runEngineCheck()
    if (status.ok) await refreshYoutubeProfiles()
  })()
  startAutomation()
}
