import { FolderOpen, RefreshCw } from 'lucide-react'
import { useState, type JSX } from 'react'
import { toast } from 'sonner'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Textarea } from '@renderer/components/ui/textarea'
import { CAPTION_FONTS, CAPTION_PRESETS, CIRCLE_PLACES, DEFAULT_TITLE_THEME, type CaptionStyle, type SourceMode, type TopMode } from '@shared/generator'
import { TelegramCard } from './TelegramCard'
import { Switch } from '@renderer/components/ui/switch'
import { Field, NativeSelect, RadioCard, Row, formatBytes, type StepProps } from './common'

const TOP_MODES: { id: TopMode; title: string; hint: string }[] = [
  { id: 'latest', title: 'Самый новый из папки 1', hint: 'Берём последний добавленный ролик' },
  { id: 'single', title: 'Выбрать один', hint: 'Конкретный файл из папки 1' },
  { id: 'random_one', title: 'Случайный', hint: 'Любой ролик из папки 1' },
  { id: 'all', title: 'Все из папки 1', hint: 'Верхние по очереди. Сколько роликов — решают аккаунты' },
  { id: 'link', title: 'По ссылке', hint: 'YouTube Shorts или Instagram Reels' },
  { id: 'telegram', title: 'Загрузка через Telegram', hint: 'Ссылка или видео в бота. Бот слушает, только пока выбран этот пункт' }
]

