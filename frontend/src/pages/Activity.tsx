import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  addThresholdTest,
  editSet,
  fetchActivity,
  fetchZones,
  logFuel,
  rateActivity,
  restoreSet,
  type ActivityDetail,
  type Fuel,
  type Rating,
  type StrengthSetRow,
} from '../api'
import { Card, DataTable } from '../components/Card'
import { StatTile } from '../components/StatTile'
import { duration, number, sentence } from '../format'
import { groupLabel } from '../theme'

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
    .padStart(2, '0')} /km`
}

function Stats({ activity }: { activity: ActivityDetail }) {
  const tiles = [
    { label: 'Duration', value: duration(activity.duration_s), detail: activity.moving_s ? `moving ${duration(activity.moving_s)}` : null },
    activity.distance_km ? { label: 'Distance', value: `${number(activity.distance_km, 2)} km`, detail: null } : null,
    activity.elevation_gain_m
      ? { label: 'Climbing', value: `${number(activity.elevation_gain_m)} m`, detail: `${number(activity.elevation_loss_m)} m down` }
      : null,
    activity.avg_hr ? { label: 'Heart rate', value: `${number(activity.avg_hr)} bpm`, detail: `max ${number(activity.max_hr)}` } : null,
    activity.distance_km && activity.avg_speed_mps
      ? {
          label: 'Pace',
          value: pace(activity.avg_speed_mps),
          detail: activity.avg_grade_adjusted_speed_mps ? `grade-adjusted ${pace(activity.avg_grade_adjusted_speed_mps)}` : null,
        }
      : null,
    activity.training_load !== null
      ? {
          label: 'Training load',
          value: number(activity.training_load),
          detail:
            activity.aerobic_training_effect !== null
              ? `effect ${number(activity.aerobic_training_effect, 1)} aerobic, ${number(activity.anaerobic_training_effect, 1)} anaerobic`
              : null,
        }
      : null,
  ].filter((tile) => tile !== null)
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {tiles.map((tile) => (
        <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
      ))}
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
    drift < 3.5
      ? 'Under 3.5%: this pace was below LT1. Try a little faster next time.'
      : drift <= 5
        ? '3.5 to 5%: this pace was close to LT1.'
        : 'Over 5%: this pace was above LT1, or the run was not steady.'
  const lt2 = zones.data?.current?.lt2_hr
  return (
    <Card title="Heart rate drift" subtitle="First half against second half after a 15 min warm-up">
      <div className="grid grid-cols-3 gap-2">
        <StatTile label="First half" value={`${number(activity.drift_first_hr)} bpm`} detail={null} />
        <StatTile label="Second half" value={`${number(activity.drift_second_hr)} bpm`} detail={null} />
        <StatTile
          label="Drift"
          value={`${number(drift, 1)}%`}
          detail={activity.decoupling_pct !== null ? `pace to HR ${number(activity.decoupling_pct, 1)}%` : null}
        />
      </div>
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
          pace(lap.avg_speed_mps),
          pace(lap.avg_grade_adjusted_speed_mps),
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
  const parts = Object.entries(planned.details).map(([key, [target, actual]]) => {
    const [label, unit] = TARGET_LABELS[key] ?? [key, '']
    return `${label} ${number(actual)} of ${number(target)} ${unit}`
  })
  return (
    <Card title={`Planned: ${planned.title}`} subtitle="How this activity compares with the planned session">
      <p className="text-sm text-primary">
        {planned.compliance !== null ? `Compliance ${number(planned.compliance)}%` : 'Done, the session had no targets'}
      </p>
      {parts.length > 0 && <p className="mt-1 text-xs text-secondary">{parts.join(', ')}</p>}
    </Card>
  )
}

const LEGS = ['Fresh', 'Normal', 'Heavy', 'Sore', 'Very sore']
const NO_RATING: Rating = { effort: null, legs: null, pain: null, note: null }

function Scale({
  label,
  values,
  chosen,
  onChoose,
}: {
  label: string
  values: string[]
  chosen: number | null
  onChoose: (value: number | null) => void
}) {
  return (
    <div>
      <p className="mb-1 text-xs text-muted">{label}</p>
      <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
        {values.map((text, index) => {
          const value = index + 1
          const on = chosen === value
          return (
            <button
              key={text}
              type="button"
              aria-pressed={on}
              onClick={() => onChoose(on ? null : value)}
              className={`min-w-9 rounded-lg border px-2 py-1.5 text-sm ${on ? 'border-accent bg-accent font-semibold text-white' : 'border-line text-secondary hover:bg-raised'}`}
            >
              {text}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function RatingCard({ activity }: { activity: ActivityDetail }) {
  const queryClient = useQueryClient()
  const [rating, setRating] = useState<Rating>(activity.rating ?? NO_RATING)
  const save = useMutation({
    mutationFn: (next: Rating) => rateActivity(activity.id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['activity', activity.id] }),
  })
  const choose = (change: Partial<Rating>) => {
    const next = { ...rating, ...change }
    setRating(next)
    save.mutate(next)
  }
  const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
  return (
    <Card title="How it felt" subtitle="The coach reads this next to the heart rate numbers">
      <div className="space-y-3">
        <Scale
          label="Effort, 1 very easy to 10 all out"
          values={Array.from({ length: 10 }, (_, index) => String(index + 1))}
          chosen={rating.effort}
          onChoose={(effort) => choose({ effort })}
        />
        <Scale label="Legs afterwards" values={LEGS} chosen={rating.legs} onChoose={(legs) => choose({ legs })} />
        <label className="block text-xs text-muted">
          <span className="mb-1 block">Pain or a niggle, and where</span>
          <input
            className={input}
            value={rating.pain ?? ''}
            onChange={(event) => setRating({ ...rating, pain: event.target.value })}
            onBlur={() => save.mutate(rating)}
          />
        </label>
        <label className="block text-xs text-muted">
          <span className="mb-1 block">Anything else, for example heat, poor sleep or a new route</span>
          <input
            className={input}
            value={rating.note ?? ''}
            onChange={(event) => setRating({ ...rating, note: event.target.value })}
            onBlur={() => save.mutate(rating)}
          />
        </label>
        <p className="text-xs text-muted" role="status">
          {save.error ? save.error.message : save.isPending ? 'Saving…' : save.isSuccess ? 'Saved' : ''}
        </p>
      </div>
    </Card>
  )
}

const NO_FUEL: Fuel = { carbs_g: null, fluid_ml: null, gut: null, note: null }
const LONG_ENOUGH_TO_FUEL_S = 60 * 60

function perHour(amount: number | null, seconds: number | null): string {
  return amount === null || !seconds ? '' : `${number(amount / (seconds / 3600))} per hour`
}

function FuelCard({ activity }: { activity: ActivityDetail }) {
  const queryClient = useQueryClient()
  const [fuel, setFuel] = useState<Fuel>(activity.fuel ?? NO_FUEL)
  const save = useMutation({
    mutationFn: (next: Fuel) => logFuel(activity.id, next),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['activity', activity.id] }),
  })
  const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
  const amount = (key: 'carbs_g' | 'fluid_ml', label: string) => (
    <label className="block text-xs text-muted">
      <span className="mb-1 block">
        {label} {perHour(fuel[key], activity.duration_s)}
      </span>
      <input
        type="number"
        min={0}
        inputMode="numeric"
        className={input}
        value={fuel[key] ?? ''}
        onChange={(event) => setFuel({ ...fuel, [key]: event.target.value === '' ? null : Number(event.target.value) })}
        onBlur={() => save.mutate(fuel)}
      />
    </label>
  )
  const text = (key: 'gut' | 'note', label: string) => (
    <label className="block text-xs text-muted">
      <span className="mb-1 block">{label}</span>
      <input
        className={input}
        value={fuel[key] ?? ''}
        onChange={(event) => setFuel({ ...fuel, [key]: event.target.value })}
        onBlur={() => save.mutate(fuel)}
      />
    </label>
  )
  return (
    <Card title="Fueling" subtitle="What you ate and drank, so the coach can build toward race fueling">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          {amount('carbs_g', 'Carbohydrate, g')}
          {amount('fluid_ml', 'Fluid, ml')}
        </div>
        {text('gut', 'Stomach problems, and when')}
        {text('note', 'What you used, for example gels, drink mix or real food')}
        <p className="text-xs text-muted" role="status">
          {save.error ? save.error.message : save.isPending ? 'Saving…' : save.isSuccess ? 'Saved' : ''}
        </p>
      </div>
    </Card>
  )
}

export function ActivityPage({ id }: { id: number }) {
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
        <h1 className="mt-1 text-lg font-semibold text-primary">{data.name ?? sentence(data.type_key)}</h1>
        <p className="text-sm text-secondary">
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
        <RatingCard activity={data} />
        {(data.fuel !== null || (data.duration_s ?? 0) >= LONG_ENOUGH_TO_FUEL_S) && <FuelCard activity={data} />}
        <Zones activity={data} />
        <Drift activity={data} />
        <StrengthSets activity={data} />
        <Laps activity={data} />
      </div>
    </div>
  )
}
