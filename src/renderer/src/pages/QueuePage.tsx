import { Pause, Play, RefreshCw, RotateCcw, Square, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState, type JSX } from 'react'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Badge } from '@renderer/components/ui/badge'
import { Button } from '@renderer/components/ui/button'
import { Card } from '@renderer/components/ui/card'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { fileName, formatDate } from '@renderer/lib/utils'
import { getPlatform } from '@shared/platforms'
import { targetLabel, targetPlatform } from '@shared/targets'
import type { AppState, JobStatus, PlatformJobStatus, VideoJob, YoutubeProfileInfo } from '@shared/types'

const statusLabel: Record<PlatformJobStatus, string> = {
  pending: 'ждёт',
  uploading: 'загрузка',
  done: 'готово',
  error: 'ошибка',
  skipped: 'пропуск'
}

const jobStatusLabel: Record<JobStatus, string> = {
  queued: 'в очереди',
  waiting: 'ожидает время',
  uploading: 'загрузка',
  done: 'готово',
  error: 'есть ошибки',
  partial: 'частично',
  paused: 'пауза'
}

const statusClass: Record<PlatformJobStatus, string> = {
  pending: 'bg-zinc-100 text-zinc-600 border-zinc-200',
  uploading: 'bg-violet-50 text-violet-700 border-violet-200',
  done: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  skipped: 'bg-zinc-50 text-zinc-500 border-zinc-200'
}

export function QueuePage({ state }: { state: AppState }): JSX.Element {
  const queued = state.jobs.filter(
    (j) => j.status === 'queued' || j.status === 'waiting' || j.status === 'uploading' || j.status === 'paused'
  )
  const done = state.jobs.filter((j) => j.status === 'done' || j.status === 'error' || j.status === 'partial')

  return (
    <div className="flex h-full flex-col">
      <header className="relative z-20 flex items-center justify-between border-b border-border bg-background px-8 py-5">
        <div>
          <h1 className="text-xl font-semibold">Очередь загрузки</h1>
          <p className="text-sm text-muted-foreground">Ролик за роликом, площадка за площадкой</p>
        </div>
        <div className="relative z-20 flex gap-2">
          {state.runner === 'running' || state.runner === 'waiting' ? (
            <Button variant="secondary" onClick={() => void window.api.pauseQueue()}>
              <Pause /> Пауза
            </Button>
          ) : (
            <Button onClick={() => void window.api.startQueue()}>
              <Play /> {state.runner === 'paused' ? 'Продолжить' : 'Старт'}
            </Button>
          )}
          <Button
            variant="outline"
            disabled={state.runner === 'idle'}
            onClick={() => void window.api.stopQueue()}
          >
            <Square /> Стоп
          </Button>
        </div>
      </header>
      <ScrollArea className="flex-1">
        <div className="space-y-6 px-8 py-6">
          {!state.chromeAvailable && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {state.chromeMessage ?? 'Установите Google Chrome — без него бот не сможет открыть площадки.'}
            </div>
          )}
          {state.jobs.length === 0 && (
            <Card className="flex flex-col items-center gap-3 py-16 text-center">
              <div className="text-4xl">🎬</div>
              <div className="text-lg font-medium">Очередь пуста</div>
              <p className="max-w-md text-sm text-muted-foreground">
                Добавьте ролик, выберите площадки и нажмите Старт — бот сам пройдёт по всем аккаунтам.
              </p>
            </Card>
          )}
          {queued.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-medium text-muted-foreground">В работе</h2>
              {queued.map((job) => (
                <JobCard key={job.id} job={job} busy={state.runner !== 'idle'} profiles={state.youtubeProfiles} />
              ))}
            </section>
          )}
          {done.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-medium text-muted-foreground">Завершённые</h2>
              {done.map((job) => (
                <JobCard key={job.id} job={job} busy={state.runner !== 'idle'} profiles={state.youtubeProfiles} />
              ))}
            </section>
          )}
        </div>
      </ScrollArea>
      <UploadLogPanel />
    </div>
  )
}

function UploadLogPanel(): JSX.Element {
  const [text, setText] = useState('')
  const load = useCallback(() => {
    void window.api.readLog().then((value) => setText(value))
  }, [])

  useEffect(() => {
    load()
    return window.api.onProgress(() => load())
  }, [load])

  return (
    <section className="shrink-0 border-t border-border px-8 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">Журнал</h2>
        <Button variant="ghost" size="sm" onClick={load}>
          <RefreshCw className="size-3.5" />
          Обновить
        </Button>
      </div>
      <pre className="max-h-40 overflow-auto rounded-lg border border-border bg-zinc-50 px-3 py-2 font-mono text-[11px] leading-4 text-zinc-700 whitespace-pre-wrap">
        {text || 'Пока пусто — записи появятся при загрузке.'}
      </pre>
    </section>
  )
}

function JobCard({ job, busy, profiles }: { job: VideoJob; busy: boolean; profiles: YoutubeProfileInfo[] }): JSX.Element {
  const targets = job.targets?.length ? job.targets : job.enabledPlatforms
  const failed = targets.filter((id) => job.results[id]?.status === 'error')

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-base font-semibold">{job.title || 'Без названия'}</h3>
            <Badge>{jobStatusLabel[job.status]}</Badge>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">{fileName(job.videoPath)}</p>
          <p className="mt-1 text-xs text-muted-foreground">Публикация: {formatDate(job.publishAt)}</p>
        </div>
        <div className="flex items-center gap-1">
          {failed.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy && job.status === 'uploading'}
              onClick={() => void window.api.retryJob(job.id)}
            >
              <RotateCcw className="size-3.5" />
              Повторить ошибки
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            disabled={job.status === 'uploading'}
            title={job.status === 'uploading' ? 'Сначала остановите очередь' : 'Удалить ролик из очереди'}
            onClick={() => void window.api.removeJob(job.id)}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {targets.map((target) => {
          const platformId = targetPlatform(target) ?? 'youtube'
          const platform = getPlatform(platformId)
          const result = job.results[target]
          const st = result?.status ?? 'pending'
          return (
            <span
              key={target}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${statusClass[st]}`}
              title={result?.error}
            >
              <PlatformIcon id={platformId} className="size-3.5" style={{ color: platform.color }} />
              {targetLabel(target, profiles)}
              <span className="opacity-70">{statusLabel[st]}</span>
              {st === 'done' && result?.url && (
                <a
                  href={result.url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-0.5 underline decoration-emerald-300 hover:text-emerald-900"
                  title={result.url}
                  onClick={(e) => e.stopPropagation()}
                >
                  ссылка
                </a>
              )}
              {st === 'error' && (
                <button
                  type="button"
                  disabled={job.status === 'uploading'}
                  className="ml-0.5 rounded-full px-1 font-medium underline decoration-red-300 hover:text-red-900 disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() => void window.api.retryJob(job.id, target)}
                >
                  ещё раз
                </button>
              )}
            </span>
          )
        })}
      </div>
      {failed.length > 0 && (
        <p className="mt-3 text-xs text-red-600">
          Не загрузилось: {failed.map((id) => targetLabel(id, profiles)).join(', ')}. Остальные направления не затронуты —
          можно повторить только ошибки.
        </p>
      )}
    </Card>
  )
}
