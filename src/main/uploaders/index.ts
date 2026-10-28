import type { PlatformId } from '../../shared/types'
import { dzenAdapter } from './dzen'
import { instagramAdapter } from './instagram'
import { pinterestAdapter } from './pinterest'
import { rutubeAdapter } from './rutube'
import { tiktokAdapter } from './tiktok'
import type { PlatformAdapter } from './types'
import { vkAdapter } from './vk'
import { youtubeAdapter } from './youtube'
import { preparePage } from './helpers'

function wrap(adapter: PlatformAdapter): PlatformAdapter {
  return {
    loginCheck: async (page) => {
      await preparePage(page)
      return adapter.loginCheck(page)
    },
    upload: async (page, payload) => {
      await preparePage(page)
      return adapter.upload(page, payload)
    }
  }
}

export const adapters: Record<PlatformId, PlatformAdapter> = {
  youtube: wrap(youtubeAdapter),
  rutube: wrap(rutubeAdapter),
  pinterest: wrap(pinterestAdapter),
  dzen: wrap(dzenAdapter),
  tiktok: wrap(tiktokAdapter),
  vk: wrap(vkAdapter),
  instagram: wrap(instagramAdapter)
}
