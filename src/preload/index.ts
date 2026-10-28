import { contextBridge, ipcRenderer, webUtils } from 'electron'
import type {
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
  TargetId,
  YoutubeProfileInfo
} from '../shared/types'
import type { PublishOptionsByPlatform } from '../shared/publish-options'
import type { KiePackResult } from '../shared/kie-pack'
import type {
  GeneratedItem,
  GenerateResult,
  GeneratorInfo,
  GeneratorRun,
  GeneratorSettings,
  LinkTopResult,
  StickerPackInfo
} from '../shared/generator'

const api = {
  platform: process.platform,
  getState: (): Promise<AppState> => ipcRenderer.invoke('app:getState'),
  addJob: (payload: NewVideoPayload): Promise<unknown> => ipcRenderer.invoke('queue:add', payload),
  addJobBatch: (payloads: NewVideoPayload[]): Promise<unknown> => ipcRenderer.invoke('queue:addBatch', payloads),
  removeJob: (id: string): Promise<void> => ipcRenderer.invoke('queue:remove', id),
  startQueue: (): Promise<void> => ipcRenderer.invoke('queue:start'),
  pauseQueue: (): Promise<void> => ipcRenderer.invoke('queue:pause'),
  resumeQueue: (): Promise<void> => ipcRenderer.invoke('queue:resume'),
  stopQueue: (): Promise<void> => ipcRenderer.invoke('queue:stop'),
  retryJob: (jobId: string, target?: TargetId): Promise<void> => ipcRenderer.invoke('queue:retry', jobId, target),
  pickVideo: (): Promise<string | null> => ipcRenderer.invoke('files:pickVideo'),
  pickImage: (): Promise<string | null> => ipcRenderer.invoke('files:pickImage'),
  previewUrl: (filePath: string): Promise<string> => ipcRenderer.invoke('files:previewUrl', filePath),
  login: (platform: PlatformId): Promise<void> => ipcRenderer.invoke('accounts:login', platform),
  confirmLogin: (platform: PlatformId): Promise<boolean> => ipcRenderer.invoke('accounts:confirmLogin', platform),
  closeBrowser: (platform: PlatformId): Promise<void> => ipcRenderer.invoke('accounts:closeBrowser', platform),
  deleteSession: (platform: PlatformId): Promise<void> => ipcRenderer.invoke('accounts:deleteSession', platform),
  checkLogin: (platform: PlatformId): Promise<boolean> => ipcRenderer.invoke('accounts:check', platform),
  checkAllLogins: (): Promise<void> => ipcRenderer.invoke('accounts:checkAll'),
  saveSettings: (settings: AppSettings): Promise<void> => ipcRenderer.invoke('settings:save', settings),
  saveComposer: (composer: ComposerDraft): Promise<void> => ipcRenderer.invoke('composer:save', composer),
  savePublishOptions: (publishOptions: PublishOptionsByPlatform): Promise<void> =>
    ipcRenderer.invoke('composer:saveOptions', publishOptions),
  saveContentDefaults: (contentDefaults: ContentDefaults): Promise<void> =>
    ipcRenderer.invoke('contentDefaults:save', contentDefaults),
  saveProxy: (proxy: ProxyConfig): Promise<void> => ipcRenderer.invoke('proxy:save', proxy),
  setPlatformProxy: (platform: PlatformId, useProxy: boolean): Promise<void> =>
    ipcRenderer.invoke('proxy:setPlatform', platform, useProxy),
  testProxy: (): Promise<{ ok: boolean; ip?: string; error?: string }> => ipcRenderer.invoke('proxy:test'),
  getPathForFile: (file: File): string => webUtils.getPathForFile(file),
  readLog: (): Promise<string> => ipcRenderer.invoke('log:read'),
  pickFile: (title: string, filters?: { name: string; extensions: string[] }[]): Promise<string | null> =>
    ipcRenderer.invoke('files:pickFile', title, filters),
  pickFolder: (title: string): Promise<string | null> => ipcRenderer.invoke('files:pickFolder', title),
  pickFiles: (title: string, filters?: { name: string; extensions: string[] }[]): Promise<string[]> =>
    ipcRenderer.invoke('files:pickFiles', title, filters),
  openPath: (target: string): Promise<string> => ipcRenderer.invoke('files:openPath', target),
  saveEnginePaths: (paths: EnginePaths): Promise<void> => ipcRenderer.invoke('engine:savePaths', paths),
  checkEngine: (): Promise<EngineCheck> => ipcRenderer.invoke('engine:check'),
  refreshYoutubeProfiles: (): Promise<YoutubeProfileInfo[]> => ipcRenderer.invoke('yt:refresh'),
  openYoutubeProfile: (number: number): Promise<void> => ipcRenderer.invoke('yt:open', number),
  closeYoutubeProfile: (number: number): Promise<void> => ipcRenderer.invoke('yt:close', number),
  createYoutubeAccount: (proxy: string): Promise<{ number: number; path: string }> => ipcRenderer.invoke('yt:create', proxy),
  deleteYoutubeAccount: (number: number): Promise<void> => ipcRenderer.invoke('yt:delete', number),
  createAccount: (platform: PlatformId, proxy: string): Promise<{ number: number; path: string }> =>
    ipcRenderer.invoke('accounts:create', platform, proxy),
  deleteAccount: (platform: PlatformId, number: number): Promise<void> =>
    ipcRenderer.invoke('accounts:deleteProfile', platform, number),
  openAccount: (platform: PlatformId, number: number): Promise<void> =>
    ipcRenderer.invoke('accounts:openProfile', platform, number),
  closeAccount: (platform: PlatformId, number: number): Promise<void> =>
    ipcRenderer.invoke('accounts:closeProfile', platform, number),
  setTarget: (id: TargetId, enabled: boolean): Promise<void> => ipcRenderer.invoke('targets:set', id, enabled),
  // генератор рилсов
  saveGenerator: (patch: Partial<GeneratorSettings>): Promise<GeneratorSettings> => ipcRenderer.invoke('gen:save', patch),
  generatorInfo: (): Promise<GeneratorInfo> => ipcRenderer.invoke('gen:info'),
  generatorPreviewCta: (settings: GeneratorSettings): Promise<{ image: string; slogan: string; tgCall: string }> =>
    ipcRenderer.invoke('gen:previewCta', settings),
  generatorPreviewBanner: (settings: GeneratorSettings): Promise<{ image: string; pauseAt: number; text: string }> =>
    ipcRenderer.invoke('gen:previewBanner', settings),
  generatorPreviewCover: (settings: GeneratorSettings): Promise<{ image: string; video: string; phrase: string; disabled?: boolean }> =>
    ipcRenderer.invoke('gen:previewCover', settings),
  generatorStickers: (settings: GeneratorSettings, force?: boolean): Promise<StickerPackInfo> =>
    ipcRenderer.invoke('gen:stickers', settings, force),
  generatorKieTitles: (settings: GeneratorSettings): Promise<{ titles: string[]; source: string }> =>
    ipcRenderer.invoke('gen:kieTitles', settings),
  generatorLinkTop: (settings: GeneratorSettings): Promise<LinkTopResult> => ipcRenderer.invoke('gen:linkTop', settings),
  generatorTranscribe: (settings: GeneratorSettings, force?: boolean): Promise<{ text: string; phrases: string[]; video: string }> =>
    ipcRenderer.invoke('gen:transcribe', settings, force),
  generatorGenerate: (settings: GeneratorSettings, files?: string[]): Promise<GenerateResult> =>
    ipcRenderer.invoke('gen:generate', settings, files),
  generatorGenerateToQueue: (settings: GeneratorSettings, targets: TargetId[], files?: string[]): Promise<{ result: GenerateResult; jobs: unknown[] }> =>
    ipcRenderer.invoke('gen:generateToQueue', settings, targets, files),
  generatorToQueue: (items: GeneratedItem[], targets: TargetId[]): Promise<unknown[]> => ipcRenderer.invoke('gen:toQueue', items, targets),
  generatorPack: (items: GeneratedItem[], settings: GeneratorSettings, platforms: PlatformId[]): Promise<GeneratedItem[]> =>
    ipcRenderer.invoke('gen:pack', items, settings, platforms),
  kiePackOne: (
    base: { title: string; description: string; hashtags: string; transcript?: string; tgLink?: string },
    platforms: PlatformId[]
  ): Promise<KiePackResult> => ipcRenderer.invoke('gen:packOne', base, platforms),
  generatorCancel: (): Promise<void> => ipcRenderer.invoke('gen:cancel'),
  automationRunNow: (): Promise<boolean> => ipcRenderer.invoke('auto:runNow'),
  automationStop: (): Promise<void> => ipcRenderer.invoke('auto:stop'),
  telegramUnbind: (): Promise<void> => ipcRenderer.invoke('tg:unbind'),
  onGeneratorRun: (callback: (run: GeneratorRun) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, run: GeneratorRun): void => callback(run)
    ipcRenderer.on('app:generator', listener)
    return () => {
      ipcRenderer.removeListener('app:generator', listener)
    }
  },
  onState: (callback: (state: AppState) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, state: AppState): void => callback(state)
    ipcRenderer.on('app:state', listener)
    return () => {
      ipcRenderer.removeListener('app:state', listener)
    }
  },
  onProgress: (callback: (event: ProgressEvent) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, event: ProgressEvent): void => callback(event)
    ipcRenderer.on('app:progress', listener)
    return () => {
      ipcRenderer.removeListener('app:progress', listener)
    }
  }
}

export type ReelsApi = typeof api

contextBridge.exposeInMainWorld('api', api)
