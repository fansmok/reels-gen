import { useEffect, useState, type JSX, type ReactNode, type SelectHTMLAttributes } from 'react'
import { Label } from '@renderer/components/ui/label'
import { cn } from '@renderer/lib/utils'
import type { GeneratorInfo, GeneratorRun, GeneratorSettings } from '@shared/generator'
import type { AppState } from '@shared/types'

export interface StepProps {
  s: GeneratorSettings
  set: (patch: Partial<GeneratorSettings>) => void
  info: GeneratorInfo | null
  state: AppState
  run: GeneratorRun
  reloadInfo: () => void
}

export function NativeSelect({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>): JSX.Element {
  return (
    <select
      className={cn(
        'h-10 w-full rounded-lg border border-border bg-white px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:opacity-50',
        className
      )}
      {...rest}
    >
      {children}
    </select>
  )
}

export function Field({ label, hint, children, className }: { label: string; hint?: string; children: ReactNode; className?: string }): JSX.Element {
  return (
    <div className={cn('space-y-1.5', className)}>
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function Row({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }): JSX.Element {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
      {children}
    </div>
  )
}

export function RadioCard({ active, title, hint, onClick, disabled }: { active: boolean; title: string; hint: string; onClick: () => void; disabled?: boolean }): JSX.Element {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-xl border p-3 text-left transition-colors disabled:opacity-50',
        active ? 'border-violet-400 bg-violet-50' : 'border-border bg-white hover:bg-muted/50'
      )}
    >
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>
    </button>
  )
}

/** Картинка с диска через протокол reel:// с защитой от кэша. */
export function LocalImage({ path, className, alt = '' }: { path: string; className?: string; alt?: string }): JSX.Element | null {
  const [src, setSrc] = useState('')
  useEffect(() => {
    let alive = true
    if (!path) {
      setSrc('')
      return
    }
    void window.api.previewUrl(path).then((url) => {
      if (alive) setSrc(`${url}&t=${Date.now()}`)
    })
    return () => {
      alive = false
    }
  }, [path])
  if (!path || !src) return null
  return <img src={src} alt={alt} className={className} />
}

export function PreviewBox({ path, note, empty, ratio = 'aspect-[9/16]' }: { path: string; note?: string; empty: string; ratio?: string }): JSX.Element {
  return (
    <div className="space-y-2">
      <div className={cn('overflow-hidden rounded-xl border border-border bg-zinc-100', ratio)}>
        {path ? (
          <LocalImage path={path} className="h-full w-full object-contain" />
        ) : (
          <div className="flex h-full items-center justify-center p-4 text-center text-xs text-muted-foreground">{empty}</div>
        )}
      </div>
      {note && <p className="whitespace-pre-line text-[11px] text-muted-foreground">{note}</p>}
    </div>
  )
}

export function linesOf(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
}

export function formatBytes(size: number): string {
  if (size > 1024 * 1024 * 1024) return `${(size / 1024 / 1024 / 1024).toFixed(1)} ГБ`
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} МБ`
  return `${Math.max(1, Math.round(size / 1024))} КБ`
}

/** Чеклист строк с галочками (фразы Whisper, заголовки Kie). */
export function CheckList({
  items,
  checked,
  onToggle,
  onRemove,
  emptyText
}: {
  items: string[]
  checked: string[]
  onToggle: (item: string) => void
  onRemove?: (item: string) => void
  emptyText: string
}): JSX.Element {
  if (items.length === 0) return <p className="text-xs text-muted-foreground">{emptyText}</p>
  return (
    <div className="space-y-1">
      {items.map((item, index) => {
        const on = checked.includes(item)
        return (
          <div key={`${index}-${item}`} className={cn('flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs', on ? 'border-violet-200 bg-violet-50/60' : 'border-border bg-white')}>
            <input type="checkbox" className="mt-0.5 accent-violet-600" checked={on} onChange={() => onToggle(item)} />
            <span className="min-w-0 flex-1 break-words">{item}</span>
            {onRemove && (
              <button type="button" className="text-muted-foreground hover:text-destructive" onClick={() => onRemove(item)} title="Убрать">
                ×
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
