import { useEffect, useState, type JSX } from 'react'
import { Toaster, toast } from 'sonner'
import { AppShell, type PageId } from '@renderer/components/AppShell'
import { useAppState } from '@renderer/lib/useAppState'
import { AccountsPage } from '@renderer/pages/AccountsPage'
import { GeneratorPage } from '@renderer/pages/GeneratorPage'
import { HistoryPage } from '@renderer/pages/HistoryPage'
import { NewVideoPage } from '@renderer/pages/NewVideoPage'
import { ProxyPage } from '@renderer/pages/ProxyPage'
import { QueuePage } from '@renderer/pages/QueuePage'
import { SettingsPage } from '@renderer/pages/SettingsPage'

const runnerLabels = {
  idle: 'ожидает',
  running: 'загружает',
  paused: 'пауза',
  waiting: 'ждёт время публикации'
} as const

function App(): JSX.Element {
  const { state, ready } = useAppState()
  const [page, setPage] = useState<PageId>('queue')

  useEffect(() => {
    return window.api.onProgress((event) => {
      if (event.level === 'info') return
      if (event.level === 'error') toast.error(event.message)
      else if (event.level === 'success') toast.success(event.message)
      else if (event.level === 'warn') toast.warning(event.message)
    })
  }, [])

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Загрузка настроек…
      </div>
    )
  }

  return (
    <>
      <AppShell page={page} onPage={setPage} runnerLabel={runnerLabels[state.runner]}>
        {page === 'queue' && <QueuePage state={state} />}
        {page === 'new' && <NewVideoPage state={state} />}
        {page === 'generator' && <GeneratorPage state={state} />}
        {page === 'accounts' && <AccountsPage state={state} />}
        {page === 'proxy' && <ProxyPage state={state} />}
        {page === 'history' && <HistoryPage state={state} />}
        {page === 'settings' && <SettingsPage state={state} />}
      </AppShell>
      <Toaster theme="light" richColors position="bottom-right" visibleToasts={3} offset={20} />
    </>
  )
}

export default App
