import { type JSX } from 'react'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Input } from '@renderer/components/ui/input'
import { Switch } from '@renderer/components/ui/switch'
import { PLATFORMS } from '@shared/platforms'
import type { PlatformId } from '@shared/types'
import {
  DZEN_COMMENT_AUDIENCE_LABELS,
  RUTUBE_CATEGORY_NAMES,
  parseVkCommunityClipsUrl,
  type DzenCommentAudience,
  type PublishOptionsByPlatform,
  type TiktokAudience,
  type YoutubeVisibility
} from '@shared/publish-options'

const selectClass = 'mt-2 h-10 w-full max-w-md rounded-lg border border-input bg-white px-3 text-sm'

function OptionSwitch({
  title,
  hint,
  checked,
  onChange
}: {
  title: string
  hint: string
  checked: boolean
  onChange: (value: boolean) => void
}): JSX.Element {
  return (
    <div className="flex items-start justify-between gap-6 border-t border-border py-3 first:border-t-0 first:pt-0">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{hint}</p>
      </div>
      <Switch className="mt-0.5" checked={checked} onCheckedChange={onChange} />
    </div>
  )
}

function PlatformCard({
  id,
  children
}: {
  id: PlatformId
  children: JSX.Element | JSX.Element[]
}): JSX.Element {
  const meta = PLATFORMS.find((p) => p.id === id)!
  return (
    <section className="rounded-2xl border border-border bg-white p-5">
      <div className="mb-4 flex items-center gap-3">
        <span
          className="flex size-9 items-center justify-center rounded-lg"
          style={{ background: `${meta.color}22`, color: meta.color }}
        >
          <PlatformIcon id={id} className="size-4" />
        </span>
        <div>
          <div className="text-sm font-semibold">{meta.name}</div>
          <div className="text-[11px] text-muted-foreground">Бот проставит эти галочки при загрузке</div>
        </div>
      </div>
      {children}
    </section>
  )
}

