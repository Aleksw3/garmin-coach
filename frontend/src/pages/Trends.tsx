import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { fetchTrends, type Trends } from '../api'
import {
  MUSCLES,
  hrvOption,
  loadOption,
  strengthOption,
  sumByWeekAndGroup,
  weekLabels,
  weeklyStackOption,
} from '../charts'
import { Card, DataTable, TableToggle } from '../components/Card'
import { Chart } from '../components/Chart'
import { ZoneTimeCard, ZonesCard } from '../components/Zones'
import { addDays, number, sentence, shortDate } from '../format'
import { SPORT_GROUPS, useTheme } from '../theme'

const RANGES = [4, 12, 26, 52]
const ALL_GROUPS = SPORT_GROUPS.map((g) => g.key as string)
const CLIMBING_GROUPS = ['run', 'vertical', 'ski']

function groupTable(trends: Trends, weeks: string[], metric: 'hours' | 'elevation_gain_m', groups: string[]) {
  const sums = sumByWeekAndGroup(trends.weekly_totals, metric)
  const shown = SPORT_GROUPS.filter((g) => groups.includes(g.key))
  return {
    columns: ['Week from', ...shown.map((g) => g.label)],
    rows: weeks.map((week) => [
      shortDate(week),
      ...shown.map((g) => number(sums.get(week)?.get(g.key) ?? 0, metric === 'hours' ? 1 : 0)),
    ]),
  }
}

function isInWeek(day: string, weekStart: string): boolean {
  return day >= weekStart && day < addDays(weekStart, 7)
}

function weeklyAverages(values: { day: string; value: number | null }[], weeks: string[]) {
  return weeks.map((week) => {
    const inWeek = values.filter((v) => v.value !== null && isInWeek(v.day, week))
    const mean = inWeek.length ? inWeek.reduce((sum, v) => sum + (v.value ?? 0), 0) / inWeek.length : null
    return { week, mean }
  })
}

