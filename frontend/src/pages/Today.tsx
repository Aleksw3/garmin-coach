import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLayoutEffect, useRef, useState } from 'react'
import {
  fetchCalendar,
  fetchLatestCoach,
  fetchProposals,
  fetchToday,
  skipPrompt,
  type Activity,
  type GroupTotals,
  type PromptKind,
  type ToLog,
  type Today,
} from '../api'
import { Card } from '../components/Card'
import { CoachText } from '../components/ChatParts'
import { FuelCard } from '../components/FuelCard'
import { Meter, MetricTile, RangeTrack, type Tone } from '../components/Metric'
import { RatingCard } from '../components/RatingCard'
import { SessionDialog } from '../components/SessionDetail'
import { BaselineBadge } from '../components/StatTile'
import { WeekStrip } from '../components/WeekStrip'
import { addDays, duration, hours, longDay, mondayOf, number, sentence, weekday } from '../format'
import { sessionStatus } from '../sessions'
import { SPORT_GROUPS, displayGroup, groupColor, groupLabel, useTheme } from '../theme'

function useWeekCalendar(today: string) {
  const monday = mondayOf(today)
  const sunday = addDays(monday, 6)
  return useQuery({ queryKey: ['calendar', monday, sunday], queryFn: () => fetchCalendar(monday, sunday) })
}

function WeekSummary({ week }: { week: GroupTotals[] }) {
  const theme = useTheme()
  const totals = new Map<string, GroupTotals>()
  for (const row of week) {
    const key = displayGroup(row.sport_group)
    const existing = totals.get(key)
    totals.set(
      key,
      existing
        ? {
            ...existing,
            activities: existing.activities + row.activities,
            distance_km: existing.distance_km + row.distance_km,
            hours: existing.hours + row.hours,
            elevation_gain_m: existing.elevation_gain_m + row.elevation_gain_m,
          }
        : { ...row, sport_group: key },
    )
  }
  const rows = SPORT_GROUPS.filter((g) => totals.has(g.key)).map((g) => totals.get(g.key)!)
  if (rows.length === 0) return <p className="text-sm text-muted">Nothing logged yet this week.</p>
  const longest = Math.max(...rows.map((row) => row.hours))
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.sport_group} className="flex items-center gap-3 text-sm">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ background: groupColor(theme, row.sport_group) }}
            aria-hidden
          />
          <span className="min-w-0 flex-1 truncate text-secondary sm:w-32 sm:flex-none">{groupLabel(row.sport_group)}</span>
          <span className="hidden h-1.5 flex-1 sm:block" aria-hidden>
            <span
              className="block h-full rounded-full"
              style={{ width: `${(row.hours / longest) * 100}%`, background: groupColor(theme, row.sport_group) }}
            />
          </span>
          <span className="tabular shrink-0 text-primary">{hours(row.hours)}</span>
          <span className="tabular w-16 shrink-0 text-right text-secondary sm:w-20">
            {row.distance_km > 0 ? `${number(row.distance_km, 1)} km` : ''}
          </span>
          <span className="tabular w-14 shrink-0 text-right text-secondary sm:w-16">
            {row.elevation_gain_m > 0 ? `${number(row.elevation_gain_m)} m` : ''}
          </span>
        </li>
      ))}
    </ul>
  )
}

function ThisWeek({ today, totals }: { today: string; totals: GroupTotals[] }) {
  const calendar = useWeekCalendar(today)
  const [openId, setOpenId] = useState<number | null>(null)
  const sessions = calendar.data?.sessions ?? []
  const open = sessions.find((session) => session.id === openId)
  const planned = sessions.filter((session) => session.sport !== 'rest' && !session.skipped)
  const done = planned.filter((session) => session.match).length
  return (
    <Card title="This week" subtitle="Each block is one activity. A dashed block is a planned session that is still open">
      <WeekStrip
        today={today}
        sessions={sessions}
        activities={calendar.data?.activities ?? []}
        onOpenSession={setOpenId}
      />
      {planned.length > 0 && (
        <div className="mt-4">
          <div className="mb-1.5 flex justify-between text-xs text-secondary">
            <span>Planned sessions done</span>
            <span className="tabular">
              {done} of {planned.length}
            </span>
          </div>
          <Meter label="Planned sessions done" value={done} max={planned.length} />
        </div>
      )}
      <div className="mt-4 border-t border-line pt-4">
        <WeekSummary week={totals} />
      </div>
      {open && <SessionDialog key={open.id} session={open} today={today} onClose={() => setOpenId(null)} />}
    </Card>
  )
}

