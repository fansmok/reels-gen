import { Mic, Sparkles } from 'lucide-react'
import { useState, type JSX } from 'react'
import { toast } from 'sonner'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Input } from '@renderer/components/ui/input'
import { Switch } from '@renderer/components/ui/switch'
import { Textarea } from '@renderer/components/ui/textarea'
import { ASR_MODELS, type AsrModel } from '@shared/generator'
import { Field, NativeSelect, RadioCard, Row, linesOf, type StepProps } from './common'

type TextMode = 'kie' | 'own' | 'list'

function modeOf(useKie: boolean, custom: boolean): TextMode {
  if (custom) return 'list'
  if (useKie) return 'kie'
  return 'own'
}

export function StepText({ s, set, run, state }: StepProps): JSX.Element {
  const [busy, setBusy] = useState<'asr' | 'kie' | null>(null)
  const mode = modeOf(s.useKieTitles, s.useCustomMeta)
  const disabled = busy !== null || run.running
  const hasKey = Boolean(state.settings.kieApiKey)

  function choose(next: TextMode): void {
    if (next === 'kie') set({ useKieTitles: true, useCustomMeta: false })
    else if (next === 'list') set({ useKieTitles: false, useCustomMeta: true })
    else set({ useKieTitles: false, useCustomMeta: false })
  }

  async function transcribe(): Promise<void> {
    setBusy('asr')
    try {
      const res = await window.api.generatorTranscribe(s, false)
      set({
        transcript: res.text,
        transcriptVideo: res.video,
        phrases: res.phrases,
        phrasesChecked: res.phrases,
        titleBase: s.titleBase || res.phrases[0] || ''
      })
      toast.success(res.text.trim() ? 'Речь распознана' : 'Речь не разобрана — впишите текст сами')
    } catch {
      /* тост из main */
    } finally {
      setBusy(null)
    }
  }

  async function kie(): Promise<void> {
    if (!s.transcript.trim()) {
      toast.error('Сначала нужен текст ролика — распознайте речь или вставьте его')
      return
    }
    setBusy('kie')
    try {
      const res = await window.api.generatorKieTitles(s)
      const titles = res.titles.map((t) => t.toUpperCase())
      set({ kieTitles: titles, kieTitlesChecked: titles, useKieTitles: true, titleBase: titles[0] ?? s.titleBase })
      toast.success(`Заголовков: ${titles.length}`)
    } catch {
      /* тост из main */
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card className="space-y-3 p-5">
        <div>
          <div className="text-sm font-semibold">Откуда брать название</div>
          <p className="text-xs text-muted-foreground">Один вариант на все ролики этой пачки. Лишнее можно не трогать.</p>
        </div>
        <div className="grid gap-2 md:grid-cols-3">
          <RadioCard active={mode === 'kie'} title="Kie по речи" hint="Нейросеть придумает заголовки по тексту ролика" onClick={() => choose('kie')} />
          <RadioCard active={mode === 'own'} title="Свой заголовок" hint="Одно название и одно описание на все ролики" onClick={() => choose('own')} />
          <RadioCard active={mode === 'list'} title="Свой список" hint="Несколько названий по кругу, без нейросети" onClick={() => choose('list')} />
        </div>
      </Card>

      {mode === 'kie' && (
        <Card className="space-y-4 p-5">
          <Row title="Текст ролика" hint="По нему Kie пишет заголовок. Можно вставить готовый текст или распознать речь.">
            <Switch checked={s.autoWhisper} onCheckedChange={(v) => set({ autoWhisper: v })} />
          </Row>
          <p className="text-[11px] text-muted-foreground">
            Переключатель — распознавать речь автоматически при каждом запуске. Кнопка ниже делает это сразу.
            {!hasKey && ' Свой ключ Kie задаётся в «Настройках».'}
          </p>
          <div className="flex items-end gap-2">
            <Field label="Точность распознавания" className="flex-1">
              <NativeSelect value={s.asrModel} onChange={(e) => set({ asrModel: e.target.value as AsrModel })}>
                {ASR_MODELS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Button variant="outline" disabled={disabled} onClick={() => void transcribe()}>
              <Mic className="size-4" />
              {busy === 'asr' ? 'Слушаю…' : 'Распознать'}
            </Button>
          </div>
          <Textarea
            className="min-h-28 text-xs"
            placeholder="Текст, который говорят в ролике"
            value={s.transcript}
            onChange={(e) => set({ transcript: e.target.value, transcriptVideo: '' })}
          />
          <Button variant="outline" disabled={disabled || !s.transcript.trim()} onClick={() => void kie()}>
            <Sparkles className="size-4" />
            {busy === 'kie' ? 'Думаю…' : 'Придумать заголовки'}
          </Button>
          <Field label="Заголовки — по одному в строке" hint="Каждый следующий ролик берёт следующую строку. Пусто — Kie придумает при запуске.">
            <Textarea
              className="min-h-24 text-xs"
              placeholder="ПРОЩАЛЬНЫЙ МАТЧ ЛЕО МЕССИ"
              value={s.kieTitles.join('\n')}
              onChange={(e) => {
                const titles = linesOf(e.target.value).map((t) => t.toUpperCase())
                set({ kieTitles: titles, kieTitlesChecked: titles, titleBase: titles[0] || '' })
              }}
            />
          </Field>
        </Card>
      )}

      {mode === 'list' && (
        <Card className="space-y-3 p-5">
          <Field label="Заголовки по кругу" hint="Первый ролик — первая строка, второй — вторая, потом сначала.">
            <Textarea className="min-h-24 text-xs" value={s.customTitles.join('\n')} onChange={(e) => set({ customTitles: linesOf(e.target.value) })} />
          </Field>
          <Field label="Описания по кругу" hint="Между описаниями — пустая строка.">
            <Textarea
              className="min-h-28 text-xs"
              value={s.customDescriptions.join('\n\n')}
              onChange={(e) =>
                set({
                  customDescriptions: e.target.value
                    .split(/\n\s*\n/)
                    .map((x) => x.trim())
                    .filter(Boolean)
                })
              }
            />
          </Field>
        </Card>
      )}

      <Card className="space-y-4 p-5">
        <div>
          <div className="text-sm font-semibold">{mode === 'own' ? 'Название и описание' : 'Описание и хэштеги'}</div>
          <p className="text-xs text-muted-foreground">
            {mode === 'kie'
              ? 'Описание и хэштеги — основа. Перед загрузкой Kie подгонит их под каждую площадку, куда реально уйдёт этот ролик.'
              : 'Это текст, который уйдёт на площадки, если пакет Kie выключен.'}
          </p>
        </div>
        {mode === 'own' && (
          <Field label="Заголовок">
            <Input value={s.titleBase} placeholder="ПРОЩАЛЬНЫЙ МАТЧ ЛЕО МЕССИ ЗА СБОРНУЮ" onChange={(e) => set({ titleBase: e.target.value })} />
          </Field>
        )}
        <Field label="Описание">
          <Textarea className="min-h-24" value={s.descManual} onChange={(e) => set({ descManual: e.target.value })} />
        </Field>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Хэштеги" hint="#футбол #гол">
            <Input value={s.hashtags} spellCheck={false} onChange={(e) => set({ hashtags: e.target.value })} />
          </Field>
          <Field label="Хэштеги на все ролики" hint="Добавляются всегда">
            <Input value={s.permanentHashtags} spellCheck={false} onChange={(e) => set({ permanentHashtags: e.target.value })} />
          </Field>
        </div>
        <div className="border-t border-border pt-3">
          <Row
            title="Подписи отдельно для каждой площадки"
            hint="Kie пишет текст только туда, куда уйдёт конкретный ролик. На три YouTube и один Дзен у первого ролика будут оба текста, у остальных — только YouTube."
          >
            <Switch checked={s.kiePack} onCheckedChange={(v) => set({ kiePack: v })} />
          </Row>
        </div>
      </Card>

      <details className="rounded-xl border border-border bg-white px-5 py-3 text-sm">
        <summary className="cursor-pointer font-medium">Дополнительно: триггер в заголовке</summary>
        <p className="mt-2 text-xs text-muted-foreground">
          Добавляется к названию, только если выключены и Kie, и свой список. Пусто — стандартные фразы вроде «смотри до конца».
        </p>
        <Textarea className="mt-2 min-h-16 text-xs" value={s.triggers.join('\n')} onChange={(e) => set({ triggers: linesOf(e.target.value) })} />
      </details>
    </div>
  )
}
