import { ExternalLink } from 'lucide-react'
import type { JSX } from 'react'
import { PlatformIcon } from '@renderer/components/PlatformIcon'
import { Badge } from '@renderer/components/ui/badge'
import { Card } from '@renderer/components/ui/card'
import { ScrollArea } from '@renderer/components/ui/scroll-area'
import { formatDate } from '@renderer/lib/utils'
import { getPlatform } from '@shared/platforms'
import { targetLabel } from '@shared/targets'
import type { AppState } from '@shared/types'

export function HistoryPage({ state }: { state: AppState }): JSX.Element {
  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-border px-8 py-5">
        <h1 className="text-xl font-semibold">История</h1>
        <p className="text-sm text-muted-foreground">Что ушло на площадки и где сломалось</p>
      </header>
      <ScrollArea className="flex-1">
        <div className="space-y-3 px-8 py-6">
          {state.history.length === 0 && (
            <Card className="py-16 text-center text-sm text-muted-foreground">Пока пусто — после загрузок записи появятся здесь</Card>
          )}
          {state.history.map((entry) => {
            const platform = getPlatform(entry.platform)
            return (
              <Card key={entry.id} className="flex items-start gap-4 p-4">
                <span style={{ color: platform.color }} className="mt-0.5">
                  <PlatformIcon id={entry.platform} className="size-5" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{entry.jobTitle}</span>
                    <Badge className={entry.status === 'done' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-red-50 text-red-700'}>
                      {entry.status === 'done' ? 'успех' : 'ошибка'}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {entry.target ? targetLabel(entry.target, state.youtubeProfiles) : platform.shortName}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{entry.message}</p>
                  {entry.url && (
                    <a
                      href={entry.url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1 inline-flex max-w-full items-center gap-1.5 text-sm text-violet-700 hover:underline"
                    >
                      <ExternalLink className="size-3.5 shrink-0" />
                      <span className="truncate">{entry.url}</span>
                    </a>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">{formatDate(entry.at)}</p>
                </div>
              </Card>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}
