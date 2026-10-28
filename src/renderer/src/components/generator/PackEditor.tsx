import type { JSX } from 'react'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Input } from '@renderer/components/ui/input'
import { Textarea } from '@renderer/components/ui/textarea'
import { PLATFORM_TEXT_LIMITS, type KiePack } from '@shared/kie-pack'
import { PLATFORMS } from '@shared/platforms'
import type { PlatformId, PlatformOverride } from '@shared/types'

/** Правка текстов под площадки из Kie-пакета одного ролика. */
export function PackEditor({ pack, platforms, onChange }: { pack: KiePack; platforms: PlatformId[]; onChange: (next: KiePack) => void }): JSX.Element {
  const list = PLATFORMS.filter((p) => platforms.includes(p.id) && pack[p.id])
  if (list.length === 0) return <p className="text-xs text-muted-foreground">Для выбранных площадок текстов нет</p>

  function update(id: PlatformId, patch: Partial<PlatformOverride>): void {
    onChange({ ...pack, [id]: { ...pack[id], ...patch } })
  }

  return (
    <div className="space-y-3">
      {list.map((platform) => {
        const v = pack[platform.id] ?? {}
        const lim = PLATFORM_TEXT_LIMITS[platform.id]
        return (
          <div key={platform.id} className="rounded-lg border border-border bg-white p-3">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium">
              <span className="flex size-6 items-center justify-center rounded-md" style={{ background: `${platform.color}22`, color: platform.color }}>
                <PlatformIcon id={platform.id} className="size-3.5" />
              </span>
              {platform.shortName}
              <span className="ml-auto text-[10px] font-normal text-muted-foreground">
                {(v.description ?? '').length}/{lim.description}
              </span>
            </div>
            <div className="space-y-2">
              {lim.title > 0 && (
                <Input className="h-8 text-xs" maxLength={lim.title} value={v.title ?? ''} placeholder="Заголовок" onChange={(e) => update(platform.id, { title: e.target.value })} />
              )}
              <Textarea className="min-h-16 text-xs" maxLength={lim.description} value={v.description ?? ''} placeholder="Описание" onChange={(e) => update(platform.id, { description: e.target.value })} />
              <Input className="h-8 text-xs" value={v.hashtags ?? ''} placeholder={`до ${lim.hashtags} хэштегов`} spellCheck={false} onChange={(e) => update(platform.id, { hashtags: e.target.value })} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
