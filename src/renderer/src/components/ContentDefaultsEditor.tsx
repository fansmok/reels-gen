import { type JSX } from 'react'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Input } from '@renderer/components/ui/input'
import { Label } from '@renderer/components/ui/label'
import { Textarea } from '@renderer/components/ui/textarea'
import { PLATFORMS, hasVideoTitle } from '@shared/platforms'
import { TIKTOK_CAPTION_MAX, TIKTOK_HASHTAG_MAX, parseTiktokHashtags } from '@shared/publish-options'
import type { ContentDefaults, PlatformId } from '@shared/types'

export function ContentDefaultsEditor({
  value,
  onChange
}: {
  value: ContentDefaults
  onChange: (next: ContentDefaults) => void
}): JSX.Element {
  function patchPlatform(id: PlatformId, field: 'title' | 'description' | 'hashtags', text: string): void {
    onChange({
      ...value,
      platforms: {
        ...value.platforms,
        [id]: { ...value.platforms[id], [field]: text }
      }
    })
  }

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-border bg-white p-5">
        <div className="mb-4">
          <div className="text-sm font-semibold">Общий текст</div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Подставляется в каждый новый ролик. Название можно оставить пустым — тогда возьмётся имя файла.
            Хэштеги нужны TikTok и Дзену: одни и те же, до пяти штук. В Дзене бот вводит тег и нажимает Enter.
          </p>
        </div>
        <div className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="defaults-title">Название</Label>
            <Input
              id="defaults-title"
              value={value.title}
              onChange={(e) => onChange({ ...value, title: e.target.value })}
              placeholder="Необязательно. Иначе имя файла ролика"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="defaults-desc">Описание</Label>
            <Textarea
              id="defaults-desc"
              className="min-h-32"
              value={value.description}
              onChange={(e) => onChange({ ...value, description: e.target.value })}
              placeholder="О себе, ссылки — этот текст уйдёт на площадки"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="defaults-hashtags">Хэштеги для TikTok и Дзена</Label>
            <Input
              id="defaults-hashtags"
              value={value.hashtags}
              onChange={(e) => onChange({ ...value, hashtags: e.target.value })}
              placeholder="свет, интерьер, обзор"
            />
            <p className="text-[11px] text-muted-foreground">
              До {TIKTOK_HASHTAG_MAX} через запятую. Одни и те же теги уйдут в TikTok и в Дзен.{' '}
              {parseTiktokHashtags(value.hashtags).length}/{TIKTOK_HASHTAG_MAX}
            </p>
          </div>
        </div>
      </section>

      {PLATFORMS.map((platform) => (
        <section key={platform.id} className="rounded-2xl border border-border bg-white p-5">
          <div className="mb-4 flex items-center gap-3">
            <span
              className="flex size-9 items-center justify-center rounded-lg"
              style={{ background: `${platform.color}22`, color: platform.color }}
            >
              <PlatformIcon id={platform.id} className="size-4" />
            </span>
            <div>
              <div className="text-sm font-semibold">{platform.name}</div>
              <div className="text-[11px] text-muted-foreground">
                {platform.id === 'tiktok'
                  ? `В TikTok нет названия. Описание до ${TIKTOK_CAPTION_MAX} символов. Хэштеги — общие, в блоке выше.`
                  : platform.id === 'vk'
                    ? 'В VK нет названия — только описание клипа. Сообщество указывается ниже, в блоке публикации.'
                    : platform.id === 'dzen'
                      ? 'В Дзене нет названия — только описание. Хэштеги те же, что для TikTok: бот введёт каждый и нажмёт Enter.'
                      : platform.id === 'instagram'
                        ? 'В Instagram нет названия — только описание рилса.'
                        : 'Если поля пустые — бот возьмёт общий текст выше'}
              </div>
            </div>
          </div>
          {platform.id === 'tiktok' ? (
            <div className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="defaults-desc-tiktok">Описание</Label>
                <Textarea
                  id="defaults-desc-tiktok"
                  className="min-h-36"
                  maxLength={TIKTOK_CAPTION_MAX}
                  value={value.platforms.tiktok?.description ?? ''}
                  onChange={(e) =>
                    patchPlatform('tiktok', 'description', e.target.value.slice(0, TIKTOK_CAPTION_MAX))
                  }
                  placeholder="Длинное описание только для TikTok"
                />
                <p className="text-[11px] text-muted-foreground">
                  {(value.platforms.tiktok?.description ?? '').length}/{TIKTOK_CAPTION_MAX}
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {hasVideoTitle(platform.id) && (
                <div className="space-y-2">
                  <Label htmlFor={`defaults-title-${platform.id}`}>Название для {platform.shortName}</Label>
                  <Input
                    id={`defaults-title-${platform.id}`}
                    value={value.platforms[platform.id]?.title ?? ''}
                    onChange={(e) => patchPlatform(platform.id, 'title', e.target.value)}
                    placeholder={`Как общее, если не заполнять`}
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor={`defaults-desc-${platform.id}`}>Описание для {platform.shortName}</Label>
                <Textarea
                  id={`defaults-desc-${platform.id}`}
                  className="min-h-24"
                  value={value.platforms[platform.id]?.description ?? ''}
                  onChange={(e) => patchPlatform(platform.id, 'description', e.target.value)}
                  placeholder="Свои упоминания или ссылка только для этой площадки"
                />
              </div>
            </div>
          )}
        </section>
      ))}
    </div>
  )
}
