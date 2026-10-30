import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  acceptProposal,
  createConversation,
  deleteSession,
  fetchCalendar,
  fetchProposals,
  rejectProposal,
  setSkipped,
  streamMessage,
  type Activity,
  type PlannedSession,
  type Proposal,
  type ProposalChange,
  type SessionSpec,
} from '../api'
import { Card } from '../components/Card'
import { applyEvent, type Pending } from '../chatEvents'
import { Bubble } from '../components/ChatParts'
import { addDays, dayLabel, duration, localToday, mondayOf, number, shortDate } from '../format'
import { groupColor, groupLabel, useTheme, type Theme } from '../theme'

const WEEKS_SHOWN = 6
const PLAN_LENGTHS = [2, 4, 6, 8, 12]

function targets(session: SessionSpec): string {
  return [
    session.duration_min ? `${number(session.duration_min)} min` : null,
    session.distance_km ? `${number(session.distance_km, 1)} km` : null,
    session.elevation_gain_m ? `${number(session.elevation_gain_m)} m up` : null,
    session.intensity,
  ]
    .filter(Boolean)
    .join(', ')
}

function sportColor(theme: Theme, sport: string): string {
  return sport === 'rest' ? 'var(--border)' : groupColor(theme, sport)
}

function sessionLine(session: SessionSpec): string {
  return [dayLabel(session.day), session.title, targets(session)].filter(Boolean).join(', ')
}

function ChangeLine({ change }: { change: ProposalChange }) {
  if (change.op === 'add' && change.session) {
    return <>Add: {sessionLine(change.session)}</>
  }
  if (change.op === 'remove') {
    return <>Remove: {change.current ? sessionLine(change.current) : `session ${change.session_id}`}</>
  }
  return (
    <>
      Change: {change.current ? sessionLine(change.current) : `session ${change.session_id}`}
      <span className="text-muted"> becomes </span>
      {change.session && sessionLine(change.session)}
    </>
  )
}