export function StepSource({ s, set, info, state, run, reloadInfo }: StepProps): JSX.Element {
  const [linking, setLinking] = useState(false)
  const tops = info?.tops ?? []
  const bottoms = info?.bottoms ?? []

  function pickTop(id: TopMode): void {
    const patch: Parameters<typeof set>[0] = { topMode: id }
    if (id === 'telegram') patch.tg = { ...s.tg, enabled: true }
    else if (s.sourceMode !== 'telegram') patch.tg = { ...s.tg, enabled: false }
    set(patch)
  }

  function look(patch: Partial<CaptionStyle>): void {
    set({ captionStyle: { ...s.captionStyle, ...patch } })
  }

  function pickBottom(id: SourceMode): void {
    const patch: Parameters<typeof set>[0] = { sourceMode: id }
    if (id === 'telegram') patch.tg = { ...s.tg, enabled: true }
    else if (s.topMode !== 'telegram') patch.tg = { ...s.tg, enabled: false }
    set(patch)
  }

  async function fetchLink(): Promise<void> {
    if (!s.topUrl.trim()) {
      toast.error('Вставьте ссылку на ролик')
      return
    }
    setLinking(true)
    try {
      const res = await window.api.generatorLinkTop(s)
      const titles = res.titles.map((t) => t.toUpperCase())
      set({
        linkedPath: res.path,
        linkedKey: res.key,
        kieTitles: titles,
        kieTitlesChecked: titles,
        titleBase: titles[0] ?? s.titleBase,
        hashtags: res.tags || s.hashtags,
        useKieTitles: titles.length > 0 ? true : s.useKieTitles,
        transcript: '',
        transcriptVideo: ''
      })
      toast.success(titles.length ? `Ролик скачан, заголовок: ${titles[0]}` : 'Ролик скачан')
      reloadInfo()
    } catch {
      /* ошибка уже показана тостом из main */
    } finally {
      setLinking(false)
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div className="space-y-4">
        <Card className="space-y-4 p-5">
          <div>
            <div className="text-sm font-semibold">Верхний ролик</div>
            <p className="text-xs text-muted-foreground">Основное видео сверху. Папка 1: {info?.folder1 ?? '…'}</p>
          </div>
          <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
            {TOP_MODES.map((m) => (
              <RadioCard key={m.id} active={s.topMode === m.id} title={m.title} hint={m.hint} onClick={() => pickTop(m.id)} />
            ))}
          </div>
          {s.topMode === 'single' && (
            <Field label="Файл из папки 1">
              <NativeSelect
                value={s.topFile}
                onChange={(e) => {
                  const topFile = e.target.value
                  set(s.transcriptVideo && topFile !== s.transcriptVideo ? { topFile, transcript: '', transcriptVideo: '' } : { topFile })
                }}
              >
                <option value="">— выберите —</option>
                {tops.map((f) => (
                  <option key={f.path} value={f.path}>
                    {f.name} · {formatBytes(f.size)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          )}
          {s.topMode === 'telegram' && (
            <p className="rounded-xl border border-violet-100 bg-violet-50/40 p-3 text-[11px] text-muted-foreground">
              Пользователь присылает боту ссылку на YouTube или Instagram либо само видео. Если у нижнего ролика тоже выбрана загрузка через Telegram, следом он присылает низ: ссылку, видео или кружок.
            </p>
          )}
          {s.topMode === 'link' && (
            <div className="space-y-3 rounded-xl border border-violet-100 bg-violet-50/40 p-3">
              <Field label="Ссылка на ролик" hint="Скачается в папку 1, Kie придумает русский заголовок по названию и теме">
                <Input value={s.topUrl} spellCheck={false} placeholder="https://www.youtube.com/shorts/…" onChange={(e) => set({ topUrl: e.target.value, linkedPath: '', linkedKey: '', transcript: '', transcriptVideo: '' })} />
              </Field>
              <div className="flex items-end gap-2">
                <Field label="Тема для заголовка" className="flex-1">
                  <Input value={s.titleTheme} placeholder={DEFAULT_TITLE_THEME} onChange={(e) => set({ titleTheme: e.target.value })} />
                </Field>
                <Button variant="outline" disabled={linking || run.running} onClick={() => void fetchLink()}>
                  {linking ? 'Скачиваю…' : 'Скачать и придумать заголовок'}
                </Button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {s.linkedPath
                  ? `Готово: ${s.linkedPath.split(/[\\/]/).pop()} · при запуске повторно качать не будем`
                  : 'Можно не нажимать — при запуске ролик скачается сам'}
              </p>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            Сколько роликов соберётся, зависит от отмеченных аккаунтов: берётся площадка, где их больше всего. 4 Instagram,
            2 Rutube и 3 YouTube — это 4 разных ролика.
          </p>
        </Card>

        <Card className="space-y-4 p-5">
          <div>
            <div className="text-sm font-semibold">Нижний ролик</div>
            <p className="text-xs text-muted-foreground">Второй экран снизу, с него берётся обложка. Папка 2: {info?.folder2 ?? '…'}</p>
          </div>
          <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
            <RadioCard active={s.sourceMode === 'folder'} title={`Папка 2 (${bottoms.length})`} hint="Уже скачанные ролики, без повторов" onClick={() => pickBottom('folder')} />
            <RadioCard active={s.sourceMode === 'instagram'} title="Instagram" hint="Скачать свежие рилсы с аккаунтов" onClick={() => pickBottom('instagram')} />
            <RadioCard active={s.sourceMode === 'telegram'} title="Загрузка через Telegram" hint="Ссылка, видео или кружок после верхнего ролика" onClick={() => pickBottom('telegram')} />
          </div>
          {s.sourceMode === 'telegram' && (
            <p className="rounded-xl border border-violet-100 bg-violet-50/40 p-3 text-[11px] text-muted-foreground">
              Сначала бот ждёт верхний рилс: ссылку или видео. Потом нижний: ссылку, файл или кружок. После этого ролики склеиваются и заливаются по всем остальным настройкам.
            </p>
          )}
          {s.sourceMode === 'instagram' && (
            <Field label="Аккаунты Instagram" hint="По одному в строке: @username или ссылка на профиль/рилс. Куки берутся из Opera.">
              <Textarea className="min-h-20" value={s.instagram} spellCheck={false} onChange={(e) => set({ instagram: e.target.value })} placeholder="@iamritafaez" />
            </Field>
          )}
        </Card>

        <Card className="space-y-3 p-5">
          <div>
            <div className="text-sm font-semibold">Звук</div>
            <p className="text-xs text-muted-foreground">
              У нижнего ролика берётся своя дорожка. Ползунок смещает громкость: влево — больше верх, вправо — больше низ.
            </p>
          </div>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>Верх</span>
            <span className="font-medium text-foreground">
              {s.audioMix <= 0 ? 'только верх' : s.audioMix >= 100 ? 'только низ' : `верх ${100 - s.audioMix}% · низ ${s.audioMix}%`}
            </span>
            <span>Низ</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={s.audioMix}
            aria-label="Смещение звука между верхним и нижним роликом"
            className="w-full accent-violet-600"
            onChange={(e) => set({ audioMix: Number(e.target.value) })}
          />
        </Card>

        <Card className="space-y-4 p-5">
          <Row
            title="Кружок внизу"
            hint="Нижнее видео кругом, около 20% высоты кадра. Верхнее занимает весь экран."
          >
            <Switch checked={s.bottomCircle} onCheckedChange={(v) => set({ bottomCircle: v })} />
          </Row>
          {s.bottomCircle && (
            <div className="grid grid-cols-4 gap-2">
              {CIRCLE_PLACES.map((place) => (
                <button
                  key={place.id}
                  type="button"
                  onClick={() => set({ circlePlace: place.id })}
                  className={
                    s.circlePlace === place.id
                      ? 'rounded-lg border border-violet-400 bg-violet-50 px-2 py-2 text-sm font-medium'
                      : 'rounded-lg border border-border bg-white px-2 py-2 text-sm'
                  }
                >
                  {place.title}
                </button>
              ))}
            </div>
          )}
          <Row
            title="Субтитры"
            hint="Анимация по словам. Текст берётся из речи нижнего ролика, если звук смещён к нему."
          >
            <Switch checked={s.captions} onCheckedChange={(v) => set({ captions: v })} />
          </Row>
          {s.captions && (
            <div className="space-y-3 border-t border-border pt-3">
              <div className="grid grid-cols-2 gap-2">
                {CAPTION_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => look({ preset: preset.id })}
                    className={
                      s.captionStyle.preset === preset.id
                        ? 'rounded-lg border border-violet-400 bg-violet-50 px-2 py-2 text-left'
                        : 'rounded-lg border border-border bg-white px-2 py-2 text-left'
                    }
                  >
                    <div className="text-sm font-medium">{preset.title}</div>
                    <div className="text-[11px] text-muted-foreground">{preset.hint}</div>
                  </button>
                ))}
              </div>
              <Field label="Шрифт">
                <NativeSelect value={s.captionStyle.font} onChange={(e) => look({ font: e.target.value })}>
                  {CAPTION_FONTS.map((font) => (
                    <option key={font.id} value={font.id}>
                      {font.label}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Размер" hint={`${s.captionStyle.fontSize} px`}>
                <input
                  type="range"
                  min={48}
                  max={140}
                  step={2}
                  value={s.captionStyle.fontSize}
                  aria-label="Размер субтитров"
                  className="w-full accent-violet-600"
                  onChange={(e) => look({ fontSize: Number(e.target.value) })}
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Цвет текста">
                  <Input type="color" className="h-10 p-1" value={s.captionStyle.color} onChange={(e) => look({ color: e.target.value.toUpperCase() })} />
                </Field>
                <Field label="Цвет активного слова">
                  <Input type="color" className="h-10 p-1" value={s.captionStyle.activeColor} onChange={(e) => look({ activeColor: e.target.value.toUpperCase() })} />
                </Field>
              </div>
              <Row title="Заглавные буквы">
                <Switch checked={s.captionStyle.uppercase} onCheckedChange={(v) => look({ uppercase: v })} />
              </Row>
            </div>
          )}
        </Card>

        <TelegramCard s={s} set={set} info={info} state={state} run={run} reloadInfo={reloadInfo} />
      </div>

      <Card className="h-fit space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold">Папки движка</div>
          <Button variant="ghost" size="sm" onClick={reloadInfo} title="Обновить списки">
            <RefreshCw className="size-3.5" />
          </Button>
        </div>
        {(
          [
            ['Папка 1 — верх', info?.folder1, tops.length],
            ['Папка 2 — низ', info?.folder2, bottoms.length],
            ['Output — готовые', info?.output, info?.outputs.length ?? 0]
          ] as const
        ).map(([label, path, count]) => (
          <div key={label} className="flex items-center justify-between gap-2 rounded-lg border border-border px-3 py-2">
            <div className="min-w-0">
              <div className="text-xs font-medium">{label}</div>
              <div className="text-[11px] text-muted-foreground">файлов: {count}</div>
            </div>
            <Button variant="outline" size="sm" disabled={!path} onClick={() => path && void window.api.openPath(path)}>
              <FolderOpen className="size-3.5" />
            </Button>
          </div>
        ))}
        {info && !info.ffmpeg && <p className="text-xs text-destructive">FFmpeg не найден в PATH — генерация не запустится.</p>}
        <div className="text-[11px] text-muted-foreground">
          {tops.slice(0, 6).map((f) => (
            <div key={f.path} className="truncate" title={f.path}>
              • {f.name}
            </div>
          ))}
          {tops.length > 6 && <div>… и ещё {tops.length - 6}</div>}
        </div>
      </Card>
    </div>
  )
}