export function PublishOptionsEditor({
  options,
  onChange
}: {
  options: PublishOptionsByPlatform
  onChange: (next: PublishOptionsByPlatform) => void
}): JSX.Element {
  return (
    <div className="space-y-4">
      <PlatformCard id="youtube">
        <div className="mb-3">
          <div className="text-sm font-medium">Кто видит ролик</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            «Все» — ролик в поиске и рекомендациях. «По ссылке» — виден только тем, у кого есть ссылка. «Только я» —
            закрытый черновик.
          </p>
          <select
            className={selectClass}
            value={options.youtube.visibility}
            onChange={(e) =>
              onChange({
                ...options,
                youtube: { ...options.youtube, visibility: e.target.value as YoutubeVisibility }
              })
            }
          >
            <option value="public">Все</option>
            <option value="unlisted">По ссылке</option>
            <option value="private">Только я</option>
          </select>
        </div>
        <OptionSwitch
          title="Детский контент"
          hint="Включайте, только если ролик сделан для детей. YouTube тогда ограничит комментарии и часть функций."
          checked={options.youtube.madeForKids}
          onChange={(madeForKids) =>
            onChange({
              ...options,
              youtube: { ...options.youtube, madeForKids, ageRestricted: madeForKids ? false : options.youtube.ageRestricted }
            })
          }
        />
        <OptionSwitch
          title="Только 18+"
          hint="Возрастное ограничение. Нельзя включить вместе с «Детский контент»."
          checked={options.youtube.ageRestricted}
          onChange={(ageRestricted) =>
            onChange({
              ...options,
              youtube: { ...options.youtube, ageRestricted, madeForKids: ageRestricted ? false : options.youtube.madeForKids }
            })
          }
        />
        <OptionSwitch
          title="Платная реклама / спонсорство"
          hint="Если в ролике есть реклама товара, бренда или спонсор — YouTube требует отметить это."
          checked={options.youtube.paidPromotion}
          onChange={(paidPromotion) => onChange({ ...options, youtube: { ...options.youtube, paidPromotion } })}
        />
        <OptionSwitch
          title="Изменённый или ИИ-контент"
          hint="Реалистичные сцены, которые сделаны или изменены нейросетью. Нужно по правилам YouTube."
          checked={options.youtube.alteredContent}
          onChange={(alteredContent) => onChange({ ...options, youtube: { ...options.youtube, alteredContent } })}
        />
        <OptionSwitch
          title="Уведомить подписчиков"
          hint="Отправить ролик в ленту подписок. Обычно оставляют включённым."
          checked={options.youtube.notifySubscribers}
          onChange={(notifySubscribers) =>
            onChange({ ...options, youtube: { ...options.youtube, notifySubscribers } })
          }
        />
      </PlatformCard>

      <PlatformCard id="rutube">
        <div className="mb-3">
          <div className="text-sm font-medium">Категория</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            На Rutube без категории ролик не публикуется. Бот выберет эту тему в форме загрузки.
          </p>
          <select
            className={selectClass}
            value={options.rutube.category || 'Разное'}
            onChange={(e) =>
              onChange({
                ...options,
                rutube: { ...options.rutube, category: e.target.value }
              })
            }
          >
            {RUTUBE_CATEGORY_NAMES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
        <OptionSwitch
          title="Комментарии"
          hint="Разрешить зрителям писать комментарии под роликом."
          checked={options.rutube.comments}
          onChange={(comments) => onChange({ ...options, rutube: { ...options.rutube, comments } })}
        />
        <OptionSwitch
          title="Для взрослых"
          hint="Отметить ролик как 18+. Его не покажут в детском и семейном разделе."
          checked={options.rutube.adult}
          onChange={(adult) => onChange({ ...options, rutube: { ...options.rutube, adult } })}
        />
      </PlatformCard>

      <PlatformCard id="pinterest">
        <div className="mb-3">
          <div className="text-sm font-medium">Ссылка на сайт</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Куда ведёт пин, если человек нажмёт на него. Можно оставить пустым.
          </p>
          <Input
            className="mt-2 h-10 max-w-md text-sm"
            placeholder="https://example.com"
            value={options.pinterest.link}
            onChange={(e) => onChange({ ...options, pinterest: { ...options.pinterest, link: e.target.value } })}
          />
        </div>
        <OptionSwitch
          title="Комментарии"
          hint="Разрешить комментарии к пину."
          checked={options.pinterest.comments}
          onChange={(comments) => onChange({ ...options, pinterest: { ...options.pinterest, comments } })}
        />
        <OptionSwitch
          title="Контент сделан ИИ"
          hint="Pinterest просит отметить, если картинка или видео сгенерированы нейросетью."
          checked={options.pinterest.aiGenerated}
          onChange={(aiGenerated) => onChange({ ...options, pinterest: { ...options.pinterest, aiGenerated } })}
        />
      </PlatformCard>

      <PlatformCard id="dzen">
        <p className="mb-3 text-xs text-muted-foreground">
          Хэштеги Дзен берёт из общего поля «Хэштеги для TikTok и Дзена». Бот вводит каждый тег и нажимает Enter.
        </p>
        <div className="mb-3">
          <div className="text-sm font-medium">Заголовок раздела комментариев</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Название блока комментариев под роликом. Пустое поле — оставить стандартное «Комментарии». Не больше 70
            символов.
          </p>
          <Input
            className="mt-2 h-10 max-w-md text-sm"
            placeholder="Комментарии"
            maxLength={70}
            value={options.dzen.commentsTitle}
            onChange={(e) =>
              onChange({ ...options, dzen: { ...options.dzen, commentsTitle: e.target.value.slice(0, 70) } })
            }
          />
        </div>
        <div>
          <div className="text-sm font-medium">Кто может комментировать</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Как в студии Дзена: все пользователи, только подписчики или никто.
          </p>
          <select
            className={selectClass}
            value={options.dzen.commentAudience}
            onChange={(e) =>
              onChange({
                ...options,
                dzen: { ...options.dzen, commentAudience: e.target.value as DzenCommentAudience }
              })
            }
          >
            {(Object.keys(DZEN_COMMENT_AUDIENCE_LABELS) as DzenCommentAudience[]).map((id) => (
              <option key={id} value={id}>
                {DZEN_COMMENT_AUDIENCE_LABELS[id]}
              </option>
            ))}
          </select>
        </div>
      </PlatformCard>

      <PlatformCard id="tiktok">
        <div className="mb-3">
          <div className="text-sm font-medium">Кто может смотреть</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            «Все» — ролик открытый. «Друзья» — только взаимные подписки. «Только я» — черновик для себя.
          </p>
          <select
            className={selectClass}
            value={options.tiktok.audience}
            onChange={(e) =>
              onChange({
                ...options,
                tiktok: { ...options.tiktok, audience: e.target.value as TiktokAudience }
              })
            }
          >
            <option value="everyone">Все</option>
            <option value="friends">Друзья</option>
            <option value="only_me">Только я</option>
          </select>
        </div>
        <OptionSwitch
          title="Комментарии"
          hint="Разрешить комментарии под роликом."
          checked={options.tiktok.comments}
          onChange={(comments) => onChange({ ...options, tiktok: { ...options.tiktok, comments } })}
        />
        <OptionSwitch
          title="Можно переиспользовать"
          hint="Другие авторы смогут делать дуэт и стич с вашим роликом."
          checked={options.tiktok.allowReuse}
          onChange={(allowReuse) => onChange({ ...options, tiktok: { ...options.tiktok, allowReuse } })}
        />
      </PlatformCard>

      <PlatformCard id="vk">
        <div className="mb-3">
          <div className="text-sm font-medium">Сообщество</div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Ссылка на сообщество, например https://vk.ru/clips/club240633418 или https://vk.ru/club240633418.
            Если поле пустое — клип публикуется в профиле пользователя.
          </p>
          <Input
            className="mt-2 h-10 max-w-md text-sm"
            placeholder="https://vk.ru/clips/club240633418"
            value={options.vk.communityUrl ?? ''}
            onChange={(e) => onChange({ ...options, vk: { ...options.vk, communityUrl: e.target.value } })}
          />
          {(options.vk.communityUrl ?? '').trim() ? (
            <p className="mt-1 text-[11px] text-muted-foreground">
              {parseVkCommunityClipsUrl(options.vk.communityUrl)
                ? `Бот откроет ${parseVkCommunityClipsUrl(options.vk.communityUrl)}`
                : 'Ссылку не разобрал. Вставьте адрес сообщества или оставьте поле пустым.'}
            </p>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">Сейчас: публикация в профиле, https://vk.ru/clips</p>
          )}
        </div>
        <OptionSwitch
          title="Комментарии"
          hint="Разрешить комментарии к клипу."
          checked={options.vk.comments}
          onChange={(comments) => onChange({ ...options, vk: { ...options.vk, comments } })}
        />
        <OptionSwitch
          title="Показать на стене"
          hint={
            options.vk.communityUrl?.trim()
              ? 'Клип появится в записях на стене сообщества.'
              : 'Клип появится в записях на вашей стене ВКонтакте.'
          }
          checked={options.vk.wallPost}
          onChange={(wallPost) => onChange({ ...options, vk: { ...options.vk, wallPost } })}
        />
        <OptionSwitch
          title="Дуэты"
          hint="Другие смогут снимать дуэт поверх вашего клипа."
          checked={options.vk.duets}
          onChange={(duets) => onChange({ ...options, vk: { ...options.vk, duets } })}
        />
        <OptionSwitch
          title="Опубликовать в истории"
          hint="Дополнительно отправить клип в истории. Обычно оставляют выключенным."
          checked={options.vk.publishStory}
          onChange={(publishStory) => onChange({ ...options, vk: { ...options.vk, publishStory } })}
        />
      </PlatformCard>

      <PlatformCard id="instagram">
        <OptionSwitch
          title="Показать в ленте"
          hint="В веб-версии рилс и так попадает в ленту профиля. Отдельного тумблера Instagram больше не показывает — бот попробует включить его, если он вдруг появится."
          checked={options.instagram.shareToFeed}
          onChange={(shareToFeed) => onChange({ ...options, instagram: { ...options.instagram, shareToFeed } })}
        />
        <OptionSwitch
          title="Комментарии"
          hint="Разрешить комментарии к рилсу."
          checked={options.instagram.comments}
          onChange={(comments) => onChange({ ...options, instagram: { ...options.instagram, comments } })}
        />
      </PlatformCard>
    </div>
  )
}
