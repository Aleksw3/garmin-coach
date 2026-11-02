import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Suspense, lazy, useEffect, useState } from 'react'
import { fetchSyncStatus, startSync } from './api'
import { TodayPage } from './pages/Today'

const TrendsPage = lazy(() => import('./pages/Trends').then((m) => ({ default: m.TrendsPage })))
const ChatPage = lazy(() => import('./pages/Chat').then((m) => ({ default: m.ChatPage })))
const PlanPage = lazy(() => import('./pages/Plan').then((m) => ({ default: m.PlanPage })))
const ActivityPage = lazy(() => import('./pages/Activity').then((m) => ({ default: m.ActivityPage })))
const ResearchPage = lazy(() => import('./pages/Research').then((m) => ({ default: m.ResearchPage })))
const GoalsPage = lazy(() => import('./pages/Goals').then((m) => ({ default: m.GoalsPage })))
const SettingsPage = lazy(() => import('./pages/Settings').then((m) => ({ default: m.SettingsPage })))

const PAGES = [
  { hash: '#today', label: 'Today', element: <TodayPage /> },
  { hash: '#chat', label: 'Chat', element: <ChatPage /> },
  { hash: '#plan', label: 'Plan', element: <PlanPage /> },
  { hash: '#trends', label: 'Trends', element: <TrendsPage /> },
  { hash: '#goals', label: 'Goals', element: <GoalsPage /> },
  { hash: '#research', label: 'Research', element: <ResearchPage /> },
  { hash: '#settings', label: 'Settings', element: <SettingsPage /> },
]

const ACTIVITY_HASH = /^#activity\/(\d+)$/

function pageElement(page: string) {
  const activity = ACTIVITY_HASH.exec(page)
  if (activity) return <ActivityPage id={Number(activity[1])} />
  return PAGES.find((p) => p.hash === page)?.element
}

function useHashPage(): string {
  const read = () => {
    const hash = window.location.hash
    return PAGES.some((p) => p.hash === hash) || ACTIVITY_HASH.test(hash) ? hash : '#today'
  }
  const [page, setPage] = useState(read)
  useEffect(() => {
    const onChange = () => setPage(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return page
}

function lastSyncText(lastSync: string | null): string {
  if (!lastSync) return 'Never synced'
  const minutes = Math.round((Date.now() - new Date(lastSync).getTime()) / 60_000)
  if (minutes < 1) return 'Synced just now'
  if (minutes < 60) return `Synced ${minutes} min ago`
  return `Synced ${Math.round(minutes / 60)} h ago`
}

function SyncButton() {
  const queryClient = useQueryClient()
  const status = useQuery({
    queryKey: ['sync'],
    queryFn: fetchSyncStatus,
    refetchInterval: (query) => (query.state.data?.running ? 3000 : 60_000),
  })
  const sync = useMutation({
    mutationFn: startSync,
    onSuccess: (data) => queryClient.setQueryData(['sync'], data),
  })
  const running = status.data?.running ?? false
  const failed = status.data?.runs[0]?.status

  useEffect(() => {
    if (!running) void queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'sync' })
  }, [running, queryClient])

  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="hidden sm:inline">
        {running ? 'Syncing with Garmin…' : lastSyncText(status.data?.last_sync ?? null)}
      </span>
      {failed && failed !== 'ok' && failed !== 'running' && (
        <span className="text-warning" title={status.data?.runs[0]?.error ?? ''}>
          ▲ Last sync {failed.replace('_', ' ')}
        </span>
      )}
      <button
        type="button"
        onClick={() => sync.mutate()}
        disabled={running}
        className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised disabled:opacity-50"
      >
        {running ? 'Syncing' : 'Sync'}
      </button>
    </div>
  )
}

export default function App() {
  const page = useHashPage()
  return (
    <div className="mx-auto min-h-screen max-w-5xl px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-10">
      <header className="mb-4 flex items-center justify-between gap-3">
        <nav className="no-scrollbar -mx-1 flex min-w-0 gap-0.5 overflow-x-auto sm:gap-1">
          {PAGES.map((p) => (
            <a
              key={p.hash}
              href={p.hash}
              aria-current={page === p.hash ? 'page' : undefined}
              className={`shrink-0 rounded-lg px-2 py-1.5 text-sm sm:px-3 ${
                page === p.hash ? 'bg-raised font-semibold text-primary' : 'text-secondary hover:bg-raised'
              }`}
            >
              {p.label}
            </a>
          ))}
        </nav>
        <SyncButton />
      </header>
      <main>
        <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
          {pageElement(page)}
        </Suspense>
      </main>
    </div>
  )
}
