import { setTimeout as sleep } from 'node:timers/promises'
import { pathToFileURL } from 'url'
import { toReelUrl } from './protocol'
import {
  addJob,
  getRunner,
  pauseQueue,
  retryJob,
  setStressUploads,
  startQueue,
  stopQueue
} from './scheduler'
import { getPersisted, patchPersisted } from './store'
import type { PlatformId } from '../shared/types'

function snapshot(): Array<{ status: string; results: string[] }> {
  return getPersisted().jobs.map((job) => ({
    status: job.status,
    results: job.enabledPlatforms.map((id) => `${id}:${job.results[id]?.status ?? 'none'}`)
  }))
}

export async function runStressTest(): Promise<{ ok: boolean; stuckUploading: number; queuedIdle: boolean }> {
  setStressUploads(true)
  const prevSettings = getPersisted().settings
  patchPersisted({
    settings: { ...prevSettings, delayBetweenPlatformsMs: 40, delayBetweenVideosMs: 40 },
    jobs: [],
    history: []
  })

  const platforms: PlatformId[] = ['youtube', 'vk', 'tiktok', 'instagram']
  for (let i = 0; i < 8; i++) {
    addJob({
      videoPath: `C:\\Users\\Public\\Videos\\stress-${i}.mp4`,
      title: `Stress ${i}`,
      description: 'stress',
      enabledPlatforms: platforms,
      overrides: {}
    })
  }

  startQueue()
  await sleep(120)
  pauseQueue()
  await sleep(80)
  startQueue()
  await sleep(200)
  stopQueue()
  await sleep(400)

  const afterStop = snapshot()
  const stuckUploading = afterStop.filter((j) => j.status === 'uploading').length

  const failed = getPersisted().jobs.find((j) => Object.values(j.results).some((r) => r?.status === 'error'))
  if (failed) {
    retryJob(failed.id)
    await sleep(80)
  }
  await sleep(200)
  stopQueue()
  await sleep(300)

  const afterRetry = snapshot()
  const queuedIdle = afterRetry.some((j) => j.status === 'queued') && getRunner() === 'idle'

  const paths = [
    'C:\\Users\\Public\\Videos\\video.mp4',
    'C:/Users/Public/Videos/clip with spaces.mp4',
    'C:\\temp\\a#hash.mp4',
    'C:\\temp\\q?query.mp4'
  ]
  for (const filePath of paths) {
    try {
      const href = toReelUrl(filePath)
      const parsed = new URL(href).searchParams.get('p')
      pathToFileURL(parsed ?? '')
    } catch {
      continue
    }
  }

  setStressUploads(false)
  patchPersisted({ settings: prevSettings })
  return { ok: stuckUploading === 0 && !queuedIdle, stuckUploading, queuedIdle }
}
