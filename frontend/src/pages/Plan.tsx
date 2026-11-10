import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  acceptProposal,
  addUnavailable,
  createConversation,
  deleteUnavailable,
  fetchCalendar,
  fetchProposals,
  fetchSeason,
  fetchUnavailable,
  rejectProposal,
  streamMessage,
  type Activity,
  type PlannedSession,
  type Proposal,
  type ProposalChange,
  type SeasonWeekSpec,
  type SessionSpec,
  type Unavailable,
  type UnavailableInput,
  type UnavailableReason,
} from '../api'
import { Card } from '../components/Card'
import { applyEvent, type Pending } from '../chatEvents'
import { Bubble } from '../components/ChatParts'
import { SessionDialog } from '../components/SessionDetail'
import { sessionStatus } from '../sessions'
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

function seasonTargets(week: SeasonWeekSpec): string {
  return [
    `${number(week.hours, 1)} h`,
    week.climb_m !== null ? `${number(week.climb_m)} m up on foot` : null,
    week.longest_h !== null ? `longest ${number(week.longest_h, 1)} h` : null,
  ]
    .filter(Boolean)
    .join(', ')
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
      queryClient.invalidateQueries({ queryKey: ['season'] }),
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
      {proposal.season && (
        <details className="mt-3 text-sm" open={proposal.season.weeks.length <= 16}>
          <summary className="cursor-pointer text-xs text-muted select-none">
            Season outline, {proposal.season.weeks.length} weeks from {shortDate(proposal.season.weeks[0].week_start)}
          </summary>
          <ul className="mt-2 space-y-1">
            {proposal.season.weeks.map((week) => (
              <li key={week.week_start} className="text-secondary">
                {shortDate(week.week_start)}, {week.phase}, {seasonTargets(week)}
                {week.focus && <span className="text-muted">. {week.focus}</span>}
              </li>
            ))}
          </ul>
        </details>
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
  const [what, setWhat] = useState<'block' | 'season'>('block')
  const [weeks, setWeeks] = useState(4)
  const [start, setStart] = useState(() => addDays(mondayOf(localToday()), 7))
  const [notes, setNotes] = useState('')
  const [pending, setPending] = useState<Pending | null>(null)
  const [done, setDone] = useState(false)
  const busy = pending !== null && !done && pending.error === null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const request =
      what === 'block'
        ? [
            `Build a ${weeks}-week training block starting ${start}.`,
            'Look at my recent training, recovery, profile, goals, season outline and current plan first, then propose it with propose_plan.',
          ]
        : [
            `Build a season outline from the week of ${mondayOf(start)} to my most important race.`,
            'Look at my last 8 weeks of training, my profile and my goals first, then propose it with propose_season.',
          ]
    const text = [request[0], notes.trim(), request[1]]
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
        <label className="block text-xs text-muted sm:col-span-2">
          <span className="mb-1 block">What to plan</span>
          <select
            value={what}
            onChange={(event) => setWhat(event.target.value as 'block' | 'season')}
            className="w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm"
          >
            <option value="block">A training block with every session</option>
            <option value="season">A season outline up to the race, with weekly targets</option>
          </select>
        </label>
        {what === 'block' && (
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
        )}
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

function SessionCard({ session, today, onOpen }: { session: PlannedSession; today: string; onOpen: () => void }) {
  const theme = useTheme()
  const status = sessionStatus(session, today)
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`block w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-left text-xs hover:bg-raised ${session.skipped ? 'opacity-60' : ''}`}
      style={{ borderLeft: `3px solid ${sportColor(theme, session.sport)}` }}
    >
      <span className="block font-semibold text-primary">{session.title}</span>
      <span className="block text-secondary">{targets(session) || session.kind}</span>
      {status && (
        <span className={`block ${session.match ? 'text-secondary' : 'text-muted'}`}>{status.split(',')[0]}</span>
      )}
    </button>
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
  season,
  away,
  today,
  onOpen,
}: {
  season?: SeasonWeekSpec
  away: Unavailable[]
  monday: string
  sessions: PlannedSession[]
  activities: Activity[]
  doneSeconds: number
  today: string
  onOpen: (id: number) => void
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
        {season && (
          <span className="block text-xs font-normal text-secondary">
            {season.phase.charAt(0).toUpperCase() + season.phase.slice(1)} week, outline {seasonTargets(season)}
            {season.focus ? `. ${season.focus}` : ''}
          </span>
        )}
      </h3>
      <div className="grid gap-2 md:grid-cols-7">
        {days.map((day) => {
          const daySessions = sessions.filter((s) => s.day === day)
          const dayActivities = activities.filter((a) => a.start_time_local.slice(0, 10) === day)
          const dayAway = away.filter((period) => period.first_day <= day && day <= period.last_day)
          const empty = daySessions.length === 0 && dayActivities.length === 0 && dayAway.length === 0 && day !== today
          return (
            <div
              key={day}
              className={`min-w-0 rounded-lg p-1.5 ${day === today ? 'bg-raised' : ''} ${empty ? 'hidden md:block' : ''}`}
            >
              <p className={`mb-1 text-xs ${day === today ? 'font-semibold text-primary' : 'text-muted'}`}>
                {dayLabel(day)}
              </p>
              <div className="space-y-1.5">
                {dayAway.map((period) => (
                  <p key={period.id} className="rounded-md border border-dashed border-line px-2 py-1 text-xs text-secondary" title={period.note ?? undefined}>
                    {REASONS[period.reason]}
                  </p>
                ))}
                {daySessions.map((session) => (
                  <SessionCard key={session.id} session={session} today={today} onOpen={() => onOpen(session.id)} />
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

const REASONS: Record<UnavailableReason, string> = {
  travel: 'Travel',
  illness: 'Illness',
  injury: 'Injury',
  work: 'Work',
  other: 'Away',
}

function AwayDays({ periods, first, last }: { periods: Unavailable[]; first: string; last: string }) {
  const queryClient = useQueryClient()
  const today = localToday()
  const [period, setPeriod] = useState<UnavailableInput>({ first_day: today, last_day: today, reason: 'travel', note: null })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['unavailable'] })
  const add = useMutation({ mutationFn: addUnavailable, onSuccess: refresh })
  const remove = useMutation({ mutationFn: deleteUnavailable, onSuccess: refresh })
  const input = 'rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-secondary select-none">
        Days you cannot train as normal
        {periods.length > 0 && `, ${periods.length} between ${shortDate(first)} and ${shortDate(last)}`}
      </summary>
      <div className="mt-2 space-y-2">
        <p className="text-xs text-muted">
          Travel, illness, injury or work. The coach plans around these days. After adding some, ask the coach to move the sessions
          they hit.
        </p>
        {periods.map((row) => (
          <p key={row.id} className="text-xs text-secondary">
            {shortDate(row.first_day)}
            {row.last_day !== row.first_day && ` to ${shortDate(row.last_day)}`}, {REASONS[row.reason].toLowerCase()}
            {row.note ? `, ${row.note}` : ''}{' '}
            <button type="button" onClick={() => remove.mutate(row.id)} className="text-muted hover:text-critical">
              Remove
            </button>
          </p>
        ))}
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            add.mutate({ ...period, note: period.note || null })
          }}
        >
          <label className="text-xs text-muted">
            <span className="mb-1 block">From</span>
            <input
              type="date"
              required
              className={input}
              value={period.first_day}
              onChange={(event) =>
                setPeriod({
                  ...period,
                  first_day: event.target.value,
                  last_day: period.last_day < event.target.value ? event.target.value : period.last_day,
                })
              }
            />
          </label>
          <label className="text-xs text-muted">
            <span className="mb-1 block">To</span>
            <input
              type="date"
              required
              min={period.first_day}
              className={input}
              value={period.last_day}
              onChange={(event) => setPeriod({ ...period, last_day: event.target.value })}
            />
          </label>
          <label className="text-xs text-muted">
            <span className="mb-1 block">Reason</span>
            <select
              className={input}
              value={period.reason}
              onChange={(event) => setPeriod({ ...period, reason: event.target.value as UnavailableReason })}
            >
              {Object.entries(REASONS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="min-w-40 flex-1 text-xs text-muted">
            <span className="mb-1 block">What is still possible</span>
            <input
              className={`${input} w-full`}
              placeholder="Hotel gym, easy walks"
              value={period.note ?? ''}
              onChange={(event) => setPeriod({ ...period, note: event.target.value })}
            />
          </label>
          <button type="submit" className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised">
            Add
          </button>
        </form>
        {add.error && <p className="text-xs text-critical">{add.error.message}</p>}
      </div>
    </details>
  )
}

export function PlanPage() {
  const today = localToday()
  const [first, setFirst] = useState(() => addDays(mondayOf(today), -7))
  const last = addDays(first, WEEKS_SHOWN * 7 - 1)
  const calendar = useQuery({ queryKey: ['calendar', first, last], queryFn: () => fetchCalendar(first, last) })
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: fetchProposals })
  const season = useQuery({ queryKey: ['season', first, last], queryFn: () => fetchSeason(first, last) })
  const away = useQuery({ queryKey: ['unavailable', first, last], queryFn: () => fetchUnavailable(first, last) })
  const mondays = Array.from({ length: WEEKS_SHOWN }, (_, index) => addDays(first, index * 7))
  const data = calendar.data
  const matched = new Set(data?.sessions.map((s) => s.match?.activity_id))
  const futureSessions = data?.sessions.filter((s) => s.day >= today).length ?? 0
  const [openId, setOpenId] = useState<number | null>(null)
  const open = data?.sessions.find((s) => s.id === openId)

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
      <AwayDays periods={away.data ?? []} first={first} last={last} />
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
                season={season.data?.find((week) => week.week_start === monday)}
                away={away.data ?? []}
                sessions={data.sessions.filter((s) => mondayOf(s.day) === monday)}
                activities={weekActivities.filter((a) => !matched.has(a.id))}
                doneSeconds={weekActivities.reduce((sum, a) => sum + (a.duration_s ?? 0), 0)}
                onOpen={setOpenId}
              />
            )
          })}
        </div>
      )}
      {open && <SessionDialog key={open.id} session={open} today={today} onClose={() => setOpenId(null)} />}
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
