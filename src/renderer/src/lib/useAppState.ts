import { emptyProxy } from '@shared/proxy'
import { defaultContentDefaults } from '@shared/content-defaults'
import { defaultComposer } from '@shared/publish-options'
import { defaultGeneratorSettings } from '@shared/generator'
import { useEffect, useState } from 'react'
import { PLATFORM_IDS } from '@shared/platforms'
import type { AppState, PlatformId, YoutubeProfileInfo } from '@shared/types'

function emptyPlatformProfiles(): Record<PlatformId, YoutubeProfileInfo[]> {
  const out = {} as Record<PlatformId, YoutubeProfileInfo[]>
  for (const id of PLATFORM_IDS) out[id] = []
  return out
}

const emptyState = (): AppState => ({
  jobs: [],
  history: [],
  settings: {
    delayBetweenPlatformsMs: 30_000,
    delayBetweenVideosMs: 60_000,
    headed: true,
    antidetectOnUpload: false,
    youtubeDistribute: false,
    youtubePerChannel: 1,
    kieApiKey: ''
  },
  proxy: emptyProxy(),
  platforms: {
    youtube: { useProxy: false, loggedIn: false },
    rutube: { useProxy: false, loggedIn: false },
    pinterest: { useProxy: false, loggedIn: false },
    dzen: { useProxy: false, loggedIn: false },
    tiktok: { useProxy: false, loggedIn: false },
    vk: { useProxy: false, loggedIn: false },
    instagram: { useProxy: false, loggedIn: false }
  },
  accounts: {
    youtube: { platform: 'youtube', loggedIn: false, checking: false, browserOpen: false },
    rutube: { platform: 'rutube', loggedIn: false, checking: false, browserOpen: false },
    pinterest: { platform: 'pinterest', loggedIn: false, checking: false, browserOpen: false },
    dzen: { platform: 'dzen', loggedIn: false, checking: false, browserOpen: false },
    tiktok: { platform: 'tiktok', loggedIn: false, checking: false, browserOpen: false },
    vk: { platform: 'vk', loggedIn: false, checking: false, browserOpen: false },
    instagram: { platform: 'instagram', loggedIn: false, checking: false, browserOpen: false }
  },
  composer: defaultComposer(),
  contentDefaults: defaultContentDefaults(),
  runner: 'idle',
  chromeAvailable: true,
  enginePaths: { pythonExe: '', tgRoot: '', vkBot: '', ydaRoot: '', ytCookies: '' },
  engine: { ok: false, problems: [] },
  youtubeProfiles: [],
  platformProfiles: emptyPlatformProfiles(),
  youtubeProfilesLoading: false,
  openYoutubeProfiles: [],
  openAccountProfiles: [],
  targets: {},
  generator: defaultGeneratorSettings(),
  generatorRun: { running: false, task: '', progress: 0, log: [] },
  automation: { enabled: false, cycleRunning: false },
  telegram: { enabled: false, listening: false, username: '', chatId: 0, queued: 0, lastError: '', lastText: '', lastUrl: '' }
})

export function useAppState(): { state: AppState; ready: boolean } {
  const [state, setState] = useState<AppState>(emptyState)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    void window.api.getState().then((next) => {
      setState(next)
      setReady(true)
    })
    return window.api.onState(setState)
  }, [])

  return { state, ready }
}
