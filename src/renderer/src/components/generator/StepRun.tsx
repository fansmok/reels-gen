import { ChevronDown, Clapperboard, ListPlus, Sparkles, Square } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type JSX } from 'react'
import { toast } from 'sonner'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { Checkbox } from '@renderer/components/ui/checkbox'
import { cn, fileName } from '@renderer/lib/utils'
import type { GeneratedItem, GenerateResult } from '@shared/generator'
import type { KiePack } from '@shared/kie-pack'
import { enabledTargets, planVariantTargets, platformsOfTargets } from '@shared/targets'
import type { TargetId } from '@shared/types'
import { AutomationCard } from './AutomationCard'
import { LocalImage, formatBytes, type StepProps } from './common'
import { PackEditor } from './PackEditor'
import { TargetsPicker } from './TargetsPicker'

export function StepRun(props: StepProps): JSX.Element {
  const { s, set, info, state, run, reloadInfo } = props
  const [picked, setPicked] = useState<TargetId[] | null>(null)
  const accountTargets = useMemo(
    () => enabledTargets(state.platformProfiles, state.targets).map((t) => t.id),
    [state.platformProfiles, state.targets]
  )
  const targets = picked ?? accountTargets
  const platforms = useMemo(() => platformsOfTargets(targets), [targets])
  const variantCount = useMemo(() => planVariantTargets(targets, 1).length, [targets])
  const [readyFiles, setReadyFiles] = useState<string[]>([])
  const [showReady, setShowReady] = useState(false)
  const [items, setItems] = useState<GeneratedItem[]>(run.result ?? [])
  const [openPack, setOpenPack] = useState<string | null>(null)
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setItems(run.result ?? [])
  }, [run.result])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [run.log.length])

  async function packAll(): Promise<void> {
    if (!items.length) return
    try {
      // без выбранных направлений — тексты под все площадки
      const packed = await window.api.generatorPack(items, s, platforms)
      setItems(packed)
    } catch {
      /* тост из main */
    }
  }

  function updatePack(uid: string, pack: KiePack): void {
    setItems((prev) => prev.map((it) => ((it.uid || it.video) === uid ? { ...it, pack } : it)))
  }

  const tops = info?.tops ?? []

  function applyResult(result: GenerateResult): void {
    const patch: Parameters<typeof set>[0] = {}
    if (result.linkedPath) patch.linkedPath = result.linkedPath
    if (result.linkedKey) patch.linkedKey = result.linkedKey
    if (result.kieTitles?.length) {
      patch.kieTitles = result.kieTitles
      patch.kieTitlesChecked = result.kieTitles
    }
    if (result.phrases?.length && !result.kieTitles?.length) {
      patch.phrases = result.phrases
      patch.phrasesChecked = result.phrases
    }
    if (result.titleBase) patch.titleBase = result.titleBase
    if (result.transcript) {
      patch.transcript = result.transcript
      patch.transcriptVideo = result.transcriptVideo || ''
      if (result.description?.trim()) patch.descManual = result.description
    } else if (s.useKieTitles && !s.useCustomMeta && result.items[0]?.description) {
      patch.descManual = result.items[0].description
    }
    if (result.hashtags && !s.hashtags) patch.hashtags = result.hashtags
    if (Object.keys(patch).length) set(patch)
    reloadInfo()
  }

  async function generate(toQueue: boolean, files?: string[]): Promise<void> {
    if (toQueue && targets.length === 0) {
      toast.error('Отметьте, куда отправлять ролики')
      return
    }
    if (!files?.length && targets.length === 0) {
      toast.error('Отметьте аккаунты — число роликов берётся из них')
      return
    }
    const settings = { ...s, count: Math.max(1, variantCount) }
    try {
      if (toQueue) {
        const out = await window.api.generatorGenerateToQueue(settings, targets, files)
        applyResult(out.result)
      } else {
        const result = await window.api.generatorGenerate(settings, files)
        applyResult(result)
      }
    } catch {
      /* ошибка показана тостом из main */
    }
  }

  async function sendToQueue(list: GeneratedItem[]): Promise<void> {
    if (targets.length === 0) {
      toast.error('Отметьте, куда отправлять ролики')
      return
    }
    await window.api.generatorToQueue(list, targets)
  }

  const busy = run.running

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <div className="space-y-4">
        <Card className="space-y-4 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">Запуск</div>
              <p className="text-xs text-muted-foreground">
                Роликов по аккаунтам: {variantCount || '—'} · верх: {s.topMode === 'all' ? `все из папки 1 (${tops.length})` : s.topMode === 'telegram' ? 'Telegram' : 'один'} · низ:{' '}
                {s.sourceMode === 'telegram' ? 'Telegram' : s.sourceMode === 'instagram' ? 'Instagram' : `папка 2 (${info?.bottoms.length ?? 0})`}
                {s.autoWhisper && !s.useCustomMeta && s.topMode !== 'link' && s.topMode !== 'telegram' ? ` · Whisper ${s.asrModel}` : ''}
                {s.useKieTitles && !s.useCustomMeta ? ' · Kie' : ''}
                {s.banner.enabled ? ' · баннер' : ''}
                {s.cover.enabled ? ' · обложки' : ''}
              </p>
            </div>
            {busy ? (
              <Button variant="destructive" onClick={() => void window.api.generatorCancel()}>
                <Square className="size-4" /> Остановить
              </Button>
            ) : (
              <div className="flex gap-2">
                <Button variant="outline" disabled={!state.engine.ok} onClick={() => void generate(false)}>
                  <Clapperboard className="size-4" /> Сгенерировать
                </Button>
                <Button disabled={!state.engine.ok || targets.length === 0} onClick={() => void generate(true)}>
                  <ListPlus className="size-4" /> Сгенерировать и загрузить
                </Button>
              </div>
            )}
          </div>
          {!state.engine.ok && <p className="text-xs text-destructive">{state.engine.problems[0] ?? 'Движок не подключён — проверьте пути в «Настройках»'}</p>}

          {(busy || run.log.length > 0) && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs">
                <span className={cn('font-medium', run.error ? 'text-destructive' : busy ? 'text-violet-700' : 'text-emerald-700')}>
                  {busy ? `Идёт: ${run.task}` : run.error ? `Ошибка: ${run.error}` : 'Готово'}
                </span>
                <span className="tabular-nums text-muted-foreground">{Math.round(run.progress * 100)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div className={cn('h-full rounded-full transition-all', run.error ? 'bg-destructive' : 'bg-violet-600')} style={{ width: `${Math.max(2, run.progress * 100)}%` }} />
              </div>
              <div ref={logRef} className="max-h-56 overflow-auto rounded-lg border border-border bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-zinc-200">
                {run.log.slice(-200).map((line, i) => (
                  <div key={i} className="whitespace-pre-wrap break-words">
                    {line}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>

        <AutomationCard {...props} />

        {items.length > 0 && (
          <Card className="space-y-3 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-semibold">Готовые ролики: {items.length}</div>
                <p className="text-xs text-muted-foreground">
                  Видео, обложка и тексты лежат в upload_queue движка.
                  {s.kiePack ? ' При «Сгенерировать и в очередь» тексты под площадки Kie делает сам.' : ''}
                </p>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void packAll()}>
                  <Sparkles className="size-4" /> Kie: тексты под площадки
                </Button>
                <Button size="sm" disabled={busy || targets.length === 0} onClick={() => void sendToQueue(items)}>
                  <ListPlus className="size-4" /> Все в очередь
                </Button>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {items.map((item) => {
                const key = item.uid || item.video
                const open = openPack === key
                return (
                  <div key={key} className={cn('rounded-xl border bg-white p-3', open ? 'border-violet-200 md:col-span-2' : 'border-border')}>
                    <div className="flex gap-3">
                      <div className="h-28 w-16 shrink-0 overflow-hidden rounded-lg bg-zinc-100">
                        {item.cover ? <LocalImage path={item.cover} className="h-full w-full object-cover" /> : null}
                      </div>
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="line-clamp-2 text-sm font-medium" title={item.title}>
                          {item.title || fileName(item.video)}
                        </div>
                        <div className="line-clamp-3 text-[11px] text-muted-foreground" title={item.description}>
                          {item.description}
                        </div>
                        {item.hashtags && <div className="truncate text-[11px] text-violet-700">{item.hashtags}</div>}
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <Button size="sm" variant="ghost" className="px-2" onClick={() => void window.api.openPath(item.video)}>
                            Открыть
                          </Button>
                          <Button size="sm" variant="outline" className="px-2" disabled={busy || targets.length === 0} onClick={() => void sendToQueue([item])}>
                            В очередь
                          </Button>
                          {item.pack && (
                            <Button size="sm" variant="ghost" className="gap-1 px-2" onClick={() => setOpenPack(open ? null : key)}>
                              <span className={cn('rounded px-1.5 py-0.5 text-[10px]', item.packSource === 'kie' ? 'bg-violet-100 text-violet-800' : 'bg-amber-100 text-amber-800')}>
                                {item.packSource === 'kie' ? 'Kie' : 'локально'}
                              </span>
                              тексты по площадкам
                              <ChevronDown className={cn('size-3.5 transition', open && 'rotate-180')} />
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                    {open && item.pack && (
                      <div className="mt-3 border-t border-border pt-3">
                        <PackEditor pack={item.pack} platforms={platforms.length ? platforms : (Object.keys(item.pack) as typeof platforms)} onChange={(next) => updatePack(key, next)} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        <Card className="space-y-3 p-5">
          <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setShowReady((v) => !v)}>
            <div>
              <div className="text-sm font-semibold">Уже готовые ролики из output ({info?.outputs.length ?? 0})</div>
              <p className="text-xs text-muted-foreground">Подготовить обложки и тексты для уже сгенерированных файлов и отправить в очередь без новой генерации.</p>
            </div>
            <span className="text-xs text-muted-foreground">{showReady ? 'свернуть' : 'показать'}</span>
          </button>
          {showReady && (
            <div className="space-y-3">
              <div className="max-h-64 space-y-1 overflow-auto">
                {(info?.outputs ?? []).map((f) => {
                  const on = readyFiles.includes(f.path)
                  return (
                    <label key={f.path} className="flex cursor-pointer items-center gap-2 rounded-lg border border-border px-2.5 py-1.5 text-xs hover:bg-muted/40">
                      <Checkbox checked={on} onCheckedChange={() => setReadyFiles(on ? readyFiles.filter((x) => x !== f.path) : [...readyFiles, f.path])} />
                      <span className="min-w-0 flex-1 truncate" title={f.path}>
                        {f.name}
                      </span>
                      <span className="text-muted-foreground">{formatBytes(f.size)}</span>
                    </label>
                  )
                })}
                {(info?.outputs.length ?? 0) === 0 && <p className="text-xs text-muted-foreground">В output пока пусто</p>}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={busy || readyFiles.length === 0} onClick={() => void generate(false, readyFiles)}>
                  Подготовить выбранные ({readyFiles.length})
                </Button>
                <Button size="sm" disabled={busy || readyFiles.length === 0 || targets.length === 0} onClick={() => void generate(true, readyFiles)}>
                  Подготовить и в очередь
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    const files = await window.api.pickFiles('Готовые ролики', [{ name: 'Видео', extensions: ['mp4', 'mov', 'webm', 'mkv', 'm4v'] }])
                    if (files.length) setReadyFiles([...new Set([...readyFiles, ...files])])
                  }}
                >
                  Добавить файлы…
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>

      <Card className="h-fit p-4">
        <TargetsPicker state={state} targets={targets} custom={picked !== null} onChange={setPicked} onReset={() => setPicked(null)} />
      </Card>
    </div>
  )
}
