import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  addThresholdTest,
  editSet,
  fetchActivity,
  fetchZones,
  restoreSet,
  setElevation,
  type ActivityDetail,
  type StrengthSetRow,
} from '../api'
import { Card, DataTable } from '../components/Card'
import { FuelCard } from '../components/FuelCard'
import { RatingCard } from '../components/RatingCard'
import { Meter, MetricTile, RangeTrack, type Tone } from '../components/Metric'
import { duration, number, sentence } from '../format'
import { groupColor, groupLabel, useTheme } from '../theme'

const TARGET_LABELS: Record<string, [string, string]> = {
  duration_min: ['Duration', 'min'],
  distance_km: ['Distance', 'km'],
  elevation_gain_m: ['Climbing', 'm'],
  hard_min: ['Above LT1', 'min'],
}

function pace(speed: number | null): string {
  if (!speed) return '–'
  const seconds = 1000 / speed
  return `${Math.floor(seconds / 60)}:${Math.round(seconds % 60)
    .toString()
    .padStart(2, '0')}`
}

const HIGHEST_TRAINING_EFFECT = 5

function Stats({ activity }: { activity: ActivityDetail }) {
  const weather = [
    activity.feels_like_c !== null ? `feels like ${number(activity.feels_like_c)} °C` : null,
    activity.humidity_pct !== null ? `humidity ${number(activity.humidity_pct)}%` : null,
  ].filter((part) => part !== null)
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      <MetricTile
        label="Duration"
        value={duration(activity.duration_s)}
        detail={activity.moving_s ? `Moving ${duration(activity.moving_s)}` : undefined}
      />
      {activity.distance_km ? (
        <MetricTile label="Distance" value={number(activity.distance_km, 2)} unit="km" />
      ) : null}
      {activity.elevation_gain_m ? (
        <MetricTile
          label="Climbing"
          value={number(activity.elevation_gain_m)}
          unit="m"
          detail={`${number(activity.elevation_loss_m)} m down`}
        />
      ) : null}
      {activity.avg_hr ? (
        <MetricTile
          label="Heart rate"
          value={number(activity.avg_hr)}
          unit="bpm"
          detail={`Highest ${number(activity.max_hr)} bpm`}
        />
      ) : null}
      {activity.distance_km && activity.avg_speed_mps ? (
        <MetricTile
          label="Pace"
          value={pace(activity.avg_speed_mps)}
          unit="/km"
          detail={
            activity.avg_grade_adjusted_speed_mps
              ? `Grade-adjusted ${pace(activity.avg_grade_adjusted_speed_mps)} /km`
              : undefined
          }
        />
      ) : null}
      {activity.training_load !== null && (
        <MetricTile label="Training load" value={number(activity.training_load)}>
          {activity.aerobic_training_effect !== null && (
            <div className="space-y-1.5 text-xs text-secondary">
              <div className="flex items-center gap-2">
                <span className="w-20 shrink-0">Aerobic {number(activity.aerobic_training_effect, 1)}</span>
                <div className="flex-1">
                  <Meter
                    label="Aerobic training effect"
                    value={activity.aerobic_training_effect}
                    max={HIGHEST_TRAINING_EFFECT}
                  />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-20 shrink-0">Anaerobic {number(activity.anaerobic_training_effect, 1)}</span>
                <div className="flex-1">
                  <Meter
                    label="Anaerobic training effect"
                    value={activity.anaerobic_training_effect ?? 0}
                    max={HIGHEST_TRAINING_EFFECT}
                    tone="neutral"
                  />
                </div>
              </div>
            </div>
          )}
        </MetricTile>
      )}
      {activity.temperature_c !== null && (
        <MetricTile
          label="Temperature"
          value={number(activity.temperature_c)}
          unit="°C"
          detail={weather.length > 0 ? weather.join(', ').replace(/^./, (first) => first.toUpperCase()) : undefined}
        />
      )}
    </div>
  )
}

