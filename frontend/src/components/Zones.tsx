import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import {
  addThresholdTest,
  deleteThresholdTest,
  fetchZoneWeeks,
  fetchZones,
  type ThresholdMethod,
  type Zones,
} from '../api'
import { zoneColor, zoneLabel, zoneWeeksOption } from '../charts'
import { localToday, number, shortDate } from '../format'
import { useTheme } from '../theme'
import { Card, TableToggle } from './Card'
import { Chart } from './Chart'

const METHODS: Record<ThresholdMethod, string> = {
  drift_test: 'Heart rate drift test',
  lab: 'Lab test',
  time_trial: 'Time trial',
  estimate: 'Estimate',
}

const ZONE_PURPOSE = [
  'Recovery and warm-up',
  'Aerobic base, most of the volume',
  'Tempo, between the thresholds',
  'Threshold, around LT2',
  'Short and hard intervals',
]

const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'

function TestForm({ zones, onDone }: { zones: Zones; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState({
    day: localToday(),
    lt1_hr: zones.current?.lt1_hr.toString() ?? '',
    lt2_hr: zones.current?.lt2_hr.toString() ?? '',
    method: 'drift_test' as ThresholdMethod,
    notes: '',
  })
  const save = useMutation({
    mutationFn: () =>
      addThresholdTest({
        day: values.day,
        lt1_hr: Number(values.lt1_hr),
        lt2_hr: Number(values.lt2_hr),
        method: values.method,
        notes: values.notes.trim() || null,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['zones'] })
      onDone()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <label className="text-xs text-muted">
        <span className="mb-1 block">LT1 (bpm)</span>
        <input
          type="number"
          required
          min={80}
          max={220}
          className={input}
          value={values.lt1_hr}
          onChange={(e) => setValues({ ...values, lt1_hr: e.target.value })}
        />
      </label>
      <label className="text-xs text-muted">
        <span className="mb-1 block">LT2 (bpm)</span>
        <input
          type="number"
          required
          min={80}
          max={230}
          className={input}
          value={values.lt2_hr}
          onChange={(e) => setValues({ ...values, lt2_hr: e.target.value })}
        />
      </label>
      <label className="text-xs text-muted">
        <span className="mb-1 block">Date</span>
        <input
          type="date"
          required
          className={input}
          value={values.day}
          onChange={(e) => setValues({ ...values, day: e.target.value })}
        />
      </label>
      <label className="text-xs text-muted">
        <span className="mb-1 block">Method</span>
        <select
          className={input}
          value={values.method}
          onChange={(e) => setValues({ ...values, method: e.target.value as ThresholdMethod })}
        >
          {Object.entries(METHODS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="col-span-2 text-xs text-muted sm:col-span-4">
        <span className="mb-1 block">Notes, for example treadmill 10.5 km/h at 1%, drift 3.2%</span>
        <input className={input} value={values.notes} onChange={(e) => setValues({ ...values, notes: e.target.value })} />
      </label>
      <div className="col-span-2 flex items-center gap-3 sm:col-span-4">
        <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
          Save
        </button>
        <button type="button" onClick={onDone} className="text-sm text-secondary">
          Cancel
        </button>
        {save.error && <span className="text-xs text-critical">{save.error.message}</span>}
      </div>
    </form>
  )
}

function ZoneLadder({ zones }: { zones: Zones }) {
  const theme = useTheme()
  return (
    <ol className="space-y-1.5">
      {[...zones.zones].reverse().map((zone) => (
        <li key={zone.number} className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 rounded-lg bg-raised px-3 py-2">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md text-xs font-semibold"
            style={{ background: zoneColor(theme, zone.number), color: zone.number > 2 ? theme.surface : theme.textPrimary }}
          >
            Z{zone.number}
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-semibold text-primary">{zone.name}</span>
            <span className="block text-xs text-muted">{ZONE_PURPOSE[zone.number - 1]}</span>
          </span>
          <span className="tabular text-sm font-semibold text-primary">{zoneLabel(zone)} bpm</span>
        </li>
      ))}
    </ol>
  )
}

export function ZonesCard() {
  const queryClient = useQueryClient()
  const zones = useQuery({ queryKey: ['zones'], queryFn: fetchZones })
  const [editing, setEditing] = useState(false)
  const remove = useMutation({
    mutationFn: deleteThresholdTest,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['zones'] }),
  })
  const data = zones.data
  const current = data?.current
  return (
    <Card
      title="Heart rate zones"
      subtitle="Uphill Athlete's five zones from your LT1 and LT2. Zone 2 ends at LT1, zone 3 at LT2."
    >
      {data && !current && !editing && (
        <div className="space-y-3 text-sm text-secondary">
          <p>
            Add your LT1 and LT2 heart rates to see your zones, time in zone and zone targets in the plan. A heart
            rate drift test gives LT1.
          </p>
          <button type="button" onClick={() => setEditing(true)} className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
            Add LT1 and LT2
          </button>
        </div>
      )}
      {data && current && !editing && (
        <div className="space-y-3">
          <ZoneLadder zones={data} />
          <p className="text-xs text-muted">
            LT1 {current.lt1_hr} and LT2 {current.lt2_hr} bpm, {METHODS[current.method].toLowerCase()} on{' '}
            {shortDate(current.day)}. Zone 1 ends at 90% of LT1 and zone 4 at 5% above LT2.
          </p>
          {data.retest_due && (
            <p className="text-xs text-secondary">
              That test is more than 8 weeks old. Thresholds move with fitness, so test again to keep the zones right.
            </p>
          )}
          <button type="button" onClick={() => setEditing(true)} className="text-sm text-accent">
            Add a new test
          </button>
        </div>
      )}
      {data && editing && <TestForm zones={data} onDone={() => setEditing(false)} />}
      {data && data.tests.length > 0 && (
        <details className="mt-3 text-xs text-muted">
          <summary className="cursor-pointer select-none">Test history ({data.tests.length})</summary>
          <ul className="mt-2 space-y-1">
            {data.tests.map((test) => (
              <li key={test.id} className="flex flex-wrap items-baseline gap-x-3 text-secondary">
                <span className="tabular">{shortDate(test.day)}</span>
                <span>
                  LT1 {test.lt1_hr}, LT2 {test.lt2_hr}
                </span>
                <span className="text-muted">{METHODS[test.method]}</span>
                {test.notes && <span className="text-muted">{test.notes}</span>}
                <button
                  type="button"
                  onClick={() => window.confirm('Delete this test?') && remove.mutate(test.id)}
                  className="text-muted hover:text-critical"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      {zones.error && <p className="text-sm text-critical">{zones.error.message}</p>}
    </Card>
  )
}

export function ZoneTimeCard({ weeks }: { weeks: number }) {
  const theme = useTheme()
  const [sports, setSports] = useState<'running' | 'all'>('running')
  const zones = useQuery({ queryKey: ['zones'], queryFn: fetchZones })
  const zoneWeeks = useQuery({
    queryKey: ['zone-weeks', weeks, sports],
    queryFn: () => fetchZoneWeeks(weeks, sports),
    enabled: Boolean(zones.data?.current),
  })
  const option = useMemo(
    () => (zones.data && zoneWeeks.data ? zoneWeeksOption(theme, zoneWeeks.data, zones.data.zones) : null),
    [theme, zones.data, zoneWeeks.data],
  )
  if (!zones.data?.current) return null
  const totals = [0, 1, 2, 3, 4].map((index) =>
    (zoneWeeks.data ?? []).reduce((sum, week) => sum + week.seconds[index], 0),
  )
  const all = totals.reduce((sum, value) => sum + value, 0)
  const easy = all > 0 ? (100 * (totals[0] + totals[1])) / all : null
  return (
    <Card
      title="Time in zones per week"
      subtitle={
        easy === null
          ? 'Hours in each of your zones'
          : `${number(easy)}% of the time in zone 1 and 2 over these ${weeks} weeks`
      }
    >
      <div className="mb-2 flex gap-2 text-xs" role="group" aria-label="Sports">
        {(['running', 'all'] as const).map((choice) => (
          <button
            key={choice}
            type="button"
            onClick={() => setSports(choice)}
            aria-pressed={sports === choice}
            className={`rounded-lg border px-2 py-1 ${sports === choice ? 'border-accent bg-raised text-primary' : 'border-line text-secondary'}`}
          >
            {choice === 'running' ? 'Running and hiking' : 'All except commutes'}
          </button>
        ))}
      </div>
      {option && <Chart option={option} label="Stacked weekly hours in each heart rate zone" />}
      {zoneWeeks.data && (
        <TableToggle
          columns={['Week from', ...zones.data.zones.map((zone) => `Z${zone.number} h`)]}
          rows={zoneWeeks.data.map((week) => [
            shortDate(week.week_start),
            ...week.seconds.map((seconds) => number(seconds / 3600, 1)),
          ])}
        />
      )}
    </Card>
  )
}
