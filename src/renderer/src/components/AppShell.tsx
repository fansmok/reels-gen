import { Clapperboard, Clock, History, Layers3, Plus, Settings2, Shield, UserRound } from 'lucide-react'
import type { JSX, ReactNode } from 'react'
import { cn } from '@renderer/lib/utils'

export type PageId = 'queue' | 'new' | 'generator' | 'accounts' | 'proxy' | 'history' | 'settings'

const items: { id: PageId; label: string; hint: string; icon: typeof Plus }[] = [
  { id: 'queue', label: 'Очередь', hint: 'Ролики и статусы', icon: Layers3 },
  { id: 'new', label: 'Новый ролик', hint: 'Файл, название, обложка', icon: Plus },
  { id: 'generator', label: 'Генератор', hint: 'Собрать рилсы из верха и низа', icon: Clapperboard },
  { id: 'accounts', label: 'Аккаунты', hint: 'Вход на площадки', icon: UserRound },
  { id: 'proxy', label: 'Прокси', hint: 'Одной строкой', icon: Shield },
  { id: 'history', label: 'История', hint: 'Успехи и ошибки', icon: History },
  { id: 'settings', label: 'Настройки', hint: 'Текст, паузы, публикация', icon: Settings2 }
]

export function AppShell({
  page,
  onPage,
  runnerLabel,
  children
}: {
  page: PageId
  onPage: (id: PageId) => void
  runnerLabel: string
  children: ReactNode
}): JSX.Element {
  return (
    <div className="flex h-full bg-background">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-white">
        <div className="flex items-center gap-3 px-5 py-5">
          <div className="flex size-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-500 text-white shadow-md shadow-violet-500/25">
            <span className="text-lg leading-none">▶</span>
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">Рилс Загрузка</div>
            <div className="text-xs text-muted-foreground">версия {__APP_VERSION__}</div>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 px-3">
          {items.map((item) => {
            const Icon = item.icon
            const active = page === item.id
            return (
              <button
                key={item.id}
                onClick={() => onPage(item.id)}
                className={cn(
                  'flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors',
                  active ? 'bg-violet-50 text-violet-900' : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                )}
              >
                <Icon className={cn('size-4', active && 'text-violet-600')} />
                <span>
                  <span className="block text-sm font-medium">{item.label}</span>
                  <span className="block text-[11px] text-muted-foreground">{item.hint}</span>
                </span>
              </button>
            )
          })}
        </nav>
        <div className="m-3 rounded-xl border border-border bg-card px-3 py-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="size-3.5" />
            Статус бота
          </div>
          <div className="mt-1 text-sm font-medium">{runnerLabel}</div>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
    </div>
  )
}
