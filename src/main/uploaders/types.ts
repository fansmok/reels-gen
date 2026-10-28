import type { Page } from 'playwright-core'
import type { PublishOptionsByPlatform } from '../../shared/publish-options'
import type { PlatformId } from '../../shared/types'

export interface UploadPayload {
  videoPath: string
  title: string
  description: string
  hashtags?: string
  coverPath?: string
  options: PublishOptionsByPlatform[PlatformId]
  dryRun?: boolean
}

export interface PlatformAdapter {
  loginCheck: (page: Page) => Promise<boolean>
  upload: (page: Page, payload: UploadPayload) => Promise<string | undefined>
}
