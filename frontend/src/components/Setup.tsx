import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import {
  addProfile,
  chooseProfile,
  fetchClaude,
  fetchGarmin,
  garminCode,
  garminLogin,
  saveClaude,
  startBackfill,
  type Claude,
  type Garmin,
} from '../api'
import { localToday, shortDate } from '../format'

const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
const primary = 'rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50'
const quiet = 'text-sm text-secondary hover:text-primary'

const HISTORY = [
  { days: 90, label: '3 months' },
  { days: 365, label: '1 year' },
  { days: 730, label: '2 years' },
  { days: 1095, label: '3 years' },
]

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-muted">
      <span className="mb-1 block">{label}</span>
      {children}
      {hint && <span className="mt-1 block">{hint}</span>}
    </label>
  )
}

function Problem({ error }: { error: Error | null }) {
  return error ? <p className="text-xs text-critical">{error.message}</p> : null
}

export function KeyHelp() {
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm text-secondary">
      <li>
        Sign in or create an account at{' '}
        <a className="text-accent" href="https://platform.claude.com" target="_blank" rel="noreferrer">
          platform.claude.com
        </a>
        . The API is separate from a Claude.ai Pro or Max subscription.
      </li>
      <li>
        Open{' '}
        <a className="text-accent" href="https://platform.claude.com/settings/billing" target="_blank" rel="noreferrer">
          Settings, Billing
        </a>{' '}
        and buy credits. The API is prepaid, so the coach does nothing without them. Credits expire after a year. Leave
        auto-reload off to make the credits you bought the most you can spend.
      </li>
      <li>
        Open{' '}
        <a className="text-accent" href="https://platform.claude.com/settings/keys" target="_blank" rel="noreferrer">
          Settings, API keys
        </a>{' '}
        and create a key. Copy it right away, the console shows it only once. It starts with sk-ant-.
      </li>
    </ol>
  )
}

export function ClaudeForm({ claude, onSaved, onSkip }: { claude: Claude; onSaved?: () => void; onSkip?: () => void }) {
  const queryClient = useQueryClient()
  const [key, setKey] = useState('')
  const [budget, setBudget] = useState(String(claude.monthly_budget_usd ?? 5))
  const save = useMutation({
    mutationFn: () => saveClaude({ monthly_budget_usd: Number(budget), ...(key.trim() && { api_key: key.trim() }) }),
    onSuccess: (data) => {
      queryClient.setQueryData(['claude'], data)
      void queryClient.invalidateQueries({ queryKey: ['usage'] })
      setKey('')
      onSaved?.()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field
        label="API key"
        hint={claude.key_set ? `The saved key ends in ${claude.key_hint}. Paste a new one to replace it.` : undefined}
      >
        <input
          type="password"
          autoComplete="off"
          required={!claude.key_set}
          className={input}
          value={key}
          placeholder="sk-ant-…"
          onChange={(event) => setKey(event.target.value)}
        />
      </Field>
      <Field
        label="Monthly budget in US dollars"
        hint="Covers everyone and the research library. The coach pauses until the 1st when it is used up. About 5 to 10 dollars fits two people."
      >
        <input
          type="number"
          required
          min={1}
          max={1000}
          step={0.5}
          className={input}
          value={budget}
          onChange={(event) => setBudget(event.target.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={save.isPending} className={primary}>
          {save.isPending ? 'Checking the key…' : 'Save'}
        </button>
        {onSkip && (
          <button type="button" onClick={onSkip} className={quiet}>
            Skip for now
          </button>
        )}
        {save.isSuccess && !onSaved && <span className="text-xs text-secondary">Saved</span>}
      </div>
      <Problem error={save.error} />
    </form>
  )
}

export function GarminLoginForm({
  slug,
  onConnected,
  onSkip,
}: {
  slug: string
  onConnected?: () => void
  onSkip?: () => void
}) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needsCode, setNeedsCode] = useState(false)
  const done = (data: Garmin) => {
    queryClient.setQueryData(['garmin', slug], data)
    setPassword('')
    setCode('')
    setNeedsCode(data.waiting_for_code)
    if (data.connected) onConnected?.()
  }
  const login = useMutation({ mutationFn: () => garminLogin(email.trim(), password), onSuccess: done })
  const confirm = useMutation({ mutationFn: () => garminCode(code.trim()), onSuccess: done })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (needsCode) confirm.mutate()
    else login.mutate()
  }
  if (needsCode) {
    return (
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-secondary">Garmin sent a code by email or text message. Enter it here.</p>
        <Field label="Code">
          <input
            required
            inputMode="numeric"
            autoComplete="one-time-code"
            className={input}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={confirm.isPending} className={primary}>
            {confirm.isPending ? 'Checking…' : 'Confirm'}
          </button>
          <button type="button" onClick={() => setNeedsCode(false)} className={quiet}>
            Start over
          </button>
        </div>
        <Problem error={confirm.error} />
      </form>
    )
  }
  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="Garmin Connect email">
        <input
          type="email"
          required
          autoComplete="username"
          className={input}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>
      <Field
        label="Password"
        hint="The password goes to Garmin only. The app keeps a login token, so you won't need to log in again."
      >
        <input
          type="password"
          required
          autoComplete="current-password"
          className={input}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={login.isPending} className={primary}>
          {login.isPending ? 'Logging in…' : 'Log in'}
        </button>
        {onSkip && (
          <button type="button" onClick={onSkip} className={quiet}>
            Skip for now
          </button>
        )}
      </div>
      <Problem error={login.error} />
    </form>
  )
}

