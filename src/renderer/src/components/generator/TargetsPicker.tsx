import type { JSX } from 'react'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Checkbox } from '@renderer/components/ui/checkbox'
import { cn } from '@renderer/lib/utils'
import { PLATFORMS } from '@shared/platforms'
import { targetId } from '@shared/targets'
import type { AppState, TargetId } from '@shared/types'

/**
 * Выбор направлений: площадки + конкретные YouTube-каналы.
 * `custom` — пользователь переопределил галочки «грузить сюда» из «Аккаунтов».
 */
export function TargetsPicker({
  state,
  targets,
  custom,
  onChange,
  onReset
}: {
  state: AppState
  targets: TargetId[]
  custom: boolean
  onChange: (targets: TargetId[]) => void
  onReset: () => void
}): JSX.Element {
  function toggle(id: TargetId): void {
    onChange(targets.includes(id) ? targets.filter((x) => x !== id) : [...targets, id])
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-sm font-medium">Куда отправить готовые ролики</span>
        {custom && (
          <button type="button" className="text-[11px] text-violet-700 hover:underline" onClick={onReset}>
            как в «Аккаунтах»
          </button>
        )}
      </div>
      <p className="mb-3 text-[11px] text-muted-foreground">
        По умолчанию — галочки «грузить сюда» из «Аккаунтов». Раздача по каналам YouTube — по настройке «без повторов».
      </p>
      <div className="space-y-2">
        {PLATFORMS.map((platform) => {
          const profiles = state.platformProfiles[platform.id] ?? []
          const legacyId = platform.id === 'youtube' ? null : targetId(platform.id)
          const channelIds = [...(legacyId ? [legacyId] : []), ...profiles.map((p) => targetId(platform.id, p.number))]
          const pickedCount = channelIds.filter((id) => targets.includes(id)).length
          const on = pickedCount > 0
          return (
            <div key={platform.id} className="rounded-xl border border-border bg-white p-3">
              <div className="flex items-center gap-3">
                <Checkbox
                  checked={channelIds.length > 0 && channelIds.every((id) => targets.includes(id)) ? true : on ? 'indeterminate' : false}
                  disabled={channelIds.length === 0}
                  onCheckedChange={() => {
                    const all = channelIds.every((id) => targets.includes(id))
                    const rest = targets.filter((id) => !channelIds.includes(id))
                    onChange(all ? rest : [...rest, ...channelIds])
                  }}
                />
                <span className="flex size-8 items-center justify-center rounded-lg" style={{ background: `${platform.color}22`, color: platform.color }}>
                  <PlatformIcon id={platform.id} className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{platform.shortName}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {channelIds.length === 0
                      ? 'аккаунтов нет — добавьте в «Аккаунтах»'
                      : `аккаунтов: ${pickedCount}/${channelIds.length}`}
                  </div>
                </div>
              </div>
              {channelIds.length > 0 && (
                <div className="mt-2 grid grid-cols-2 gap-1.5 pl-11">
                  {legacyId && (
                    <label className="flex cursor-pointer items-center gap-2 text-xs">
                      <Checkbox checked={targets.includes(legacyId)} onCheckedChange={() => toggle(legacyId)} />
                      <span className={cn('truncate', targets.includes(legacyId) ? 'text-foreground' : 'text-muted-foreground')}>
                        Прежний аккаунт
                      </span>
                    </label>
                  )}
                  {profiles.map((profile) => {
                    const id = targetId(platform.id, profile.number)
                    const checked = targets.includes(id)
                    return (
                      <label key={id} className="flex cursor-pointer items-center gap-2 text-xs">
                        <Checkbox checked={checked} onCheckedChange={() => toggle(id)} />
                        <span className={cn('truncate', checked ? 'text-foreground' : 'text-muted-foreground')} title={profile.path}>
                          {profile.name} <span className="opacity-60">#{profile.number}</span>
                        </span>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
