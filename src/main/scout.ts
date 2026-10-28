import { mkdirSync, readdirSync, writeFileSync } from 'fs'
import { join } from 'path'
import { setTimeout as sleep } from 'node:timers/promises'
import { defaultPublishOptions } from '../shared/publish-options'
import type { PlatformId } from '../shared/types'
import { closeAllBrowsers, closePlatformBrowser, openPlatformBrowser } from './browser'
import { adapters } from './uploaders'

function projectRoot(): string {
  return join(process.env.USERPROFILE || '', 'Desktop', 'РИЛС-ЗАГРУЗКА')
}

function pickMedia(): { videoPath: string; coverPath?: string } {
  const root = projectRoot()
  const files = readdirSync(root)
  const video = files.find((name) => name.toLowerCase().endsWith('.mp4'))
  const cover = files.find((name) => name.toLowerCase() === 'test-cover.png') || files.find((name) => name.toLowerCase().endsWith('.png'))
  if (!video) throw new Error('В папке проекта нет тестового mp4')
  return {
    videoPath: join(root, video),
    coverPath: cover ? join(root, cover) : undefined
  }
}

export async function runScout(): Promise<Record<string, string>> {
  const media = pickMedia()
  const requested = (process.env.REELS_SCOUT_PLATFORMS || 'youtube,rutube,pinterest,dzen,tiktok,vk,instagram')
    .split(',')
    .map((id) => id.trim())
    .filter(Boolean) as PlatformId[]
  const options = defaultPublishOptions()
  const results: Record<string, string> = {}

  for (const id of requested) {
    const adapter = adapters[id]
    if (!adapter) {
      results[id] = 'unknown platform'
      continue
    }
    console.log(`[scout] ${id} start`)
    try {
      const { page } = await openPlatformBrowser(id)
      const loggedIn = await adapter.loginCheck(page)
      if (!loggedIn) {
        results[id] = 'нет сессии'
        continue
      }
      const url = await adapter.upload(page, {
        videoPath: media.videoPath,
        title: 'Тест шортс (черновик, не публиковать)',
        description: 'Проверка загрузчика',
        coverPath: media.coverPath,
        options: options[id],
        dryRun: true
      })
      results[id] = `ok ${url ?? page.url()}`
      await sleep(1500)
    } catch (error) {
      results[id] = error instanceof Error ? error.message : String(error)
      console.error(`[scout] ${id} fail`, results[id])
    } finally {
      await closePlatformBrowser(id).catch(() => undefined)
    }
  }

  const outDir = join(projectRoot(), 'scripts')
  mkdirSync(outDir, { recursive: true })
  writeFileSync(join(outDir, 'scout-results.json'), JSON.stringify(results, null, 2), 'utf-8')
  console.log('[scout] done', results)
  await closeAllBrowsers()
  return results
}