function daysSince(isoDate: string): number {
  return Math.round((Date.parse(localToday()) - Date.parse(isoDate)) / 86_400_000)
}

export function BackfillProgress({ garmin }: { garmin: Garmin }) {
  if (!garmin.backfill) return null
  const reached = garmin.backfill_reached
  const share = reached ? Math.min(daysSince(reached) / garmin.backfill.days, 1) : 0
  return (
    <div className="space-y-1.5">
      <div
        className="h-2 overflow-hidden rounded-full bg-raised"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
        aria-label="History fetched from Garmin"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(share, 0.02) * 100}%` }} />
      </div>
      <p className="text-xs text-secondary">
        {reached ? `Fetched back to ${shortDate(reached)}` : 'Starting'}, {Math.round(share * 100)}% of{' '}
        {garmin.backfill.days} days. It keeps going in the background if you leave this page.
      </p>
    </div>
  )
}

export function HistoryForm({ slug, onStarted }: { slug: string; onStarted?: () => void }) {
  const queryClient = useQueryClient()
  const [days, setDays] = useState(730)
  const start = useMutation({
    mutationFn: () => startBackfill(days),
    onSuccess: (data) => {
      queryClient.setQueryData(['garmin', slug], data)
      onStarted?.()
    },
  })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="How much history">
        {HISTORY.map((choice) => (
          <button
            key={choice.days}
            type="button"
            onClick={() => setDays(choice.days)}
            aria-pressed={days === choice.days}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              days === choice.days ? 'border-accent bg-raised text-primary' : 'border-line text-secondary'
            }`}
          >
            {choice.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">
        The app waits 2 seconds between requests to Garmin, so a year takes one to two hours. Fetching again later
        continues from where it stopped.
      </p>
      <button type="button" disabled={start.isPending} onClick={() => start.mutate()} className={primary}>
        Start fetching
      </button>
      <Problem error={start.error} />
    </div>
  )
}

function useGarmin(slug: string) {
  return useQuery({
    queryKey: ['garmin', slug],
    queryFn: fetchGarmin,
    refetchInterval: (query) => (query.state.data?.syncing ? 3000 : false),
  })
}

export function GarminStatus({ slug }: { slug: string }) {
  const garmin = useGarmin(slug)
  const [open, setOpen] = useState<'login' | 'history' | null>(null)
  const data = garmin.data
  if (garmin.error) return <Problem error={garmin.error} />
  if (!data) return null
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">Login</dt>
        <dd className={data.connected ? 'text-primary' : 'text-warning'}>
          {data.connected ? 'Connected' : '▲ Not connected'}
        </dd>
        <dt className="text-muted">Activities from</dt>
        <dd className="text-primary">{data.oldest_activity ? shortDate(data.oldest_activity) : 'none yet'}</dd>
      </dl>
      <BackfillProgress garmin={data} />
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => setOpen(open === 'login' ? null : 'login')}
          className="text-sm text-accent"
        >
          {data.connected ? 'Log in again' : 'Log in to Garmin'}
        </button>
        {data.connected && !data.syncing && (
          <button
            type="button"
            onClick={() => setOpen(open === 'history' ? null : 'history')}
            className="text-sm text-accent"
          >
            Fetch more history
          </button>
        )}
      </div>
      {open === 'login' && <GarminLoginForm slug={slug} onConnected={() => setOpen(null)} />}
      {open === 'history' && <HistoryForm slug={slug} onStarted={() => setOpen(null)} />}
    </div>
  )
}

type Step = 'claude' | 'person' | 'garmin' | 'history'

const STEP_TITLES: Record<Step, string> = {
  claude: 'Connect Claude',
  person: 'Who is training?',
  garmin: 'Connect Garmin',
  history: 'Fetch your history',
}

