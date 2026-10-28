import type { PlatformId } from './types'

export interface PlatformMeta {
  id: PlatformId
  name: string
  shortName: string
  url: string
  loginUrl: string
  uploadUrl: string
  color: string
  format: string
}

export const PLATFORMS: PlatformMeta[] = [
  {
    id: 'youtube',
    name: 'YouTube Shorts',
    shortName: 'YouTube',
    url: 'https://www.youtube.com',
    loginUrl: 'https://studio.youtube.com',
    uploadUrl: 'https://studio.youtube.com',
    color: '#FF0033',
    format: 'Shorts'
  },
  {
    id: 'rutube',
    name: 'Rutube Shorts',
    shortName: 'Rutube',
    url: 'https://rutube.ru',
    loginUrl: 'https://studio.rutube.ru',
    uploadUrl: 'https://studio.rutube.ru',
    color: '#1A9F29',
    format: 'Shorts'
  },
  {
    id: 'pinterest',
    name: 'Pinterest Pins',
    shortName: 'Pinterest',
    url: 'https://www.pinterest.com',
    loginUrl: 'https://www.pinterest.com',
    uploadUrl: 'https://ru.pinterest.com/pin-creation-tool/',
    color: '#E60023',
    format: 'Pin'
  },
  {
    id: 'dzen',
    name: 'Дзен',
    shortName: 'Дзен',
    url: 'https://dzen.ru',
    loginUrl: 'https://dzen.ru',
    uploadUrl: 'https://dzen.ru/profile/editor/',
    color: '#FFCC00',
    format: 'Ролик'
  },
  {
    id: 'tiktok',
    name: 'TikTok',
    shortName: 'TikTok',
    url: 'https://www.tiktok.com',
    loginUrl: 'https://www.tiktok.com/login',
    uploadUrl: 'https://www.tiktok.com/tiktokstudio/upload',
    color: '#25F4EE',
    format: 'Видео'
  },
  {
    id: 'vk',
    name: 'VK Клипы',
    shortName: 'VK',
    url: 'https://vk.ru',
    loginUrl: 'https://vk.ru',
    uploadUrl: 'https://vk.ru/clips',
    color: '#0077FF',
    format: 'Клип'
  },
  {
    id: 'instagram',
    name: 'Instagram Reels',
    shortName: 'Instagram',
    url: 'https://www.instagram.com',
    loginUrl: 'https://www.instagram.com/accounts/login/',
    uploadUrl: 'https://www.instagram.com/',
    color: '#E1306C',
    format: 'Reels'
  }
]

export const PLATFORM_IDS = PLATFORMS.map((p) => p.id)

export function getPlatform(id: PlatformId): PlatformMeta {
  return PLATFORMS.find((p) => p.id === id)!
}

/** Название есть у YouTube, Rutube и Pinterest. У остальных — только описание. */
export function hasVideoTitle(id: PlatformId): boolean {
  return id === 'youtube' || id === 'rutube' || id === 'pinterest'
}

/** Общие хэштеги из «Нового ролика» уходят в TikTok и Дзен. */
export function usesHashtags(id: PlatformId): boolean {
  return id === 'tiktok' || id === 'dzen'
}
