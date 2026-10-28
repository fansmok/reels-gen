import { PLATFORM_IDS } from './platforms'
import type { ComposerDraft } from './types'

export type YoutubeVisibility = 'public' | 'unlisted' | 'private'
export type TiktokAudience = 'everyone' | 'friends' | 'only_me'

export interface YoutubePublishOptions {
  madeForKids: boolean
  ageRestricted: boolean
  visibility: YoutubeVisibility
  paidPromotion: boolean
  alteredContent: boolean
  notifySubscribers: boolean
}

/** Категории студии RUTUBE: https://rutube.ru/api/video/category/ */
export const RUTUBE_CATEGORIES = [
  { id: 2, name: 'Авто-мото' },
  { id: 41, name: 'Аниме' },
  { id: 48, name: 'Аудио' },
  { id: 60, name: 'Аудиокниги' },
  { id: 67, name: 'Бизнес и предпринимательство' },
  { id: 22, name: 'Видеоигры' },
  { id: 42, name: 'Детям' },
  { id: 69, name: 'Дизайн' },
  { id: 59, name: 'Еда' },
  { id: 10, name: 'Животные' },
  { id: 71, name: 'Здоровье' },
  { id: 58, name: 'Интервью' },
  { id: 64, name: 'Культура' },
  { id: 44, name: 'Красота' },
  { id: 73, name: 'Лайфстайл' },
  { id: 55, name: 'Лайфхаки' },
  { id: 7, name: 'Мультфильмы' },
  { id: 6, name: 'Музыка' },
  { id: 52, name: 'Наука' },
  { id: 72, name: 'Недвижимость' },
  { id: 8, name: 'Новости и СМИ' },
  { id: 78, name: 'Обзоры и распаковки товаров' },
  { id: 17, name: 'Обучение' },
  { id: 53, name: 'Охота и рыбалка' },
  { id: 51, name: 'Политика' },
  { id: 70, name: 'Природа' },
  { id: 50, name: 'Психология' },
  { id: 11, name: 'Путешествия' },
  { id: 13, name: 'Разное' },
  { id: 57, name: 'Развлечения' },
  { id: 63, name: 'Религия' },
  { id: 61, name: 'Сад и огород' },
  { id: 5, name: 'Сериалы' },
  { id: 16, name: 'Спорт' },
  { id: 62, name: 'Строительство и ремонт' },
  { id: 43, name: 'Телепередачи' },
  { id: 68, name: 'Техника и оборудование' },
  { id: 45, name: 'Технологии и интернет' },
  { id: 4, name: 'Фильмы' },
  { id: 35, name: 'Хобби' },
  { id: 54, name: 'Эзотерика' },
  { id: 19, name: 'Юмор' }
] as const

export const RUTUBE_CATEGORY_NAMES = RUTUBE_CATEGORIES.map((item) => item.name)
export const DEFAULT_RUTUBE_CATEGORY = 'Разное'

export type RutubeCategory = (typeof RUTUBE_CATEGORIES)[number]['name']

export interface RutubePublishOptions {
  comments: boolean
  adult: boolean
  category: RutubeCategory | string
}

export interface PinterestPublishOptions {
  link: string
  comments: boolean
  aiGenerated: boolean
}

export const TIKTOK_CAPTION_MAX = 4000
export const TIKTOK_HASHTAG_MAX = 5
export const SHARED_HASHTAG_MAX = TIKTOK_HASHTAG_MAX

