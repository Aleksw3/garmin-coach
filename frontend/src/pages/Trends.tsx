import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { fetchTrends, fetchZones, type GroupTotals, type RunWeek, type Trends } from '../api'
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
import { MetricTile } from '../components/Metric'
import { ZoneTimeCard, ZonesCard } from '../components/Zones'
import { addDays, number, sentence, shortDate } from '../format'
import { SPORT_GROUPS, displayGroup, useTheme } from '../theme'

const RANGES = [4, 12, 26, 52]
const LONGEST_RANGE_WEEKS = 104
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

const ON_FOOT_GROUPS = ['run', 'vertical']

type Average = { label: string; unit: string; digits: number; groups: string[]; metric: keyof GroupTotals }

const AVERAGES: Average[] = [
  { label: 'Training time per week', unit: 'h', digits: 1, groups: ALL_GROUPS.filter((g) => g !== 'commute'), metric: 'hours' },
  { label: 'Distance on foot per week', unit: 'km', digits: 1, groups: ON_FOOT_GROUPS, metric: 'distance_km' },
  { label: 'Climbing per week', unit: 'm', digits: 0, groups: CLIMBING_GROUPS, metric: 'elevation_gain_m' },
]

function weeklyAverage(totals: GroupTotals[], average: Average, firstWeek: string, weeks: number): number {
  const lastWeek = addDays(firstWeek, (weeks - 1) * 7)
  const sum = totals
    .filter((row) => row.week_start >= firstWeek && row.week_start <= lastWeek)
    .filter((row) => average.groups.includes(displayGroup(row.sport_group)))
    .reduce((total, row) => total + (row[average.metric] as number), 0)
  return sum / weeks
}

function PeriodAverages({ trends, weeksShown }: { trends: Trends; weeksShown: number }) {
  const before = useQuery({
    queryKey: ['trends', weeksShown * 2],
    queryFn: () => fetchTrends(weeksShown * 2),
    enabled: weeksShown * 2 <= LONGEST_RANGE_WEEKS,
  })
  const weeksBefore = before.data ? before.data.first_week : null
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {AVERAGES.map((average) => {
        const now = weeklyAverage(trends.weekly_totals, average, trends.first_week, weeksShown)
        const earlier =
          before.data && weeksBefore
            ? weeklyAverage(before.data.weekly_totals, average, weeksBefore, weeksShown)
            : null
        const change = earlier === null ? null : now - earlier
        return (
          <MetricTile
            key={average.label}
            label={average.label}
            value={number(now, average.digits)}
            unit={average.unit}
            detail={
              change === null ? undefined : (
                <>
                  <span aria-hidden>{change > 0 ? '▲' : change < 0 ? '▼' : '●'}</span>{' '}
                  {number(Math.abs(change), average.digits)} {average.unit} {change < 0 ? 'less' : 'more'} than the{' '}
                  {weeksShown} weeks before
                </>
              )
            }
          />
        )
      })}
    </div>
  )
}

function BarCell({ value, longest, text }: { value: number; longest: number; text: string }) {
  return (
    <td className="py-1 pr-3 whitespace-nowrap">
      <span className="flex items-center gap-2">
        <span className="w-10 text-right">{text}</span>
        <span className="h-1.5 w-16 rounded-full bg-raised" aria-hidden>
          <span
            className="block h-full rounded-full bg-accent"
            style={{ width: longest > 0 ? `${(value / longest) * 100}%` : 0 }}
          />
        </span>
      </span>
    </td>
  )
}

const RUN_WEEK_COLUMNS = ['Week from', 'Runs', 'km', 'Hours', 'm up', 'm down', 'Longest', 'Flat h', 'Rolling h', 'Mountain h', 'Back-to-back long days', 'Descent on foot', 'Biggest descent']

function RunWeeksTable({ weeks }: { weeks: RunWeek[] }) {
  const longest = (pick: (week: RunWeek) => number) => Math.max(0, ...weeks.map(pick))
  const mostKm = longest((w) => w.distance_km)
  const mostHours = longest((w) => w.hours)
  const mostClimb = longest((w) => w.elevation_gain_m)
  const plain = 'py-1 pr-3 whitespace-nowrap'
  return (
    <div className="overflow-x-auto">
      <table className="tabular w-full text-left text-xs">
        <thead>
          <tr className="text-muted">
            {RUN_WEEK_COLUMNS.map((column) => (
              <th key={column} className="py-1 pr-3 font-medium whitespace-nowrap">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((w) => (
            <tr key={w.week_start} className="border-t border-line text-secondary">
              <td className={plain}>{shortDate(w.week_start)}</td>
              <td className={plain}>{w.runs}</td>
              <BarCell value={w.distance_km} longest={mostKm} text={number(w.distance_km, 1)} />
              <BarCell value={w.hours} longest={mostHours} text={number(w.hours, 1)} />
              <BarCell value={w.elevation_gain_m} longest={mostClimb} text={number(w.elevation_gain_m)} />
              <td className={plain}>{number(w.elevation_loss_m)}</td>
              <td className={plain}>{number(w.longest_run_h, 1)} h</td>
              <td className={plain}>{number(w.flat_h, 1)}</td>
              <td className={plain}>{number(w.rolling_h, 1)}</td>
              <td className={plain}>{number(w.mountain_h, 1)}</td>
              <td className={plain}>{w.back_to_back_long_days}</td>
              <td className={plain}>
                {number(w.descent_on_foot_m)} m
                {w.descent_jump && w.descent_ratio !== null && (
                  <span className="ml-2 text-primary">
                    <span className="text-warning" aria-hidden>
                      ▲
                    </span>{' '}
                    jump of {number(w.descent_ratio, 1)} times
                  </span>
                )}
              </td>
              <td className={plain}>{number(w.biggest_descent_m)} m</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TrendCharts({ trends, weeksShown }: { trends: Trends; weeksShown: number }) {
  const theme = useTheme()
  const zones = useQuery({ queryKey: ['zones'], queryFn: fetchZones })
  const hasZones = Boolean(zones.data?.current)
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

      <ZonesCard className={hasZones ? undefined : 'lg:col-span-2'} />
      <ZoneTimeCard weeks={weeksShown} />

      <Card
        title="Running weeks"
        subtitle="Terrain from climb per km: flat under 10 m, rolling 10 to 25 m, mountain above. Descent on foot counts hikes too, and a week with 1000 m or more that is 1.5 times the 4 weeks before is marked as a jump, which is a rule of thumb"
        className="lg:col-span-2">
        <RunWeeksTable weeks={trends.run_weeks} />
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

      <Card
        title="Estimated one-rep max"
        subtitle="Best Epley estimate per exercise in this period, sets of 12 reps or fewer"
        className={trends.one_rep_max.length === 0 ? 'self-start' : undefined}
      >
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
            className={`rounded-lg border px-3 py-1.5 text-sm whitespace-nowrap ${
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
          <div className="space-y-4">
            <PeriodAverages trends={data} weeksShown={weeks} />
            <TrendCharts trends={data} weeksShown={weeks} />
          </div>
        </div>
      )}
    </div>
  )
}
