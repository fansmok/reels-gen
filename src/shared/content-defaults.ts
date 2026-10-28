import { PLATFORM_IDS, hasVideoTitle } from './platforms'
import type { ComposerDraft, ContentDefaults, PlatformCopy, PlatformId, PlatformOverride } from './types'

export function emptyPlatformCopy(): PlatformCopy {
  return { title: '', description: '', hashtags: '' }
}

export function defaultContentDefaults(): ContentDefaults {
  const platforms = {} as Record<PlatformId, PlatformCopy>
  for (const id of PLATFORM_IDS) {
    platforms[id] = emptyPlatformCopy()
  }
  return { title: '', description: '', hashtags: '', platforms }
}

export function mergeContentDefaults(saved?: Partial<ContentDefaults>): ContentDefaults {
  const base = defaultContentDefaults()
  if (!saved) return base
  const platforms = { ...base.platforms }
  for (const id of PLATFORM_IDS) {
    platforms[id] = {
      title: saved.platforms?.[id]?.title ?? '',
      description: saved.platforms?.[id]?.description ?? '',
      hashtags: saved.platforms?.[id]?.hashtags ?? ''
    }
  }
  return {
    title: saved.title ?? '',
    description: saved.description ?? '',
    hashtags: saved.hashtags ?? '',
    platforms
  }
}

export function textOverridesFromDefaults(
  defaults: ContentDefaults
): Partial<Record<PlatformId, PlatformOverride>> {
  const result: Partial<Record<PlatformId, PlatformOverride>> = {}
  for (const id of PLATFORM_IDS) {
    const copy = defaults.platforms[id]
    if (!copy) continue
    const next: PlatformOverride = {}
    if (copy.title && hasVideoTitle(id)) next.title = copy.title
    if (copy.description) next.description = copy.description
    if (copy.hashtags) next.hashtags = copy.hashtags
    if (next.title || next.description || next.hashtags) result[id] = next
  }
  return result
}

export function mergeOverridesWithDefaults(
  defaults: ContentDefaults,
  overrides: Partial<Record<PlatformId, PlatformOverride>>
): Partial<Record<PlatformId, PlatformOverride>> {
  const base = textOverridesFromDefaults(defaults)
  const result: Partial<Record<PlatformId, PlatformOverride>> = {}
  for (const id of PLATFORM_IDS) {
    const merged: PlatformOverride = { ...base[id], ...overrides[id] }
    if (merged.title || merged.description || merged.hashtags || merged.coverPath) result[id] = merged
  }
  return result
}

export function seedComposerText(
  draft: {
    videoPath: string
    title: string
    description: string
    hashtags?: string
    overrides: Partial<Record<PlatformId, PlatformOverride>>
  },
  defaults: ContentDefaults
): {
  title: string
  description: string
  hashtags: string
  overrides: Partial<Record<PlatformId, PlatformOverride>>
} {
  if (draft.videoPath) {
    return {
      title: draft.title,
      description: draft.description,
      hashtags: draft.hashtags || defaults.hashtags || defaults.platforms.tiktok?.hashtags || '',
      overrides: mergeOverridesWithDefaults(defaults, draft.overrides)
    }
  }
  return {
    title: draft.title || defaults.title,
    description: draft.description || defaults.description,
    hashtags: draft.hashtags || defaults.hashtags || defaults.platforms.tiktok?.hashtags || '',
    overrides: mergeOverridesWithDefaults(defaults, draft.overrides)
  }
}

export function refreshIdleComposer(
  composer: ComposerDraft,
  previous: ContentDefaults,
  next: ContentDefaults
): ComposerDraft {
  const overrides: Partial<Record<PlatformId, PlatformOverride>> = {}
  for (const id of PLATFORM_IDS) {
    const current = composer.overrides[id] ?? {}
    const prevCopy = previous.platforms[id]
    const nextCopy = next.platforms[id]
    const titleStock = !current.title || current.title === (prevCopy?.title ?? '')
    const descStock = !current.description || current.description === (prevCopy?.description ?? '')
    const tagsStock = !current.hashtags || current.hashtags === (prevCopy?.hashtags ?? '')
    const merged: PlatformOverride = {}
    const title = hasVideoTitle(id) ? (titleStock ? nextCopy.title : current.title) : undefined
    const description = descStock ? nextCopy.description : current.description
    const hashtags = tagsStock ? nextCopy.hashtags : current.hashtags
    if (title) merged.title = title
    if (description) merged.description = description
    if (hashtags) merged.hashtags = hashtags
    if (current.coverPath) merged.coverPath = current.coverPath
    if (merged.title || merged.description || merged.hashtags || merged.coverPath) overrides[id] = merged
  }

  return {
    ...composer,
    title: !composer.title || composer.title === previous.title ? next.title : composer.title,
    description:
      !composer.description || composer.description === previous.description ? next.description : composer.description,
    hashtags:
      !composer.hashtags || composer.hashtags === (previous.hashtags || previous.platforms.tiktok?.hashtags || '')
        ? next.hashtags || next.platforms.tiktok?.hashtags || ''
        : composer.hashtags,
    overrides
  }
}