function ActivityRow({ activity }: { activity: Activity }) {
  const theme = useTheme()
  const figures = [
    duration(activity.duration_s),
    activity.distance_km ? `${number(activity.distance_km, 1)} km` : '',
    activity.elevation_gain_m ? `${number(activity.elevation_gain_m)} m` : '',
    activity.avg_hr ? `${number(activity.avg_hr)} bpm` : '',
    activity.training_load !== null ? number(activity.training_load) : '',
  ]
  const terrain = activity.terrain && activity.terrain !== 'unknown' ? `, ${activity.terrain}` : ''
  return (
    <li>
      <a
        href={`#activity/${activity.id}`}
        className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-raised"
      >
        <span
          className="h-9 w-1 shrink-0 rounded-full"
          style={{ background: groupColor(theme, activity.sport_group) }}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-primary">
            {activity.name ?? sentence(activity.type_key)}
          </div>
          <div className="truncate text-xs text-muted">
            {weekday(activity.start_time_local)} · {groupLabel(activity.sport_group)}
            {terrain}
            <span className="sm:hidden"> · {figures.slice(0, 3).filter(Boolean).join(' · ')}</span>
          </div>
        </div>
        {figures.map((figure, index) => (
          <span
            key={ACTIVITY_COLUMNS[index]}
            className={`tabular hidden w-20 shrink-0 text-right text-sm sm:block ${index === 0 ? 'text-primary' : 'text-secondary'}`}
          >
            {figure}
          </span>
        ))}
      </a>
    </li>
  )
}

const ACTIVITY_COLUMNS = ['Time', 'Distance', 'Climbing', 'Heart rate', 'Load']