function ProposalCard({ proposal }: { proposal: Proposal }) {
  const queryClient = useQueryClient()
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['proposals'] }),
      queryClient.invalidateQueries({ queryKey: ['calendar'] }),
    ])
  const accept = useMutation({ mutationFn: () => acceptProposal(proposal.id), onSuccess: refresh })
  const reject = useMutation({ mutationFn: () => rejectProposal(proposal.id), onSuccess: refresh })
  const sessions = proposal.plan?.sessions ?? []
  const error = accept.error ?? reject.error
  return (
    <Card title={proposal.summary} subtitle={`Proposed ${shortDate(proposal.created_at)}, waiting for you`}>
      <p className="text-sm whitespace-pre-wrap text-secondary">{proposal.reason}</p>
      {proposal.plan && (
        <div className="mt-3 text-sm">
          <p className="font-semibold text-primary">{proposal.plan.title}</p>
          {proposal.plan.description && (
            <p className="mt-1 whitespace-pre-wrap text-secondary">{proposal.plan.description}</p>
          )}
          <details className="mt-2" open={sessions.length <= 14}>
            <summary className="cursor-pointer text-xs text-muted select-none">
              {sessions.length} sessions from {shortDate(sessions[0].day)} to{' '}
              {shortDate(sessions[sessions.length - 1].day)}
            </summary>
            <ul className="mt-2 space-y-1">
              {sessions.map((session, index) => (
                <li key={index} className="text-secondary">
                  {sessionLine(session)}
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
      {proposal.changes.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-secondary">
          {proposal.changes.map((change, index) => (
            <li key={index}>
              <ChangeLine change={change} />
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          onClick={() => accept.mutate()}
          disabled={accept.isPending || reject.isPending}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          Accept
        </button>
        <button
          type="button"
          onClick={() => reject.mutate()}
          disabled={accept.isPending || reject.isPending}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-secondary hover:bg-raised disabled:opacity-50"
        >
          Reject
        </button>
        {error && <span className="text-xs text-critical">{error.message}</span>}
      </div>
    </Card>
  )
}

function PlanRequest() {
  const queryClient = useQueryClient()
  const [weeks, setWeeks] = useState(4)
  const [start, setStart] = useState(() => addDays(mondayOf(localToday()), 7))
  const [notes, setNotes] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [done, setDone] = useState(false)
  const busy = pending !== null && !done && pending.error === null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const text = [
      `Build a ${weeks}-week training block starting ${start}.`,
      notes.trim(),
      'Look at my recent training, recovery, profile, goals and current plan first, then propose it with propose_plan.',
    ]
      .filter(Boolean)
      .join(' ')
    setPending({ user: text, coach: '', tools: [], error: null })
    setDone(false)
    try {
      const conversation = await createConversation()
      await streamMessage(
        conversation.id,
        text,
        (chatEvent) => setPending((current) => (current ? applyEvent(current, chatEvent) : current)),
        'plan',
      )
    } catch (error) {
      setPending((current) => current && { ...current, error: String(error) })
    }
    setDone(true)
    await Promise.all(
      ['proposals', 'conversations', 'usage'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    )
  }

  return (
    <Card title="Ask the coach for a plan" subtitle="Uses the larger model, a plan costs about a dollar">
      <form onSubmit={(event) => void submit(event)} className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-muted">
          <span className="mb-1 block">Length</span>
          <select
            value={weeks}
            onChange={(event) => setWeeks(Number(event.target.value))}
            className="w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm"
          >
            {PLAN_LENGTHS.map((length) => (
              <option key={length} value={length}>
                {length} weeks
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          <span className="mb-1 block">First day</span>
          <input
            type="date"
            value={start}
            onChange={(event) => setStart(event.target.value)}
            className="w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm"
          />
        </label>
        <label className="block text-xs text-muted sm:col-span-2">
          <span className="mb-1 block">Anything to consider, for example a trip, a sore knee or a focus</span>
          <textarea
            rows={2}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm"
          />
        </label>
        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {busy ? 'The coach is planning…' : 'Ask the coach'}
          </button>
        </div>
      </form>
      {pending && (
        <div className="mt-4 border-t border-line pt-4">
          <Bubble item={{ role: 'coach', text: pending.coach, tools: pending.tools }} />
          {pending.error && <p className="mt-2 text-sm text-critical">{pending.error}</p>}
          {done && (
            <a href="#chat" className="mt-2 inline-block text-xs text-accent">
              Continue this conversation in Chat
            </a>
          )}
        </div>
      )}
    </Card>
  )
}

function SessionCard({ session, today }: { session: PlannedSession; today: string }) {
  const theme = useTheme()
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['calendar'] })
  const skip = useMutation({ mutationFn: (skipped: boolean) => setSkipped(session.id, skipped), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => deleteSession(session.id), onSuccess: refresh })
  const past = session.day < today
  const status = session.skipped
    ? 'Skipped'
    : session.match
      ? `✓ Done${session.match.compliance !== null ? `, ${number(session.match.compliance)}%` : ''}`
      : past && session.sport !== 'rest'
        ? '▲ Not done'
        : null
  return (
    <details
      className={`rounded-lg border border-line bg-surface px-2 py-1.5 text-xs ${session.skipped ? 'opacity-60' : ''}`}
      style={{ borderLeft: `3px solid ${sportColor(theme, session.sport)}` }}
    >
      <summary className="cursor-pointer list-none">
        <span className="block font-semibold text-primary">{session.title}</span>
        <span className="block text-secondary">{targets(session) || session.kind}</span>
        {status && <span className={`block ${session.match ? 'text-secondary' : 'text-muted'}`}>{status}</span>}
      </summary>
      <div className="mt-2 space-y-2">
        <p className="text-muted">
          {session.sport === 'rest' ? 'Rest' : groupLabel(session.sport)}, {session.kind}
        </p>
        {session.description && <p className="whitespace-pre-wrap text-secondary">{session.description}</p>}
        {session.match && (
          <a href={`#activity/${session.match.activity_id}`} className="block text-accent">
            Open the activity
          </a>
        )}
        <div className="flex gap-3">
          <button type="button" onClick={() => skip.mutate(!session.skipped)} className="text-accent">
            {session.skipped ? 'Unskip' : 'Skip'}
          </button>
          <button
            type="button"
            onClick={() => window.confirm(`Delete ${session.title}?`) && remove.mutate()}
            className="text-muted hover:text-critical"
          >
            Delete
          </button>
        </div>
      </div>
    </details>
  )
}

function ActivityChip({ activity }: { activity: Activity }) {
  const theme = useTheme()
  return (
    <a
      href={`#activity/${activity.id}`}
      className="block rounded-lg border border-dashed border-line px-2 py-1 text-xs text-secondary hover:bg-raised"
    >
      <span
        className="mr-1.5 inline-block h-2 w-2 rounded-sm"
        style={{ background: groupColor(theme, activity.sport_group) }}
        aria-hidden
      />
      {activity.name ?? groupLabel(activity.sport_group)}, {duration(activity.duration_s)}
      {activity.distance_km ? `, ${number(activity.distance_km, 1)} km` : ''}
    </a>
  )
}

function WeekRow({
  monday,
  sessions,
  activities,
  doneSeconds,
  today,
}: {
  monday: string
  sessions: PlannedSession[]
  activities: Activity[]
  doneSeconds: number
  today: string
}) {
  const days = Array.from({ length: 7 }, (_, index) => addDays(monday, index))
  const plannedMinutes = sessions
    .filter((s) => !s.skipped)
    .reduce((sum, s) => sum + (s.duration_min ?? 0), 0)
  return (
    <section className="min-w-0">
      <h3 className="mb-2 text-sm font-semibold text-primary">
        Week from {shortDate(monday)}
        <span className="ml-2 text-xs font-normal text-muted">
          planned {duration(plannedMinutes * 60)}, done {duration(doneSeconds)}
        </span>
      </h3>
      <div className="grid gap-2 md:grid-cols-7">
        {days.map((day) => {
          const daySessions = sessions.filter((s) => s.day === day)
          const dayActivities = activities.filter((a) => a.start_time_local.slice(0, 10) === day)
          const empty = daySessions.length === 0 && dayActivities.length === 0 && day !== today
          return (
            <div
              key={day}
              className={`min-w-0 rounded-lg p-1.5 ${day === today ? 'bg-raised' : ''} ${empty ? 'hidden md:block' : ''}`}
            >
              <p className={`mb-1 text-xs ${day === today ? 'font-semibold text-primary' : 'text-muted'}`}>
                {dayLabel(day)}
              </p>
              <div className="space-y-1.5">
                {daySessions.map((session) => (
                  <SessionCard key={session.id} session={session} today={today} />
                ))}
                {dayActivities.map((activity) => (
                  <ActivityChip key={activity.id} activity={activity} />
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

export function PlanPage() {
  const today = localToday()
  const [first, setFirst] = useState(() => addDays(mondayOf(today), -7))
  const last = addDays(first, WEEKS_SHOWN * 7 - 1)
  const calendar = useQuery({ queryKey: ['calendar', first, last], queryFn: () => fetchCalendar(first, last) })
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: fetchProposals })
  const mondays = Array.from({ length: WEEKS_SHOWN }, (_, index) => addDays(first, index * 7))
  const data = calendar.data
  const matched = new Set(data?.sessions.map((s) => s.match?.activity_id))
  const futureSessions = data?.sessions.filter((s) => s.day >= today).length ?? 0

  return (
    <div className="space-y-4">
      {proposals.data?.map((proposal) => (
        <ProposalCard key={proposal.id} proposal={proposal} />
      ))}
      {data?.plans.map((plan) => (
        <details key={plan.id} className="text-sm">
          <summary className="cursor-pointer text-secondary select-none">
            <span className="font-semibold text-primary">{plan.title}</span>, {shortDate(plan.start_date)} to{' '}
            {shortDate(plan.end_date)}
          </summary>
          {plan.description && <p className="mt-1 whitespace-pre-wrap text-secondary">{plan.description}</p>}
        </details>
      ))}
      {futureSessions === 0 && !calendar.isPending && <PlanRequest />}
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Weeks shown">
        <button
          type="button"
          onClick={() => setFirst(addDays(first, -28))}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-secondary hover:bg-raised"
        >
          Earlier
        </button>
        <button
          type="button"
          onClick={() => setFirst(addDays(mondayOf(today), -7))}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-secondary hover:bg-raised"
        >
          This week
        </button>
        <button
          type="button"
          onClick={() => setFirst(addDays(first, 28))}
          className="rounded-lg border border-line px-3 py-1.5 text-sm text-secondary hover:bg-raised"
        >
          Later
        </button>
        <span className="text-xs text-muted">
          {shortDate(first)} to {shortDate(last)}
        </span>
      </div>
      {calendar.error && <p className="text-sm text-critical">{calendar.error.message}</p>}
      {data && (
        <div className="space-y-6">
          {mondays.map((monday) => {
            const weekActivities = data.activities.filter(
              (a) => a.sport_group !== 'commute' && mondayOf(a.start_time_local.slice(0, 10)) === monday,
            )
            return (
              <WeekRow
                key={monday}
                monday={monday}
                today={today}
                sessions={data.sessions.filter((s) => mondayOf(s.day) === monday)}
                activities={weekActivities.filter((a) => !matched.has(a.id))}
                doneSeconds={weekActivities.reduce((sum, a) => sum + (a.duration_s ?? 0), 0)}
              />
            )
          })}
        </div>
      )}
      {futureSessions > 0 && (
        <details>
          <summary className="cursor-pointer text-sm text-secondary select-none">Ask the coach for a new plan</summary>
          <div className="mt-2">
            <PlanRequest />
          </div>
        </details>
      )}
    </div>
  )
}
