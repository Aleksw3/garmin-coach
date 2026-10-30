import { useQuery } from '@tanstack/react-query'
import { fetchCalendar, fetchLatestCoach, fetchProposals, fetchToday, type Activity, type GroupTotals } from '../api'
import { Card } from '../components/Card'
import { CoachText } from '../components/ChatParts'
import { BaselineBadge, StatTile } from '../components/StatTile'
import { duration, hours, localToday, number, sentence, weekday } from '../format'
import { SPORT_GROUPS, displayGroup, groupColor, groupLabel, useTheme } from '../theme'

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
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.sport_group} className="flex items-center gap-3 text-sm">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ background: groupColor(theme, row.sport_group) }}
            aria-hidden
          />
          <span className="flex-1 text-secondary">{groupLabel(row.sport_group)}</span>
          <span className="tabular text-primary">{hours(row.hours)}</span>
          <span className="tabular w-20 text-right text-secondary">
            {row.distance_km > 0 ? `${number(row.distance_km, 1)} km` : ''}
          </span>
          <span className="tabular w-16 text-right text-secondary">
            {row.elevation_gain_m > 0 ? `${number(row.elevation_gain_m)} m` : ''}
          </span>
        </li>
      ))}
    </ul>
  )
}

function ActivityRow({ activity }: { activity: Activity }) {
  const theme = useTheme()
  const details = [
    duration(activity.duration_s),
    activity.distance_km ? `${number(activity.distance_km, 1)} km` : null,
    activity.elevation_gain_m ? `${number(activity.elevation_gain_m)} m up` : null,
    activity.avg_hr ? `${number(activity.avg_hr)} bpm` : null,
    activity.terrain && activity.terrain !== 'unknown' ? activity.terrain : null,
  ].filter(Boolean)
  return (
    <li>
      <a href={`#activity/${activity.id}`} className="-mx-2 flex gap-3 rounded-lg px-2 py-2 hover:bg-raised">
      <span
        className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-sm"
        style={{ background: groupColor(theme, activity.sport_group) }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex justify-between gap-2 text-sm">
          <span className="truncate text-primary">{activity.name ?? sentence(activity.type_key)}</span>
          <span className="shrink-0 text-xs text-muted">{weekday(activity.start_time_local)}</span>
        </div>
        <div className="text-xs text-secondary">
          {groupLabel(activity.sport_group)} · {details.join(' · ')}
          {activity.training_load !== null && ` · load ${number(activity.training_load)}`}
        </div>
      </div>
      </a>
    </li>
  )
}

function TodayPlan() {
  const today = localToday()
  const calendar = useQuery({ queryKey: ['calendar', today, today], queryFn: () => fetchCalendar(today, today) })
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: fetchProposals })
  const sessions = calendar.data?.sessions ?? []
  const waiting = proposals.data?.length ?? 0
  return (
    <Card title="Today's plan">
      {sessions.length === 0 && <p className="text-sm text-muted">Nothing planned today.</p>}
      <ul className="space-y-2">
        {sessions.map((session) => (
          <li key={session.id} className="text-sm">
            <span className="font-semibold text-primary">{session.title}</span>
            <span className="text-secondary">
              {[
                session.duration_min ? `${number(session.duration_min)} min` : null,
                session.elevation_gain_m ? `${number(session.elevation_gain_m)} m up` : null,
                session.intensity,
              ]
                .filter(Boolean)
                .map((part) => `, ${part}`)
                .join('')}
            </span>
            {session.match && <span className="ml-2 text-xs text-secondary">✓ Done</span>}
            {session.description && <p className="mt-0.5 text-xs whitespace-pre-wrap text-muted">{session.description}</p>}
          </li>
        ))}
      </ul>
      {waiting > 0 && (
        <a href="#plan" className="mt-3 block text-xs text-accent">
          {waiting === 1 ? '1 plan proposal is' : `${waiting} plan proposals are`} waiting for you
        </a>
      )}
    </Card>
  )
}

function LatestCoachMessage() {
  const latest = useQuery({ queryKey: ['coach-latest'], queryFn: fetchLatestCoach })
  if (!latest.data) return null
  return (
    <Card title="From your coach" subtitle={latest.data.label ?? undefined}>
      <div className="max-h-64 overflow-hidden">
        <CoachText text={latest.data.text} />
      </div>
      <a href="#chat" className="mt-2 block text-xs text-accent">
        Open in Chat
      </a>
    </Card>
  )
}

export function TodayPage() {
  const { data, error, isPending } = useQuery({ queryKey: ['today'], queryFn: fetchToday })
  if (isPending) return <p className="text-sm text-muted">Loading…</p>
  if (error) return <p className="text-sm text-critical">{error.message}</p>

  const wellness = data.wellness
  const sleptToday = wellness?.sleep_day === data.day
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <TodayPlan />
        <LatestCoachMessage />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile
          label="Readiness"
          value={number(wellness?.readiness_score)}
          detail={sentence(wellness?.readiness_level)}
        />
        <StatTile
          label={sleptToday ? 'Sleep last night' : `Sleep (${wellness?.sleep_day ? weekday(wellness.sleep_day) : '–'})`}
          value={hours(wellness?.sleep_h)}
          detail={wellness?.sleep_score ? `Score ${wellness.sleep_score}` : undefined}
        />
        <StatTile
          label="HRV, 7-day mean"
          value={data.hrv ? `${number(data.hrv.rolling)} ms` : '–'}
          detail={
            data.hrv ? (
              <>
                <BaselineBadge status={data.hrv.status} />
                <div className="text-muted">
                  Range {number(data.hrv.low)} to {number(data.hrv.high)} ms, last night{' '}
                  {number(wellness?.hrv_last_night)}
                </div>
              </>
            ) : (
              'Needs 30 nights of data'
            )
          }
        />
        <StatTile
          label="Resting heart rate"
          value={wellness?.resting_hr ? `${wellness.resting_hr} bpm` : '–'}
          detail={data.resting_hr ? <BaselineBadge status={data.resting_hr.status} /> : undefined}
        />
        <StatTile
          label="Training load"
          value={data.load ? number(data.load.acute) : '–'}
          detail={data.load ? `Acute (7-day). Chronic (42-day) ${number(data.load.chronic)}` : undefined}
        />
        <StatTile
          label="Garmin training status"
          value={wellness?.training_status ?? '–'}
          detail={
            wellness?.body_battery_at_wake ? `Body battery at wake ${wellness.body_battery_at_wake}` : undefined
          }
        />
      </div>

      <Card title="This week" subtitle="Time, distance and climbing per sport since Monday">
        <WeekSummary week={data.week} />
      </Card>

      <Card title="Recent activities">
        {data.recent_activities.length === 0 ? (
          <p className="text-sm text-muted">No activities yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {data.recent_activities.map((activity) => (
              <ActivityRow key={activity.id} activity={activity} />
            ))}
          </ul>
        )}
      </Card>

    </div>
  )
}
