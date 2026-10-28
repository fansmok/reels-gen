import { useState, type JSX } from 'react'
import { toast } from 'sonner'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Switch } from '@renderer/components/ui/switch'
import { Textarea } from '@renderer/components/ui/textarea'
import { fileName } from '@renderer/lib/utils'
import { DEFAULT_STICKER_PACK, type StickerPackInfo } from '@shared/generator'
import { Field, LocalImage, NativeSelect, PreviewBox, Row, type StepProps } from './common'

export function StepCta({ s, set, info, run }: StepProps): JSX.Element {
  const [preview, setPreview] = useState<{ image: string; note: string }>({ image: '', note: '' })
  const [pack, setPack] = useState<StickerPackInfo | null>(null)
  const [loadingPack, setLoadingPack] = useState(false)
  const [rendering, setRendering] = useState(false)

  async function doPreview(): Promise<void> {
    setRendering(true)
    try {
      const res = await window.api.generatorPreviewCta(s)
      setPreview({ image: res.image, note: `«${res.slogan}»\n${res.tgCall}` })
    } catch {
      /* тост из main */
    } finally {
      setRendering(false)
    }
  }

  async function loadPack(force = false): Promise<void> {
    setLoadingPack(true)
    try {
      const res = await window.api.generatorStickers(s, force)
      setPack(res)
      toast.success(`Пак «${res.title}»: ${res.count} стикеров`)
    } catch {
      /* тост из main */
    } finally {
      setLoadingPack(false)
    }
  }

  async function pickQr(): Promise<void> {
    const picked = await window.api.pickFile('QR-код (картинка)', [{ name: 'Изображения', extensions: ['png', 'jpg', 'jpeg', 'webp'] }])
    if (picked) set({ qrFile: picked })
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
      <div className="space-y-4">
        <Card className="space-y-4 p-5">
          <Row title="Экран призыва в конце ролика" hint="Слоган, QR и подпись «в Telegram». Выключено — ролик заканчивается без этой вставки.">
            <Switch checked={s.ctaEnabled} onCheckedChange={(v) => set({ ctaEnabled: v })} />
          </Row>
          {s.ctaEnabled && (
          <>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Слоганы (по одному в строке)" hint={info ? `Пусто — возьмём из файла или стандартные: «${info.defaultSlogans[0]}»…` : undefined}>
              <Textarea className="min-h-24" value={s.slogans} onChange={(e) => set({ slogans: e.target.value })} />
              <label className="flex items-center gap-2 text-xs">
                <Switch checked={s.randSlogan} onCheckedChange={(v) => set({ randSlogan: v })} /> случайный слоган на каждый ролик
              </label>
            </Field>
            <Field label="Подпись к Telegram (по одной в строке)" hint={info ? `Пусто — стандартные: «${info.defaultTgCalls[0]}»…` : undefined}>
              <Textarea className="min-h-24" value={s.tgCalls} onChange={(e) => set({ tgCalls: e.target.value })} />
              <label className="flex items-center gap-2 text-xs">
                <Switch checked={s.randTg} onCheckedChange={(v) => set({ randTg: v })} /> случайная подпись
              </label>
            </Field>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Стиль экрана">
              <NativeSelect value={s.randStyle ? 'random' : s.ctaStyle} onChange={(e) => set(e.target.value === 'random' ? { randStyle: true, ctaStyle: 'random' } : { randStyle: false, ctaStyle: e.target.value })}>
                <option value="random">Случайный</option>
                {(info?.ctaStyles ?? []).map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.title}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field label="Длительность, с">
              <Input type="number" min={1} max={15} step={0.5} value={s.ctaSec} onChange={(e) => set({ ctaSec: Math.max(1, Math.min(15, Number(e.target.value) || 5)) })} />
            </Field>
          </div>
          </>
          )}
        </Card>

        {s.ctaEnabled && (
        <Card className="space-y-4 p-5">
          <Row title="QR-код и ссылка" hint="Текст ссылки показывается под QR. Можно загрузить свою картинку QR." />
          <div className="grid gap-3 md:grid-cols-[1fr_auto]">
            <Field label="Ссылка (например, на Telegram)">
              <Input value={s.qr} spellCheck={false} placeholder="https://t.me/…" onChange={(e) => set({ qr: e.target.value })} />
            </Field>
            <Field label="Своя картинка QR">
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => void pickQr()}>
                  {s.qrFile ? fileName(s.qrFile) : 'Выбрать'}
                </Button>
                {s.qrFile && (
                  <Button variant="ghost" onClick={() => set({ qrFile: '' })}>
                    ×
                  </Button>
                )}
              </div>
            </Field>
          </div>
        </Card>
        )}

        {s.ctaEnabled && (
        <Card className="space-y-4 p-5">
          <Row title="Стикер Telegram на экране CTA" hint="Анимированный стикер из пака — живее, чем смайлы">
            <Switch checked={s.stickerEnabled} onCheckedChange={(v) => set({ stickerEnabled: v })} />
          </Row>
          {s.stickerEnabled && (
            <div className="space-y-3">
              <div className="flex items-end gap-2">
                <Field label="Ссылка на пак" className="flex-1">
                  <Input value={s.stickerUrl} spellCheck={false} placeholder={DEFAULT_STICKER_PACK} onChange={(e) => set({ stickerUrl: e.target.value })} />
                </Field>
                <Button variant="outline" disabled={loadingPack || run.running} onClick={() => void loadPack(false)}>
                  {loadingPack ? 'Загружаю…' : 'Загрузить пак'}
                </Button>
              </div>
              <Field label="Какой стикер" hint={pack ? `«${pack.title}» · ${pack.count} шт.` : 'Загрузите пак, чтобы выбрать конкретный — иначе случайный'}>
                <NativeSelect value={s.stickerSelection} onChange={(e) => set({ stickerSelection: e.target.value })}>
                  <option value="random">Случайный</option>
                  {(pack?.stickers ?? []).map((st) => (
                    <option key={st.index} value={String(st.index)}>
                      {st.label}
                    </option>
                  ))}
                  {!pack && s.stickerSelection !== 'random' && <option value={s.stickerSelection}>№ {Number(s.stickerSelection) + 1}</option>}
                </NativeSelect>
              </Field>
              {pack && (
                <div className="flex flex-wrap gap-1.5">
                  {pack.stickers.slice(0, 40).map((st) => (
                    <button
                      key={st.index}
                      type="button"
                      title={st.label}
                      onClick={() => set({ stickerSelection: String(st.index) })}
                      className={`size-12 overflow-hidden rounded-lg border ${s.stickerSelection === String(st.index) ? 'border-violet-500 ring-2 ring-violet-200' : 'border-border'}`}
                    >
                      {st.thumb ? <LocalImage path={st.thumb} className="h-full w-full object-contain" /> : <span className="text-lg">{st.emoji}</span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
        )}
      </div>

      <Card className="h-fit space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div className="text-sm font-semibold">Превью CTA</div>
          <Button size="sm" variant="outline" disabled={rendering || run.running || !s.ctaEnabled} onClick={() => void doPreview()}>
            {rendering ? 'Рисую…' : 'Обновить'}
          </Button>
        </div>
        <PreviewBox path={preview.image} note={preview.note} empty={s.ctaEnabled ? 'Нажмите «Обновить»' : 'Призыв выключен'} ratio="aspect-[9/8]" />
      </Card>
    </div>
  )
}
