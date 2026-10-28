import { useState, type JSX } from 'react'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Switch } from '@renderer/components/ui/switch'
import { Textarea } from '@renderer/components/ui/textarea'
import { fileName } from '@renderer/lib/utils'
import type { GeneratorBanner, GeneratorCover } from '@shared/generator'
import { Field, NativeSelect, PreviewBox, Row, type StepProps } from './common'

export function StepDesign({ s, set, info, run }: StepProps): JSX.Element {
  const [bannerPreview, setBannerPreview] = useState<{ image: string; note: string }>({ image: '', note: '' })
  const [coverPreview, setCoverPreview] = useState<{ image: string; note: string }>({ image: '', note: '' })
  const [busy, setBusy] = useState<'banner' | 'cover' | null>(null)

  const banner = (patch: Partial<GeneratorBanner>): void => set({ banner: { ...s.banner, ...patch } })
  const cover = (patch: Partial<GeneratorCover>): void => set({ cover: { ...s.cover, ...patch } })

  async function previewBanner(): Promise<void> {
    setBusy('banner')
    try {
      const res = await window.api.generatorPreviewBanner(s)
      setBannerPreview({ image: res.image, note: `«${res.text}» · пауза на ${res.pauseAt} с` })
    } catch {
      /* тост из main */
    } finally {
      setBusy(null)
    }
  }

  async function previewCover(): Promise<void> {
    setBusy('cover')
    try {
      const res = await window.api.generatorPreviewCover(s)
      if (res.disabled) setCoverPreview({ image: '', note: 'Обложка отключена' })
      else setCoverPreview({ image: res.image, note: `${res.video ? fileName(res.video) : 'плейсхолдер'}\n«${res.phrase}»` })
    } catch {
      /* тост из main */
    } finally {
      setBusy(null)
    }
  }

  async function pickAudio(): Promise<void> {
    const picked = await window.api.pickFile('Аудио для баннера', [{ name: 'Аудио', extensions: ['mp3', 'wav', 'm4a', 'ogg', 'aac'] }])
    if (picked) banner({ audio: picked })
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        <Card className="space-y-4 p-5">
          <Row title="Баннер «ПОДПИШИСЬ» с паузой" hint="Видео замирает, поверх — анимированная плашка. Второй баннер можно поставить в конец.">
            <Switch checked={s.banner.enabled} onCheckedChange={(v) => banner({ enabled: v })} />
          </Row>
          {s.banner.enabled && (
            <div className="space-y-3">
              <Field label="Текст баннера">
                <Textarea className="min-h-16" value={s.banner.text} onChange={(e) => banner({ text: e.target.value })} />
              </Field>
              <div className="grid gap-3 md:grid-cols-3">
                <Field label="Стиль">
                  <NativeSelect value={s.banner.style} onChange={(e) => banner({ style: e.target.value })}>
                    <option value="random">Случайный</option>
                    {(info?.bannerStyles ?? []).map((st) => (
                      <option key={st.id} value={st.id}>
                        {st.title}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field label="Длительность, с" hint="С аудио — по длине дорожки">
                  <Input type="number" min={1} max={20} step={0.5} value={s.banner.duration} onChange={(e) => banner({ duration: Math.max(1, Math.min(20, Number(e.target.value) || 4)) })} />
                </Field>
                <Field label="Где показывать">
                  <NativeSelect value={s.banner.place} onChange={(e) => banner({ place: e.target.value as GeneratorBanner['place'] })}>
                    <option value="mid">На паузе (10 с, иначе за 3 с до конца)</option>
                    <option value="end">В конце ролика</option>
                    <option value="both">И на паузе, и в конце</option>
                  </NativeSelect>
                </Field>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Источник (подпись мелким)" hint="Например, @канал — откуда ролик">
                  <Input value={s.banner.source} spellCheck={false} onChange={(e) => banner({ source: e.target.value })} />
                </Field>
                <Field label="Аудио на баннер" hint="Озвучка поверх паузы (ElevenLabs и т.п.)">
                  <div className="flex gap-2">
                    <Button variant="outline" className="min-w-0 flex-1 justify-start truncate" onClick={() => void pickAudio()}>
                      {s.banner.audio ? fileName(s.banner.audio) : 'Выбрать файл'}
                    </Button>
                    {s.banner.audio && (
                      <Button variant="ghost" onClick={() => banner({ audio: '' })}>
                        ×
                      </Button>
                    )}
                  </div>
                </Field>
              </div>
              <label className="flex items-center gap-2 text-xs">
                <Switch checked={s.banner.dropBottom} onCheckedChange={(v) => banner({ dropBottom: v })} /> после паузы оставить только верхний ролик (без нижнего)
              </label>
            </div>
          )}
        </Card>
        <Card className="h-fit space-y-3 p-4">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">Превью баннера</div>
            <Button size="sm" variant="outline" disabled={busy !== null || run.running || !s.banner.enabled} onClick={() => void previewBanner()}>
              {busy === 'banner' ? 'Рисую…' : 'Обновить'}
            </Button>
          </div>
          <PreviewBox path={bannerPreview.image} note={bannerPreview.note} empty={s.banner.enabled ? 'Нажмите «Обновить»' : 'Баннер выключен'} ratio="aspect-[9/8]" />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
        <Card className="space-y-4 p-5">
          <Row title="Обложка ролика" hint="Кадр из ролика + крупный текст. Уходит на все площадки, где есть обложка.">
            <Switch checked={s.cover.enabled} onCheckedChange={(v) => cover({ enabled: v })} />
          </Row>
          {s.cover.enabled && (
            <div className="space-y-3">
              <div className="grid gap-3 md:grid-cols-3">
                <Field label="Кадр берём из">
                  <NativeSelect value={s.cover.source} onChange={(e) => cover({ source: e.target.value as GeneratorCover['source'] })}>
                    <option value="bottom">нижнего ролика (уникально на каждый)</option>
                    <option value="top">верхнего ролика</option>
                    <option value="split">две части: верх — видео 1, низ — видео 2</option>
                  </NativeSelect>
                </Field>
                <Field label="Текст">
                  <NativeSelect value={s.cover.position} onChange={(e) => cover({ position: e.target.value as GeneratorCover['position'] })}>
                    <option value="bottom">снизу</option>
                    <option value="center">по центру</option>
                    <option value="top">сверху</option>
                  </NativeSelect>
                </Field>
                <Field label="Что писать">
                  <NativeSelect value={s.cover.textSource} onChange={(e) => cover({ textSource: e.target.value as GeneratorCover['textSource'] })}>
                    <option value="titles">заголовок ролика</option>
                    <option value="templates">заготовки из списка ниже</option>
                  </NativeSelect>
                </Field>
              </div>
              <div className="grid gap-3 md:grid-cols-4">
                <Field label="Цвет текста">
                  <Input type="color" className="h-10 p-1" value={s.cover.textColor} onChange={(e) => cover({ textColor: e.target.value.toUpperCase() })} />
                </Field>
                <Field label="Цвет обводки">
                  <Input type="color" className="h-10 p-1" value={s.cover.strokeColor} onChange={(e) => cover({ strokeColor: e.target.value.toUpperCase() })} />
                </Field>
                <Field label="Обводка, px">
                  <Input type="number" min={0} max={30} value={s.cover.strokeWidth} onChange={(e) => cover({ strokeWidth: Math.max(0, Math.min(30, Number(e.target.value) || 0)) })} />
                </Field>
                <Field label="Шрифт, px" hint="0 — авто">
                  <Input type="number" min={0} max={200} value={s.cover.fontSize} onChange={(e) => cover({ fontSize: Math.max(0, Math.min(200, Number(e.target.value) || 0)) })} />
                </Field>
              </div>
              <label className="flex items-center gap-2 text-xs">
                <Switch checked={s.cover.uppercase} onCheckedChange={(v) => cover({ uppercase: v })} /> ЗАГЛАВНЫМИ
              </label>
              {s.cover.textSource === 'templates' && (
                <Field label="Заготовки текста (по одной в строке)" hint={info ? `Пусто — стандартные: «${info.defaultCoverPhrases[0]}»…` : undefined}>
                  <Textarea className="min-h-20" value={s.cover.phrases} onChange={(e) => cover({ phrases: e.target.value })} />
                </Field>
              )}
            </div>
          )}
        </Card>
        <Card className="h-fit space-y-3 p-4">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">Превью обложки</div>
            <Button size="sm" variant="outline" disabled={busy !== null || run.running || !s.cover.enabled} onClick={() => void previewCover()}>
              {busy === 'cover' ? 'Рисую…' : 'Обновить'}
            </Button>
          </div>
          <PreviewBox path={coverPreview.image} note={coverPreview.note} empty={s.cover.enabled ? 'Нажмите «Обновить»' : 'Обложка выключена'} />
        </Card>
      </div>
    </div>
  )
}