export function parseTiktokHashtags(raw?: string): string[] {
  return String(raw || '')
    .replace(/#/g, ' ')
    .split(/[,;\n]+/)
    .flatMap((chunk) => chunk.trim().split(/\s+/))
    .map((item) => item.trim().replace(/^#+/, ''))
    .filter(Boolean)
    .slice(0, TIKTOK_HASHTAG_MAX)
}

export const parseHashtags = parseTiktokHashtags

export function clampTiktokCaption(text?: string): string {
  return String(text || '').slice(0, TIKTOK_CAPTION_MAX)
}

export interface TiktokPublishOptions {
  description: string
  hashtags: string
  audience: TiktokAudience
  comments: boolean
  allowReuse: boolean
}

export interface VkPublishOptions {
  comments: boolean
  wallPost: boolean
  duets: boolean
  publishStory: boolean
  /** Ссылка на сообщество. Пусто — клип уходит в профиль. */
  communityUrl: string
}

const VK_PROFILE_CLIPS = 'https://vk.ru/clips'
const VK_RESERVED = /^(clips|feed|im|video|music|search|discover|settings|apps|groups|vkvideo|id\d+)$/i

/**
 * Из поля настроек собирает URL клипов сообщества: https://vk.ru/clips/club240633418
 * Пустая строка → undefined (публикация в профиле).
 */
export function parseVkCommunityClipsUrl(raw?: string): string | undefined {
  const text = String(raw || '').trim()
  if (!text) return undefined
  if (/^\d+$/.test(text)) return `${VK_PROFILE_CLIPS}/club${text}`

  const clubOnly = text.match(/^(club|public|event)(\d+)$/i)
  if (clubOnly) return `${VK_PROFILE_CLIPS}/${clubOnly[1].toLowerCase()}${clubOnly[2]}`

  let path = text
    .replace(/^https?:\/\//i, '')
    .replace(/^www\./i, '')
    .replace(/^(m\.)?vk\.(ru|com)\//i, '')
    .replace(/[?#].*$/, '')
    .replace(/^\/+|\/+$/g, '')

  const clipsClub = path.match(/^clips\/((?:club|public|event)\d+)$/i)
  if (clipsClub) return `${VK_PROFILE_CLIPS}/${clipsClub[1].toLowerCase()}`

  const clipsScreen = path.match(/^clips\/([a-zA-Z0-9._]+)$/i)
  if (clipsScreen && !VK_RESERVED.test(clipsScreen[1])) {
    return `${VK_PROFILE_CLIPS}/${clipsScreen[1]}`
  }

  const clubPath = path.match(/^(club|public|event)(\d+)$/i)
  if (clubPath) return `${VK_PROFILE_CLIPS}/${clubPath[1].toLowerCase()}${clubPath[2]}`

  const screen = path.match(/^([a-zA-Z0-9._]+)$/i)
  if (screen && !VK_RESERVED.test(screen[1])) return `${VK_PROFILE_CLIPS}/${screen[1]}`

  return undefined
}

export function vkClipsUploadUrl(communityUrl?: string): string {
  const text = String(communityUrl || '').trim()
  if (!text) return VK_PROFILE_CLIPS
  const parsed = parseVkCommunityClipsUrl(text)
  if (!parsed) {
    throw new Error(
      'Не понял ссылку на сообщество VK. Пример: https://vk.ru/clips/club240633418. Пустое поле — публикация в профиле.'
    )
  }
  return parsed
}

export type DzenCommentAudience = 'everyone' | 'subscribers' | 'nobody'

export const DZEN_COMMENT_AUDIENCE_LABELS: Record<DzenCommentAudience, string> = {
  everyone: 'Все пользователи',
  subscribers: 'Подписчики',
  nobody: 'Никто'
}

export interface DzenPublishOptions {
  tags: string
  commentsTitle: string
  commentAudience: DzenCommentAudience
}

export interface InstagramPublishOptions {
  shareToFeed: boolean
  comments: boolean
}

export interface PublishOptionsByPlatform {
  youtube: YoutubePublishOptions
  rutube: RutubePublishOptions
  pinterest: PinterestPublishOptions
  dzen: DzenPublishOptions
  tiktok: TiktokPublishOptions
  vk: VkPublishOptions
  instagram: InstagramPublishOptions
}

export function defaultPublishOptions(): PublishOptionsByPlatform {
  return {
    youtube: {
      madeForKids: false,
      ageRestricted: false,
      visibility: 'public',
      paidPromotion: false,
      alteredContent: false,
      notifySubscribers: true
    },
    rutube: { comments: true, adult: false, category: DEFAULT_RUTUBE_CATEGORY },
    pinterest: { link: '', comments: true, aiGenerated: false },
    dzen: { tags: '', commentsTitle: '', commentAudience: 'everyone' },
    tiktok: { description: '', hashtags: '', audience: 'everyone', comments: true, allowReuse: true },
    vk: { comments: true, wallPost: true, duets: true, publishStory: false, communityUrl: '' },
    instagram: { shareToFeed: true, comments: true }
  }
}

export function mergePublishOptions(
  saved?: Partial<PublishOptionsByPlatform>
): PublishOptionsByPlatform {
  const base = defaultPublishOptions()
  if (!saved) return base
  return {
    youtube: { ...base.youtube, ...saved.youtube },
    rutube: {
      ...base.rutube,
      ...saved.rutube,
      category: saved.rutube?.category || base.rutube.category
    },
    pinterest: { ...base.pinterest, ...saved.pinterest },
    dzen: { ...base.dzen, ...saved.dzen },
    tiktok: {
      ...base.tiktok,
      ...saved.tiktok,
      description: saved.tiktok?.description ?? base.tiktok.description,
      hashtags: saved.tiktok?.hashtags ?? base.tiktok.hashtags
    },
    vk: { ...base.vk, ...saved.vk, communityUrl: saved.vk?.communityUrl ?? base.vk.communityUrl },
    instagram: { ...base.instagram, ...saved.instagram }
  }
}

export function defaultComposer(): ComposerDraft {
  return {
    videoPath: '',
    coverPath: '',
    title: '',
    description: '',
    hashtags: '',
    enabledPlatforms: [...PLATFORM_IDS],
    overrides: {},
    publishOptions: defaultPublishOptions(),
    scheduleOn: false,
    publishAt: ''
  }
}

export function mergeComposer(saved?: Partial<ComposerDraft>): ComposerDraft {
  const base = defaultComposer()
  if (!saved) return base
  return {
    ...base,
    ...saved,
    enabledPlatforms: Array.isArray(saved.enabledPlatforms) ? saved.enabledPlatforms : base.enabledPlatforms,
    targets: Array.isArray(saved.targets) ? saved.targets.filter((t) => typeof t === 'string') : undefined,
    overrides: saved.overrides ?? {},
    publishOptions: mergePublishOptions(saved.publishOptions),
    hashtags: saved.hashtags ?? ''
  }
}
