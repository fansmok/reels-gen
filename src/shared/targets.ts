import { PLATFORM_IDS, getPlatform } from './platforms'
import type { PlatformId, Target, TargetId, YoutubeProfileInfo } from './types'

const PLATFORM_SET = new Set<string>(PLATFORM_IDS)

export function targetId(platform: PlatformId, channelNumber?: number): TargetId {
  return channelNumber ? `${platform}:${channelNumber}` : platform
}

export function parseTargetId(id: TargetId): { platform: PlatformId; channelNumber?: number } | null {
  const [platform, rawNumber] = String(id || '').split(':')
  if (!PLATFORM_SET.has(platform)) return null
  const channelNumber = rawNumber ? Number(rawNumber) : undefined
  if (rawNumber && (!Number.isInteger(channelNumber) || (channelNumber as number) < 1)) return null
  return { platform: platform as PlatformId, channelNumber }
}

export function targetPlatform(id: TargetId): PlatformId | null {
  return parseTargetId(id)?.platform ?? null
}

export function targetLabel(id: TargetId, profiles: YoutubeProfileInfo[] = []): string {
  const parsed = parseTargetId(id)
  if (!parsed) return id
  const meta = getPlatform(parsed.platform)
  if (!parsed.channelNumber) return meta.shortName
  const profile = profiles.find(
    (p) => p.number === parsed.channelNumber && (p.platform ? p.platform === parsed.platform : parsed.platform === 'youtube')
  )
  const name = profile?.name?.trim()
  const numbered = `${meta.shortName} #${parsed.channelNumber}`
  return name && name !== numbered ? `${name} (#${parsed.channelNumber})` : numbered
}

/** Направления заливки: прежний вход площадки и отдельные профили с отпечатком. */
export function buildTargets(
  profiles: Partial<Record<PlatformId, YoutubeProfileInfo[]>>,
  enabled: Record<TargetId, boolean>
): Target[] {
  const flat = PLATFORM_IDS.flatMap((id) => profiles[id] ?? [])
  const result: Target[] = []
  for (const platform of PLATFORM_IDS) {
    if (platform !== 'youtube') {
      const id = targetId(platform)
      const meta = getPlatform(platform)
      result.push({
        id,
        platform,
        label: meta.shortName,
        enabled: enabled[id] ?? false
      })
    }
    for (const profile of profiles[platform] ?? []) {
      const id = targetId(platform, profile.number)
      result.push({
        id,
        platform,
        channelNumber: profile.number,
        label: targetLabel(id, flat),
        enabled: enabled[id] ?? false
      })
    }
  }
  return result
}

export function enabledTargets(
  profiles: Partial<Record<PlatformId, YoutubeProfileInfo[]>>,
  enabled: Record<TargetId, boolean>
): Target[] {
  return buildTargets(profiles, enabled).filter((t) => t.enabled)
}

/** Уникальные площадки по списку направлений, в порядке PLATFORM_IDS. */
export function platformsOfTargets(targets: TargetId[]): PlatformId[] {
  const set = new Set<PlatformId>()
  for (const id of targets) {
    const platform = targetPlatform(id)
    if (platform) set.add(platform)
  }
  return PLATFORM_IDS.filter((p) => set.has(p))
}

/**
 * Сколько разных роликов нужно, чтобы на одной площадке не повторять один и тот же.
 * 3 YouTube, 2 Instagram, 1 Дзен и 1 круг → 3 ролика:
 * первый на YT1+IG1+Дзен, второй на YT2+IG2, третий только на YT3.
 * `rounds` — поле «кругов»: каждый круг снова даёт свой набор роликов.
 */
export function planVariantTargets(targets: TargetId[], rounds = 1): TargetId[][] {
  const groups = new Map<PlatformId, TargetId[]>()
  for (const id of targets) {
    const platform = targetPlatform(id)
    if (!platform) continue
    const list = groups.get(platform) ?? []
    list.push(id)
    groups.set(platform, list)
  }
  const ordered = PLATFORM_IDS.filter((id) => (groups.get(id)?.length ?? 0) > 0)
  if (!ordered.length) return []
  const slots = Math.max(...ordered.map((id) => groups.get(id)!.length))
  const repeat = Math.max(1, Math.floor(rounds) || 1)
  const plan: TargetId[][] = []
  for (let round = 0; round < repeat; round++) {
    for (let index = 0; index < slots; index++) {
      const row: TargetId[] = []
      for (const platform of ordered) {
        const group = groups.get(platform)!
        if (index < group.length) row.push(group[index])
      }
      if (row.length) plan.push(row)
    }
  }
  return plan
}

export function isYoutubeChannelTarget(id: TargetId): boolean {
  const parsed = parseTargetId(id)
  return !!parsed && parsed.platform === 'youtube' && !!parsed.channelNumber
}

/**
 * Раздать пачку роликов по YouTube-каналам без повторов (как `distribute_exclusive` в генераторе):
 * каждый ролик уходит только в один канал, на канал не больше `perChannel` штук.
 * Возвращает для каждого ролика список его направлений: не-YouTube направления остаются у всех.
 */
export function distributeTargets(
  count: number,
  targets: TargetId[],
  options: { distribute: boolean; perChannel: number }
): TargetId[][] {
  const youtube = targets.filter(isYoutubeChannelTarget)
  const rest = targets.filter((t) => !isYoutubeChannelTarget(t))
  const result: TargetId[][] = []
  if (!options.distribute || youtube.length === 0) {
    for (let i = 0; i < count; i++) result.push([...targets])
    return result
  }
  const perChannel = Math.max(1, Math.floor(options.perChannel) || 1)
  const used = new Map<TargetId, number>(youtube.map((t) => [t, 0]))
  let cursor = 0
  for (let i = 0; i < count; i++) {
    let picked: TargetId | undefined
    for (let offset = 0; offset < youtube.length; offset++) {
      const candidate = youtube[(cursor + offset) % youtube.length]
      if ((used.get(candidate) ?? 0) < perChannel) {
        picked = candidate
        used.set(candidate, (used.get(candidate) ?? 0) + 1)
        cursor = (youtube.indexOf(candidate) + 1) % youtube.length
        break
      }
    }
    result.push(picked ? [picked, ...rest] : [...rest])
  }
  return result
}