function TrendCharts({ trends, weeksShown }: { trends: Trends; weeksShown: number }) {
  const theme = useTheme()
  const weeks = useMemo(() => weekLabels(trends), [trends])
  const options = useMemo(
    () => ({
      hours: weeklyStackOption(theme, weeks, trends.weekly_totals, 'hours', ALL_GROUPS, 'h'),
      climbing: weeklyStackOption(
        theme,
        weeks,
        trends.weekly_totals,
        'elevation_gain_m',
        CLIMBING_GROUPS,
        'm',
      ),
      load: loadOption(theme, trends.load),
      hrv: hrvOption(theme, trends.hrv),
      strength: strengthOption(theme, weeks, trends),
    }),
    [theme, weeks, trends],
  )
  const strengthByWeek = new Map(trends.strength_weeks.map((w) => [w.week_start, w.sets_per_muscle]))

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Training time per week" subtitle="Hours by sport, bike commutes shown separately">
        <Chart option={options.hours} label="Stacked weekly training hours by sport" />
        <TableToggle {...groupTable(trends, weeks, 'hours', ALL_GROUPS)} />
      </Card>

      <ZonesCard />
      <ZoneTimeCard weeks={weeksShown} />

      <Card title="Climbing per week" subtitle="Metres of ascent from running, hiking and skiing">
        <Chart option={options.climbing} label="Stacked weekly elevation gain" />
        <TableToggle {...groupTable(trends, weeks, 'elevation_gain_m', CLIMBING_GROUPS)} />
      </Card>

      <Card
        title="Training load"
        subtitle="Garmin load per day with 7-day (acute) and 42-day (chronic) averages"
      >
        <Chart option={options.load} label="Daily training load with acute and chronic averages" />
        <TableToggle
          columns={['Week from', 'Load', 'Acute at week end', 'Chronic at week end']}
          rows={weeks.map((week) => {
            const days = trends.load.filter((d) => isInWeek(d.day, week))
            const last = days[days.length - 1]
            return [
              shortDate(week),
              number(days.reduce((sum, d) => sum + d.load, 0)),
              number(last?.acute),
              number(last?.chronic),
            ]
          })}
        />
      </Card>

      <Card
        title="Heart rate variability"
        subtitle="Nightly HRV, its 7-day mean, and the normal range from the last 60 nights"
      >
        <Chart option={options.hrv} label="Nightly HRV with 7-day mean and normal range" />
        <TableToggle
          columns={['Week from', 'Mean nightly HRV (ms)']}
          rows={weeklyAverages(trends.hrv, weeks).map((w) => [shortDate(w.week), number(w.mean)])}
        />
      </Card>

      <Card
        title="Running weeks"
        subtitle="Terrain from climb per km: flat under 10 m, rolling 10 to 25 m, mountain above. Descent on foot counts hikes too, and a week with 1000 m or more that is 1.5 times the 4 weeks before is marked as a jump, which is a rule of thumb"
        className="lg:col-span-2">
        <DataTable
          columns={['Week from', 'Runs', 'km', 'Hours', 'm up', 'm down', 'Longest', 'Flat h', 'Rolling h', 'Mountain h', 'Back-to-back long days', 'Descent on foot', 'Biggest descent']}
          rows={trends.run_weeks.map((w) => [
            shortDate(w.week_start),
            w.runs,
            number(w.distance_km, 1),
            number(w.hours, 1),
            number(w.elevation_gain_m),
            number(w.elevation_loss_m),
            `${number(w.longest_run_h, 1)} h`,
            number(w.flat_h, 1),
            number(w.rolling_h, 1),
            number(w.mountain_h, 1),
            w.back_to_back_long_days,
            w.descent_jump && w.descent_ratio !== null
              ? `${number(w.descent_on_foot_m)} m, jump of ${number(w.descent_ratio, 1)} times`
              : `${number(w.descent_on_foot_m)} m`,
            `${number(w.biggest_descent_m)} m`,
          ])}
        />
      </Card>

      <Card title="Strength volume" subtitle="Hard sets per muscle group per week, secondary muscles count half">
        <Chart option={options.strength} height={320} label="Heatmap of weekly hard sets per muscle group" />
        <TableToggle
          columns={['Week from', ...MUSCLES.map((m) => sentence(m))]}
          rows={weeks.map((week) => [
            shortDate(week),
            ...MUSCLES.map((m) => number(strengthByWeek.get(week)?.[m] ?? 0, 1)),
          ])}
        />
      </Card>

      <Card title="Estimated one-rep max" subtitle="Best Epley estimate per exercise in this period, sets of 12 reps or fewer">
        {trends.one_rep_max.length === 0 ? (
          <p className="text-sm text-muted">No weighted sets in this period.</p>
        ) : (
          <DataTable
            columns={['Exercise', 'Estimate', 'Date']}
            rows={trends.one_rep_max.map((r) => [sentence(r.exercise), `${number(r.kg, 1)} kg`, shortDate(r.day)])}
          />
        )}
      </Card>
    </div>
  )
}

export function TrendsPage() {
  const [weeks, setWeeks] = useState(12)
  const { data, error, isPending, isFetching } = useQuery({
    queryKey: ['trends', weeks],
    queryFn: () => fetchTrends(weeks),
  })
  return (
    <div className="space-y-4">
      <div className="flex gap-2" role="group" aria-label="Time range">
        {RANGES.map((range) => (
          <button
            key={range}
            type="button"
            onClick={() => setWeeks(range)}
            aria-pressed={weeks === range}
            className={`rounded-lg border px-3 py-1.5 text-sm ${
              weeks === range
                ? 'border-accent bg-raised font-semibold text-primary'
                : 'border-line text-secondary hover:bg-raised'
            }`}
          >
            {range} weeks
          </button>
        ))}
      </div>
      {isPending && <p className="text-sm text-muted">Loading…</p>}
      {error && <p className="text-sm text-critical">{error.message}</p>}
      {data && (
        <div className={isFetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
          <TrendCharts trends={data} weeksShown={weeks} />
        </div>
      )}
    </div>
  )
}
