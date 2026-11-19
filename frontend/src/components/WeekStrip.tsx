import type { Activity, PlannedSession } from '../api'
import { addDays, clock, duration, mondayOf, sentence } from '../format'
import { groupColor, useTheme } from '../theme'

const COLUMN_HEIGHT_PX = 72
const SMALLEST_BLOCK_PX = 5
const SHORTEST_FULL_SCALE_MIN = 60

type Day = { date: string; done: Activity[]; open: PlannedSession[]; rest: boolean }

function weekDays(today: string, sessions: PlannedSession[], activities: Activity[]): Day[] {
  const monday = mondayOf(today)
  return Array.from({ length: 7 }, (_, index) => {
    const date = addDays(monday, index)
    const planned = sessions.filter((session) => session.day === date)
    return {
      date,
      done: activities.filter((activity) => activity.start_time_local.slice(0, 10) === date),
      open: planned.filter((session) => session.sport !== 'rest' && !session.match && !session.skipped),
      rest: planned.some((session) => session.sport === 'rest'),
    }
  })
}

function minutes(day: Day): number {
  const done = day.done.reduce((sum, activity) => sum + (activity.duration_s ?? 0) / 60, 0)
  const open = day.open.reduce((sum, session) => sum + (session.duration_min ?? 0), 0)
  return done + open
}

type Props = {
  today: string
  sessions: PlannedSession[]
  activities: Activity[]
  onOpenSession: (id: number) => void
}

export function WeekStrip({ today, sessions, activities, onOpenSession }: Props) {
  const theme = useTheme()
  const days = weekDays(today, sessions, activities)
  const fullScale = Math.max(SHORTEST_FULL_SCALE_MIN, ...days.map(minutes))
  const height = (blockMinutes: number) =>
    Math.max(SMALLEST_BLOCK_PX, (blockMinutes / fullScale) * COLUMN_HEIGHT_PX)
  return (
    <ol className="grid grid-cols-7 gap-1 sm:gap-2">
      {days.map((day) => {
        const isToday = day.date === today
        const doneSeconds = day.done.reduce((sum, activity) => sum + (activity.duration_s ?? 0), 0)
        const weekdayName = new Date(`${day.date}T00:00:00Z`).toLocaleDateString('en-GB', {
          weekday: 'short',
          timeZone: 'UTC',
        })
        return (
          <li key={day.date} className="flex min-w-0 flex-col items-center gap-1.5">
            <div
              className="flex w-full max-w-10 flex-col-reverse gap-0.5"
              style={{ height: COLUMN_HEIGHT_PX }}
            >
              {day.done.map((activity) => (
                <a
                  key={activity.id}
                  href={`#activity/${activity.id}`}
                  title={`${activity.name ?? sentence(activity.type_key)}, ${duration(activity.duration_s)}`}
                  className="block w-full shrink-0 rounded-sm hover:opacity-80"
                  style={{
                    height: height((activity.duration_s ?? 0) / 60),
                    background: groupColor(theme, activity.sport_group),
                  }}
                />
              ))}
              {day.open.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => onOpenSession(session.id)}
                  title={`Planned: ${session.title}`}
                  aria-label={`Planned: ${session.title}`}
                  className="block w-full shrink-0 rounded-sm border border-dashed hover:bg-raised"
                  style={{
                    height: height(session.duration_min ?? 0),
                    borderColor: day.date < today ? theme.textMuted : groupColor(theme, session.sport),
                  }}
                />
              ))}
            </div>
            <div
              className={`rounded-md px-1.5 py-0.5 text-xs ${isToday ? 'bg-accent font-semibold text-white' : 'text-secondary'}`}
            >
              {weekdayName}
            </div>
            <div className="tabular h-4 text-xs text-muted">
              {doneSeconds > 0 ? clock(doneSeconds) : day.rest && day.open.length === 0 ? 'Rest' : ''}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
