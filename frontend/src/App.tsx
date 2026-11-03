import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Suspense, lazy, useEffect, useState } from 'react'
import { chooseProfile, currentProfile, fetchProfiles, fetchSyncStatus, startSync, type ProfileSummary } from './api'
import { SetupWizard } from './components/Setup'
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
const ADD_PERSON = '#add-person'

function pageElement(page: string) {
  const activity = ACTIVITY_HASH.exec(page)
  if (activity) return <ActivityPage id={Number(activity[1])} />
  return PAGES.find((p) => p.hash === page)?.element
}

function useHashPage(): string {
  const read = () => {
    const hash = window.location.hash
    return PAGES.some((p) => p.hash === hash) || ACTIVITY_HASH.test(hash) || hash === ADD_PERSON ? hash : '#today'
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

function ProfilePicker({
  profiles,
  onChoose,
  onCancel,
}: {
  profiles: ProfileSummary[]
  onChoose: (slug: string) => void
  onCancel?: () => void
}) {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-sm flex-col justify-center gap-4">
      <h1 className="text-lg font-semibold text-primary">Who is training?</h1>
      <ul className="space-y-2">
        {profiles.map((profile) => (
          <li key={profile.slug}>
            <button
              type="button"
              onClick={() => onChoose(profile.slug)}
              className="flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-left hover:bg-raised"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-raised text-sm font-semibold text-primary">
                {profile.name.charAt(0)}
              </span>
              <span className="text-base font-semibold text-primary">{profile.name}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">Each person has their own data, plan and coach. Research papers are shared.</p>
      <div className="flex gap-4">
        <a href={ADD_PERSON} className="text-sm text-accent">
          Add a person
        </a>
        {onCancel && (
          <button type="button" onClick={onCancel} className="text-sm text-secondary">
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const page = useHashPage()
  const queryClient = useQueryClient()
  const profiles = useQuery({ queryKey: ['profiles'], queryFn: fetchProfiles, staleTime: Infinity })
  const [chosen, setChosen] = useState(currentProfile)
  const [picking, setPicking] = useState(false)
  const list = profiles.data
  const active = list?.length === 1 ? list[0] : list?.find((profile) => profile.slug === chosen)

  useEffect(() => {
    if (active && page !== ADD_PERSON && active.slug !== currentProfile()) chooseProfile(active.slug)
  }, [active, page])

  const choose = (slug: string) => {
    chooseProfile(slug)
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'profiles' })
    setChosen(slug)
    setPicking(false)
    window.location.hash = '#today'
  }

  const finishSetup = async (slug: string) => {
    await queryClient.invalidateQueries({ queryKey: ['profiles'] })
    choose(slug)
  }

  if (profiles.error) {
    return <p className="p-4 text-sm text-critical">{profiles.error.message}</p>
  }
  if (!list) return null
  if (list.length === 0 || page === ADD_PERSON) {
    return (
      <div className="px-4">
        <SetupWizard
          firstRun={list.length === 0}
          onDone={(slug) => void finishSetup(slug)}
          onCancel={list.length > 0 ? () => (window.location.hash = active ? '#settings' : '') : undefined}
        />
      </div>
    )
  }
  if (!active || picking) {
    return (
      <div className="px-4">
        <ProfilePicker profiles={list} onChoose={choose} onCancel={active ? () => setPicking(false) : undefined} />
      </div>
    )
  }
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
        <div className="flex shrink-0 items-center gap-2">
          <SyncButton key={active.slug} />
          {list.length > 1 && (
            <button
              type="button"
              onClick={() => setPicking(true)}
              title={`${active.name}, switch profile`}
              aria-label={`Profile ${active.name}, switch profile`}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-raised text-sm font-semibold text-primary hover:border-accent"
            >
              {active.name.charAt(0)}
            </button>
          )}
        </div>
      </header>
      <main key={active.slug}>
        <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
          {pageElement(page)}
        </Suspense>
      </main>
    </div>
  )
}