function PersonStep({ onCreated }: { onCreated: (slug: string) => void }) {
  const [name, setName] = useState('')
  const [trimp, setTrimp] = useState(1.92)
  const create = useMutation({
    mutationFn: () => addProfile(name.trim(), trimp),
    onSuccess: (profile) => {
      chooseProfile(profile.slug)
      onCreated(profile.slug)
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-secondary">
        Each person gets their own Garmin login, data, plan and coach. Everyone shares the research library, and there
        is no app login, so anyone who can open the app sees every profile.
      </p>
      <Field label="Name">
        <input required maxLength={60} className={input} value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-xs text-muted">Training load formula</legend>
        {[
          { value: 1.92, label: 'Male, factor 1.92' },
          { value: 1.67, label: 'Female, factor 1.67' },
        ].map((choice) => (
          <label key={choice.value} className="flex items-center gap-2 text-sm text-primary">
            <input type="radio" name="trimp" checked={trimp === choice.value} onChange={() => setTrimp(choice.value)} />
            {choice.label}
          </label>
        ))}
        <p className="text-xs text-muted">
          TRIMP turns heart rate into training load for activities where Garmin has none. You can change the factor on
          the Goals page.
        </p>
      </fieldset>
      <button type="submit" disabled={create.isPending} className={primary}>
        Create profile
      </button>
      <Problem error={create.error} />
    </form>
  )
}

function HistoryStep({ slug, onDone }: { slug: string; onDone: () => void }) {
  const garmin = useGarmin(slug)
  const started = Boolean(garmin.data?.backfill)
  return (
    <div className="space-y-4">
      <p className="text-sm text-secondary">
        The coach uses past activities, sleep and HRV for baselines and trends, so more history gives better advice.
      </p>
      {started && garmin.data ? <BackfillProgress garmin={garmin.data} /> : <HistoryForm slug={slug} />}
      <button type="button" onClick={onDone} className={started ? primary : quiet}>
        {started ? 'Open the app' : 'Skip, the hourly sync fetches the last two weeks'}
      </button>
    </div>
  )
}

function Wizard({
  askKey,
  claude,
  firstRun,
  onDone,
  onCancel,
}: {
  askKey: boolean
  claude: Claude
  firstRun: boolean
  onDone: (slug: string) => void
  onCancel?: () => void
}) {
  const [steps] = useState<Step[]>(() =>
    askKey ? ['claude', 'person', 'garmin', 'history'] : ['person', 'garmin', 'history'],
  )
  const [step, setStep] = useState<Step>(steps[0])
  const [slug, setSlug] = useState<string | null>(null)
  const next = () => setStep(steps[steps.indexOf(step) + 1])
  return (
    <div className="mx-auto max-w-md py-10">
      <p className="text-xs text-muted">
        {firstRun ? 'Set up the coach' : 'Add a person'}, step {steps.indexOf(step) + 1} of {steps.length}
      </p>
      <h1 className="mb-4 text-lg font-semibold text-primary">{STEP_TITLES[step]}</h1>
      <div className="rounded-xl border border-line bg-surface p-4">
        {step === 'claude' && (
          <div className="space-y-4">
            <p className="text-sm text-secondary">
              The coach talks to Claude through the Anthropic API. It needs an API key with credits:
            </p>
            <KeyHelp />
            <ClaudeForm claude={claude} onSaved={next} onSkip={next} />
          </div>
        )}
        {step === 'person' && (
          <PersonStep
            onCreated={(created) => {
              setSlug(created)
              next()
            }}
          />
        )}
        {step === 'garmin' && slug && (
          <div className="space-y-4">
            <p className="text-sm text-secondary">
              Log in with the Garmin Connect account your watch syncs to. The app then fetches new activities every hour
              from 05:00 to 23:00.
            </p>
            <GarminLoginForm slug={slug} onConnected={next} onSkip={() => onDone(slug)} />
          </div>
        )}
        {step === 'history' && slug && <HistoryStep slug={slug} onDone={() => onDone(slug)} />}
      </div>
      {onCancel && step !== 'garmin' && step !== 'history' && (
        <button type="button" onClick={onCancel} className={`mt-4 ${quiet}`}>
          Cancel
        </button>
      )}
    </div>
  )
}

export function SetupWizard({
  firstRun,
  onDone,
  onCancel,
}: {
  firstRun: boolean
  onDone: (slug: string) => void
  onCancel?: () => void
}) {
  const claude = useQuery({ queryKey: ['claude'], queryFn: fetchClaude })
  if (claude.error) return <p className="p-4 text-sm text-critical">{claude.error.message}</p>
  if (!claude.data) return null
  return (
    <Wizard
      askKey={!claude.data.key_set}
      claude={claude.data}
      firstRun={firstRun}
      onDone={onDone}
      onCancel={onCancel}
    />
  )
}
