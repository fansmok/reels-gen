import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type JSX } from 'react'
import { Button } from '@renderer/components/ui/button'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { cn } from '@renderer/lib/utils'
import { StepCta } from '@renderer/components/generator/StepCta'
import { StepDesign } from '@renderer/components/generator/StepDesign'
import { StepRun } from '@renderer/components/generator/StepRun'
import { StepSource } from '@renderer/components/generator/StepSource'
import { StepText } from '@renderer/components/generator/StepText'
import { STEP_TITLES, type GeneratorInfo, type GeneratorRun, type GeneratorSettings } from '@shared/generator'
import type { AppState } from '@shared/types'

const STEP_HINTS = ['верх, низ, количество', 'слоган, QR, стикер', 'пауза-баннер, обложка', 'Whisper, Kie, хэштеги', 'направления и старт']

export function GeneratorPage({ state }: { state: AppState }): JSX.Element {
  const [s, setS] = useState<GeneratorSettings>(state.generator)
  const [info, setInfo] = useState<GeneratorInfo | null>(null)
  const [run, setRun] = useState<GeneratorRun>(state.generatorRun)
  const pending = useRef<Partial<GeneratorSettings>>({})
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    const patch = pending.current
    pending.current = {}
    if (Object.keys(patch).length) void window.api.saveGenerator(patch)
  }, [])

  const set = useCallback(
    (patch: Partial<GeneratorSettings>) => {
      setS((prev) => ({ ...prev, ...patch }))
      pending.current = { ...pending.current, ...patch }
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(flush, 400)
    },
    [flush]
  )

  const reloadInfo = useCallback(() => {
    if (!state.engine.ok) return
    void window.api.generatorInfo().then(setInfo).catch(() => undefined)
  }, [state.engine.ok])

  useEffect(() => {
    reloadInfo()
  }, [reloadInfo])

  useEffect(() => {
    const off = window.api.onGeneratorRun(setRun)
    return () => {
      off()
      flush()
    }
  }, [flush])

  useEffect(() => {
    setRun(state.generatorRun)
  }, [state.generatorRun])

  // отметки запусков автоматизации ведёт main — подтягиваем, чтобы не затереть их локальными правками
  const { lastRun, lastTopSig } = state.generator.auto
  useEffect(() => {
    setS((prev) => (prev.auto.lastRun === lastRun && prev.auto.lastTopSig === lastTopSig ? prev : { ...prev, auto: { ...prev.auto, lastRun, lastTopSig } }))
  }, [lastRun, lastTopSig])

  const step = s.step
  const goto = (next: number): void => set({ step: Math.max(0, Math.min(STEP_TITLES.length - 1, next)) })
  const props = { s, set, info, state, run, reloadInfo }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 py-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Генератор рилсов</h1>
            <p className="text-sm text-muted-foreground">Верх + низ + призыв → готовые ролики с обложками и текстами → очередь на все площадки.</p>
          </div>
          {run.running && (
            <div className="flex items-center gap-2 rounded-full bg-violet-50 px-3 py-1.5 text-xs text-violet-800">
              <span className="size-2 animate-pulse rounded-full bg-violet-600" />
              {run.task} · {Math.round(run.progress * 100)}%
            </div>
          )}
        </div>
        <nav className="mt-4 grid grid-cols-5 gap-2">
          {STEP_TITLES.map((title, index) => {
            const active = index === step
            const done = index < step
            return (
              <button
                key={title}
                type="button"
                onClick={() => goto(index)}
                className={cn(
                  'flex items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition-colors',
                  active ? 'border-violet-400 bg-violet-50' : done ? 'border-emerald-200 bg-emerald-50/50 hover:bg-emerald-50' : 'border-border bg-white hover:bg-muted/50'
                )}
              >
                <span
                  className={cn(
                    'flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                    active ? 'bg-violet-600 text-white' : done ? 'bg-emerald-600 text-white' : 'bg-muted text-muted-foreground'
                  )}
                >
                  {index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-xs font-medium">{title}</span>
                  <span className="block truncate text-[10px] text-muted-foreground">{STEP_HINTS[index]}</span>
                </span>
              </button>
            )
          })}
        </nav>
      </header>
      <ScrollArea className="flex-1">
        <div className="px-8 py-6">
          {step === 0 && <StepSource {...props} />}
          {step === 1 && <StepCta {...props} />}
          {step === 2 && <StepDesign {...props} />}
          {step === 3 && <StepText {...props} />}
          {step === 4 && <StepRun {...props} />}
        </div>
      </ScrollArea>
      <footer className="flex items-center justify-between border-t border-border px-8 py-3">
        <Button variant="outline" disabled={step === 0} onClick={() => goto(step - 1)}>
          <ChevronLeft className="size-4" /> Назад
        </Button>
        <span className="text-xs text-muted-foreground">
          Шаг {step + 1} из {STEP_TITLES.length} · настройки сохраняются сами
        </span>
        <Button disabled={step === STEP_TITLES.length - 1} onClick={() => goto(step + 1)}>
          Дальше <ChevronRight className="size-4" />
        </Button>
      </footer>
    </div>
  )
}