function RecentActivities({ activities }: { activities: Activity[] }) {
  return (
    <Card title="Recent activities">
      {activities.length === 0 ? (
        <p className="text-sm text-muted">No activities yet.</p>
      ) : (
        <>
          <div className="hidden gap-3 pb-1 text-xs text-muted sm:flex" aria-hidden>
            <span className="flex-1" />
            {ACTIVITY_COLUMNS.map((column) => (
              <span key={column} className="w-20 shrink-0 text-right">
                {column}
              </span>
            ))}
          </div>
          <ul className="divide-y divide-line">
            {activities.map((activity) => (
              <ActivityRow key={activity.id} activity={activity} />
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}

function TodayPlan({ today }: { today: string }) {
  const theme = useTheme()
  const calendar = useWeekCalendar(today)
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: fetchProposals })
  const sessions = (calendar.data?.sessions ?? []).filter((session) => session.day === today)
  const waiting = proposals.data?.length ?? 0
  const [openId, setOpenId] = useState<number | null>(null)
  const open = sessions.find((s) => s.id === openId)
  return (
    <Card title="Today's plan" className="lg:col-span-2">
      {sessions.length === 0 && <p className="text-sm text-muted">Nothing planned today.</p>}
      <ul className="space-y-2">
        {sessions.map((session) => {
          const status = sessionStatus(session, today)
          const figures = [
            session.duration_min ? `${number(session.duration_min)} min` : null,
            session.distance_km ? `${number(session.distance_km, 1)} km` : null,
            session.elevation_gain_m ? `${number(session.elevation_gain_m)} m up` : null,
          ].filter(Boolean)
          return (
            <li key={session.id}>
              <button
                type="button"
                onClick={() => setOpenId(session.id)}
                className="flex w-full gap-3 rounded-lg bg-raised p-3 text-left hover:outline hover:outline-1 hover:outline-accent"
              >
                <span
                  className="w-1 shrink-0 self-stretch rounded-full"
                  style={{ background: session.sport === 'rest' ? theme.textMuted : groupColor(theme, session.sport) }}
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold text-primary">{session.title}</span>
                  {figures.length > 0 && (
                    <span className="tabular block text-xs text-secondary">{figures.join(' · ')}</span>
                  )}
                  {session.intensity && <span className="mt-0.5 block text-xs text-muted">{session.intensity}</span>}
                </span>
                {status && <span className="shrink-0 text-xs text-secondary">{status}</span>}
              </button>
            </li>
          )
        })}
      </ul>
      {open && <SessionDialog key={open.id} session={open} today={today} onClose={() => setOpenId(null)} />}
      {waiting > 0 && (
        <a href="#plan" className="mt-3 block text-xs text-accent">
          {waiting === 1 ? '1 plan proposal is' : `${waiting} plan proposals are`} waiting for you
        </a>
      )}
    </Card>
  )
}

function LatestCoachMessage() {
  const latest = useQuery({
    queryKey: ['coach-latest'],
    queryFn: fetchLatestCoach,
  })
  const text = useRef<HTMLDivElement>(null)
  const [cut, setCut] = useState(false)
  useLayoutEffect(() => {
    if (text.current) setCut(text.current.scrollHeight > text.current.clientHeight)
  }, [latest.data])
  if (!latest.data) return null
  return (
    <Card title="From your coach" subtitle={latest.data.label ?? undefined} className="lg:col-span-3">
      <div ref={text} className="relative max-h-64 overflow-hidden border-l-2 border-accent pl-3">
        <CoachText text={latest.data.text} />
        {cut && <div className="absolute inset-x-0 bottom-0 h-12 bg-linear-to-t from-surface to-transparent" />}
      </div>
      <a href="#chat" className="mt-3 block text-xs text-accent">
        {cut ? 'Read the rest in Chat' : 'Open in Chat'}
      </a>
    </Card>
  )
}

const READINESS_TONE: Record<string, Tone> = {
  POOR: 'critical',
  LOW: 'warning',
  MODERATE: 'accent',
  HIGH: 'good',
  PRIME: 'good',
}

const BASELINE_TONE: Record<'below' | 'within' | 'above', Tone> = {
  below: 'warning',
  within: 'good',
  above: 'neutral',
}

function Recovery({ data }: { data: Today }) {
  const wellness = data.wellness
  const sleptToday = wellness?.sleep_day === data.day
  const { hrv, resting_hr: restingHr, load } = data
  const loadScale = load ? Math.max(load.acute, load.chronic) * 1.1 : 1
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
      <MetricTile
        label="Readiness"
        value={number(wellness?.readiness_score)}
        unit="of 100"
        detail={sentence(wellness?.readiness_level)}
      >
        {wellness?.readiness_score != null && (
          <Meter
            label="Readiness"
            value={wellness.readiness_score}
            tone={READINESS_TONE[wellness.readiness_level ?? ''] ?? 'accent'}
          />
        )}
      </MetricTile>
      <MetricTile
        label={sleptToday ? 'Sleep last night' : `Sleep (${wellness?.sleep_day ? weekday(wellness.sleep_day) : '–'})`}
        value={hours(wellness?.sleep_h)}
        detail={wellness?.sleep_score ? `Score ${wellness.sleep_score} of 100` : undefined}
      >
        {wellness?.sleep_score != null && <Meter label="Sleep score" value={wellness.sleep_score} />}
      </MetricTile>
      <MetricTile
        label="HRV, 7-day mean"
        value={hrv ? number(hrv.rolling) : '–'}
        unit={hrv ? 'ms' : undefined}
        detail={
          hrv ? (
            <>
              <BaselineBadge status={hrv.status} />
              <div className="text-muted">
                Normal {number(hrv.low)} to {number(hrv.high)} ms, last night {number(wellness?.hrv_last_night)}
              </div>
            </>
          ) : (
            'Needs 30 nights of data'
          )
        }
      >
        {hrv && (
          <RangeTrack
            label="HRV against its normal range"
            low={hrv.low}
            high={hrv.high}
            value={hrv.rolling}
            latest={wellness?.hrv_last_night}
            tone={BASELINE_TONE[hrv.status]}
          />
        )}
      </MetricTile>
      <MetricTile
        label="Resting heart rate"
        value={number(wellness?.resting_hr)}
        unit={wellness?.resting_hr ? 'bpm' : undefined}
        detail={
          restingHr ? (
            <>
              <BaselineBadge status={restingHr.status} />
              <div className="text-muted">
                Normal {number(restingHr.low)} to {number(restingHr.high)} bpm
              </div>
            </>
          ) : undefined
        }
      >
        {restingHr && (
          <RangeTrack
            label="Resting heart rate against its normal range"
            low={restingHr.low}
            high={restingHr.high}
            value={restingHr.rolling}
            latest={wellness?.resting_hr}
            tone={BASELINE_TONE[restingHr.status]}
          />
        )}
      </MetricTile>
      <MetricTile label="Training load, 7-day" value={load ? number(load.acute) : '–'}>
        {load && (
          <div className="space-y-1.5 text-xs text-secondary">
            <Meter label="7-day load" value={load.acute} max={loadScale} />
            <Meter label="42-day load" value={load.chronic} max={loadScale} tone="neutral" />
            <div>42-day load {number(load.chronic)}</div>
          </div>
        )}
      </MetricTile>
      <MetricTile
        label="Garmin training status"
        value={wellness?.training_status ?? '–'}
        detail={wellness?.body_battery_at_wake ? `Body battery at wake ${wellness.body_battery_at_wake} of 100` : undefined}
      >
        {wellness?.body_battery_at_wake != null && (
          <Meter label="Body battery at wake" value={wellness.body_battery_at_wake} />
        )}
      </MetricTile>
    </div>
  )
}

function PageHeading({ today }: { today: string }) {
  const calendar = useWeekCalendar(today)
  const plan = calendar.data?.plans.find((p) => p.start_date <= today && today <= p.end_date)
  return (
    <header>
      <h1 className="text-2xl font-semibold tracking-tight text-primary">{longDay(today)}</h1>
      {plan && <p className="mt-0.5 text-sm text-muted">{plan.title}</p>}
    </header>
  )
}

type Prompt = { key: string; kind: PromptKind; entry: ToLog }

const KIND_ORDER: PromptKind[] = ['rating', 'fuel']

function prompts(entries: ToLog[]): Prompt[] {
  return entries.flatMap((entry) => entry.asks.map((kind) => ({ key: `${kind}:${entry.activity.id}`, kind, entry })))
}

function newestFirst(a: Prompt, b: Prompt): number {
  const byStart = b.entry.activity.start_time_local.localeCompare(a.entry.activity.start_time_local)
  return byStart || KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind)
}

function SessionsToLog({ entries }: { entries: ToLog[] }) {
  const queryClient = useQueryClient()
  const [started, setStarted] = useState<Prompt[]>([])
  const [skipped, setSkipped] = useState<string[]>([])
  const skip = useMutation({
    mutationFn: (prompt: Prompt) => skipPrompt(prompt.entry.activity.id, prompt.kind),
    onSuccess: (_, prompt) => {
      setSkipped((keys) => [...keys, prompt.key])
      return queryClient.invalidateQueries({ queryKey: ['today'] })
    },
  })
  const waiting = prompts(entries).filter((prompt) => started.every((other) => other.key !== prompt.key))
  const shown = [...started, ...waiting].filter((prompt) => !skipped.includes(prompt.key)).sort(newestFirst)
  const keepWhileFilledIn = (prompt: Prompt) =>
    setStarted((kept) => (kept.some((other) => other.key === prompt.key) ? kept : [...kept, prompt]))
  if (shown.length === 0) return null
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {shown.map((prompt) => {
        const { activity, rating, fuel } = prompt.entry
        const name = activity.name ?? sentence(activity.type_key)
        const when = `${weekday(activity.start_time_local)}, ${duration(activity.duration_s)}`
        const common = {
          activityId: activity.id,
          onSaved: () => keepWhileFilledIn(prompt),
          onSkip: () => skip.mutate(prompt),
        }
        return prompt.kind === 'rating' ? (
          <RatingCard
            key={prompt.key}
            {...common}
            saved={rating}
            title={`How did ${name} feel?`}
            subtitle={`${when}. The coach reads this next to the heart rate numbers`}
          />
        ) : (
          <FuelCard
            key={prompt.key}
            {...common}
            durationS={activity.duration_s}
            saved={fuel}
            title={`What did you eat and drink on ${name}?`}
            subtitle={`${when}. The coach uses this to build toward race fueling`}
          />
        )
      })}
    </div>
  )
}

export function TodayPage() {
  const { data, error, isPending } = useQuery({
    queryKey: ['today'],
    queryFn: fetchToday,
  })
  if (isPending) return <p className="text-sm text-muted">Loading…</p>
  if (error) return <p className="text-sm text-critical">{error.message}</p>

  return (
    <div className="space-y-4">
      <PageHeading today={data.day} />
      <SessionsToLog entries={data.to_log} />
      <div className="grid gap-4 lg:grid-cols-5">
        <TodayPlan today={data.day} />
        <LatestCoachMessage />
      </div>
      <Recovery data={data} />
      <ThisWeek today={data.day} totals={data.week} />
      <RecentActivities activities={data.recent_activities} />
    </div>
  )
}