function Zones({ activity }: { activity: ActivityDetail }) {
  const own = activity.zones.filter((zone) => zone.kind === 'own')
  const zones = own.length > 0 ? own : activity.zones.filter((zone) => zone.kind === 'hr')
  const total = zones.reduce((sum, zone) => sum + zone.seconds, 0)
  if (total === 0) return null
  return (
    <Card
      title="Time in heart rate zones"
      subtitle={own.length > 0 ? 'Your zones from LT1 and LT2' : "Garmin's zones. Add LT1 and LT2 on Trends to use your own"}
    >
      <ul className="space-y-1.5">
        {zones.map((zone) => (
          <li key={zone.zone} className="flex items-center gap-3 text-xs">
            <span className="w-24 shrink-0 text-secondary">
              Zone {zone.zone}
              {zone.low_boundary ? <span className="text-muted"> from {number(zone.low_boundary)}</span> : null}
            </span>
            <span className="h-3 flex-1 overflow-hidden rounded-sm bg-raised">
              <span
                className="block h-full rounded-sm bg-accent"
                style={{ width: `${(100 * zone.seconds) / total}%` }}
              />
            </span>
            <span className="tabular w-24 shrink-0 text-right text-primary">
              {duration(zone.seconds)} <span className="text-muted">{number((100 * zone.seconds) / total)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

const CLOSE_TO_LT1_FROM_PCT = 3.5
const CLOSE_TO_LT1_TO_PCT = 5

function Drift({ activity }: { activity: ActivityDetail }) {
  const queryClient = useQueryClient()
  const zones = useQuery({ queryKey: ['zones'], queryFn: fetchZones })
  const [saved, setSaved] = useState(false)
  const lt1 = Math.round(activity.drift_first_hr ?? 0)
  const save = useMutation({
    mutationFn: () =>
      addThresholdTest({
        day: activity.start_time_local.slice(0, 10),
        lt1_hr: lt1,
        lt2_hr: zones.data?.current?.lt2_hr ?? 0,
        method: 'drift_test',
        activity_id: activity.id,
        notes: `Drift ${number(activity.hr_drift_pct, 1)}% after a 15 min warm-up`,
      }),
    onSuccess: async () => {
      setSaved(true)
      await queryClient.invalidateQueries({ queryKey: ['zones'] })
      await queryClient.invalidateQueries({ queryKey: ['activity', activity.id] })
    },
  })
  if (activity.hr_drift_pct === null || !['run', 'vertical'].includes(activity.sport_group)) return null
  const drift = activity.hr_drift_pct
  const verdict =
    drift < CLOSE_TO_LT1_FROM_PCT
      ? 'Under 3.5%: this pace was below LT1. Try a little faster next time.'
      : drift <= CLOSE_TO_LT1_TO_PCT
        ? '3.5 to 5%: this pace was close to LT1.'
        : 'Over 5%: this pace was above LT1, or the run was not steady.'
  const lt2 = zones.data?.current?.lt2_hr
  const tone: Tone = drift < CLOSE_TO_LT1_FROM_PCT ? 'neutral' : drift <= CLOSE_TO_LT1_TO_PCT ? 'good' : 'warning'
  return (
    <Card title="Heart rate drift" subtitle="First half against second half after a 15 min warm-up">
      <div className="flex items-baseline gap-3">
        <span className="tabular text-3xl font-semibold tracking-tight text-primary">{number(drift, 1)}%</span>
        <span className="tabular text-sm text-secondary">
          {number(activity.drift_first_hr)} bpm, then {number(activity.drift_second_hr)} bpm
        </span>
      </div>
      <div className="mt-3">
        <RangeTrack
          label="Drift against the 3.5 to 5% band that is close to LT1"
          low={CLOSE_TO_LT1_FROM_PCT}
          high={CLOSE_TO_LT1_TO_PCT}
          value={drift}
          tone={tone}
        />
      </div>
      <p className="mt-1.5 text-xs text-muted">
        The band is 3.5 to 5%, a pace close to LT1
        {activity.decoupling_pct !== null && `. Pace to heart rate changed ${number(activity.decoupling_pct, 1)}%`}
      </p>
      <p className="mt-3 text-sm text-secondary">{verdict}</p>
      <p className="mt-1 text-xs text-muted">
        Only meaningful for a steady pace on flat ground or a treadmill, like the LT1 test.
      </p>
      {drift >= 2 && drift <= 5 && lt2 !== undefined && lt1 < lt2 && !saved && (
        <button type="button" onClick={() => save.mutate()} className="mt-2 text-sm text-accent">
          Use as an LT1 test: LT1 {lt1} bpm, the first half average
        </button>
      )}
      {saved && <p className="mt-2 text-sm text-secondary">Saved. Your zones now use LT1 {lt1}.</p>}
      {save.error && <p className="mt-2 text-xs text-critical">{save.error.message}</p>}
    </Card>
  )
}

function Laps({ activity }: { activity: ActivityDetail }) {
  if (activity.laps.length < 2) return null
  return (
    <Card title="Laps" className="lg:col-span-2">
      <DataTable
        columns={['Lap', 'km', 'Time', 'Pace', 'Grade-adjusted', 'm up', 'm down', 'HR']}
        rows={activity.laps.map((lap) => [
          lap.lap_index,
          number((lap.distance_m ?? 0) / 1000, 2),
          duration(lap.duration_s),
          lap.avg_speed_mps ? `${pace(lap.avg_speed_mps)} /km` : '–',
          lap.avg_grade_adjusted_speed_mps ? `${pace(lap.avg_grade_adjusted_speed_mps)} /km` : '–',
          number(lap.elevation_gain_m),
          number(lap.elevation_loss_m),
          number(lap.avg_hr),
        ])}
      />
    </Card>
  )
}

function setText(row: StrengthSetRow): string {
  const name = sentence(row.exercise_name ?? row.exercise_category)
  const weight = row.weight_kg ? ` × ${number(row.weight_kg, 1)} kg` : ''
  return `${name}, ${row.reps ?? '?'} reps${weight}`
}

function SetEditor({
  activityId,
  row,
  categories,
  onDone,
}: {
  activityId: number
  row: StrengthSetRow
  categories: string[]
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [values, setValues] = useState({
    exercise_category: row.exercise_category ?? '',
    exercise_name: row.exercise_name ?? '',
    reps: row.reps?.toString() ?? '',
    weight_kg: row.weight_kg?.toString() ?? '',
  })
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['activity', activityId] })
    onDone()
  }
  const save = useMutation({
    mutationFn: (deleted: boolean) =>
      editSet(activityId, row.set_index, {
        exercise_category: values.exercise_category || null,
        exercise_name: values.exercise_name.trim().toUpperCase().replaceAll(' ', '_') || null,
        reps: values.reps ? Number(values.reps) : null,
        weight_kg: values.weight_kg ? Number(values.weight_kg) : null,
        deleted,
      }),
    onSuccess: refresh,
  })
  const restore = useMutation({ mutationFn: () => restoreSet(activityId, row.set_index), onSuccess: refresh })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate(false)
  }
  const input = 'w-full min-w-0 rounded-lg border border-line bg-page px-2 py-1 text-base text-primary sm:text-sm'
  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 py-2 sm:grid-cols-4">
      <label className="text-xs text-muted">
        Category
        <select
          className={input}
          value={values.exercise_category}
          onChange={(e) => setValues({ ...values, exercise_category: e.target.value })}
        >
          <option value="">Unknown</option>
          {[...new Set([...categories, row.original.exercise_category ?? ''])].filter(Boolean).map((category) => (
            <option key={category} value={category}>
              {sentence(category)}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-muted">
        Exercise
        <input
          className={input}
          value={values.exercise_name}
          onChange={(e) => setValues({ ...values, exercise_name: e.target.value })}
        />
      </label>
      <label className="text-xs text-muted">
        Reps
        <input
          type="number"
          className={input}
          value={values.reps}
          onChange={(e) => setValues({ ...values, reps: e.target.value })}
        />
      </label>
      <label className="text-xs text-muted">
        Weight (kg)
        <input
          type="number"
          step="0.5"
          className={input}
          value={values.weight_kg}
          onChange={(e) => setValues({ ...values, weight_kg: e.target.value })}
        />
      </label>
      <div className="col-span-2 flex flex-wrap gap-3 text-xs sm:col-span-4">
        <button type="submit" className="rounded-lg bg-accent px-3 py-1 font-semibold text-white">
          Save
        </button>
        <button type="button" onClick={onDone} className="text-secondary">
          Cancel
        </button>
        <button type="button" onClick={() => save.mutate(true)} className="text-muted hover:text-critical">
          Remove set
        </button>
        {row.edited && (
          <button type="button" onClick={() => restore.mutate()} className="text-accent">
            Restore what the watch recorded
          </button>
        )}
      </div>
    </form>
  )
}

function StrengthSets({ activity }: { activity: ActivityDetail }) {
  const [editing, setEditing] = useState<number | null>(null)
  if (activity.sets.length === 0) return null
  return (
    <Card
      title="Strength sets"
      subtitle="Fix sets the watch got wrong. Edits survive syncs and feed the strength trends."
      className="lg:col-span-2"
    >
      <ol className="divide-y divide-[var(--border)]">
        {activity.sets.map((row, index) => (
          <li key={row.set_index} className="py-1.5 text-sm">
            {editing === row.set_index ? (
              <SetEditor
                activityId={activity.id}
                row={row}
                categories={activity.exercise_categories}
                onDone={() => setEditing(null)}
              />
            ) : (
              <div className="flex items-center justify-between gap-3">
                <span className={row.deleted ? 'text-muted line-through' : 'text-primary'}>
                  <span className="tabular mr-2 text-xs text-muted">{index + 1}</span>
                  {setText(row)}
                  {row.edited && !row.deleted && <span className="ml-2 text-xs text-muted">edited</span>}
                </span>
                <button type="button" onClick={() => setEditing(row.set_index)} className="shrink-0 text-xs text-accent">
                  Edit
                </button>
              </div>
            )}
          </li>
        ))}
      </ol>
    </Card>
  )
}

function Planned({ planned }: { planned: NonNullable<ActivityDetail['planned']> }) {
  const targets = Object.entries(planned.details)
  return (
    <Card title={`Planned: ${planned.title}`} subtitle="How this activity compares with the planned session">
      {planned.compliance !== null ? (
        <div className="flex items-baseline gap-1.5">
          <span className="tabular text-3xl font-semibold tracking-tight text-primary">
            {number(planned.compliance)}%
          </span>
          <span className="text-sm text-secondary">of the targets</span>
        </div>
      ) : (
        <p className="text-sm text-primary">Done, the session had no targets</p>
      )}
      {targets.length > 0 && (
        <ul className="mt-3 space-y-2">
          {targets.map(([key, [target, actual]]) => {
            const [label, unit] = TARGET_LABELS[key] ?? [key, '']
            return (
              <li key={key} className="flex items-center gap-3 text-xs">
                <span className="w-20 shrink-0 text-secondary">{label}</span>
                <div className="flex-1">
                  <Meter label={`${label} done of the target`} value={actual} max={target} />
                </div>
                <span className="tabular w-28 shrink-0 text-right text-primary">
                  {number(actual, unit === 'km' ? 1 : 0)} of {number(target, unit === 'km' ? 1 : 0)} {unit}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function ClimbingCard({ activity }: { activity: ActivityDetail }) {
  const queryClient = useQueryClient()
  const [metres, setMetres] = useState<number | null>(activity.elevation_gain_override_m)
  const [incline, setIncline] = useState('')
  const save = useMutation({
    mutationFn: (next: number | null) => setElevation(activity.id, next),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  const fromIncline = (percent: string) => {
    setIncline(percent)
    if (percent === '' || activity.distance_km === null) return
    setMetres(Math.round(activity.distance_km * 1000 * (Number(percent) / 100)))
  }
  const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
  return (
    <Card title="Climbing" subtitle="For a treadmill or another session where the watch measured no climbing">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-muted">
            <span className="mb-1 block">Climbing, m</span>
            <input
              type="number"
              min={0}
              inputMode="numeric"
              className={input}
              value={metres ?? ''}
              onChange={(event) => setMetres(event.target.value === '' ? null : Number(event.target.value))}
            />
          </label>
          {activity.distance_km !== null && (
            <label className="block text-xs text-muted">
              <span className="mb-1 block">Or the average incline, %</span>
              <input
                type="number"
                min={0}
                step={0.5}
                inputMode="decimal"
                className={input}
                value={incline}
                onChange={(event) => fromIncline(event.target.value)}
              />
            </label>
          )}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => save.mutate(metres)}
            disabled={save.isPending || metres === activity.elevation_gain_override_m}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
          <p className="text-xs text-muted" role="status">
            {save.error ? save.error.message : save.isPending ? 'Saving…' : save.isSuccess ? 'Saved' : ''}
          </p>
        </div>
      </div>
    </Card>
  )
}

const LONG_ENOUGH_TO_FUEL_S = 60 * 60

export function ActivityPage({ id }: { id: number }) {
  const theme = useTheme()
  const activity = useQuery({ queryKey: ['activity', id], queryFn: () => fetchActivity(id) })
  if (activity.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (activity.error) return <p className="text-sm text-critical">{activity.error.message}</p>
  const data = activity.data
  const started = new Date(data.start_time_local).toLocaleString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
  return (
    <div className="space-y-4">
      <div>
        <button type="button" onClick={() => window.history.back()} className="text-xs text-accent">
          Back
        </button>
        <h1 className="mt-1 flex items-center gap-2.5 text-2xl font-semibold tracking-tight text-primary">
          <span
            className="h-6 w-1.5 shrink-0 rounded-full"
            style={{ background: groupColor(theme, data.sport_group) }}
            aria-hidden
          />
          {data.name ?? sentence(data.type_key)}
        </h1>
        <p className="mt-0.5 text-sm text-muted">
          {[groupLabel(data.sport_group), sentence(data.type_key)]
            .filter((part, index, parts) => parts.indexOf(part) === index)
            .join(', ')}
          , {started}
          {data.terrain && data.terrain !== 'unknown' ? `, ${data.terrain} terrain` : ''}
        </p>
      </div>
      <Stats activity={data} />
      <div className="grid gap-4 lg:grid-cols-2">
        {data.planned && <Planned planned={data.planned} />}
        <RatingCard
          activityId={data.id}
          saved={data.rating}
          title="How it felt"
          subtitle="The coach reads this next to the heart rate numbers"
        />
        {(data.elevation_gain_override_m !== null || !data.elevation_gain_m) && <ClimbingCard activity={data} />}
        {(data.fuel !== null || (data.duration_s ?? 0) >= LONG_ENOUGH_TO_FUEL_S) && (
          <FuelCard
            activityId={data.id}
            durationS={data.duration_s}
            saved={data.fuel}
            title="Fueling"
            subtitle="What you ate and drank, so the coach can build toward race fueling"
          />
        )}
        <Zones activity={data} />
        <Drift activity={data} />
        <StrengthSets activity={data} />
        <Laps activity={data} />
      </div>
    </div>
  )
}
