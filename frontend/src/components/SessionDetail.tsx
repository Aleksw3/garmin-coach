import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, type ReactNode } from 'react'
import { deleteSession, fetchZones, setSkipped, type Exercise, type PlannedSession, type Step } from '../api'
import { zoneLabel } from '../charts'
import { dayLabel, number } from '../format'
import { sessionStatus } from '../sessions'
import { groupColor, groupLabel, useTheme } from '../theme'

const STEP_LABELS: Record<Step['kind'], string> = {
  warmup: 'Warm-up',
  steady: 'Main part',
  intervals: 'Intervals',
  cooldown: 'Cool-down',
}

function size(duration: number | null | undefined, distance: number | null | undefined): string {
  return [duration ? `${number(duration)} min` : null, distance ? `${number(distance, 1)} km` : null]
    .filter(Boolean)
    .join(' or ')
}

function Target({ text }: { text: string }) {
  const zones = useQuery({ queryKey: ['zones'], queryFn: fetchZones })
  const numbers = [...text.matchAll(/Z([1-5])/g)].map((match) => Number(match[1]))
  const shown = zones.data?.zones.filter((zone) => numbers.includes(zone.number)) ?? []
  const low = shown[0]
  const high = shown[shown.length - 1]
  const range = !low || /bpm/.test(text) ? null : zoneLabel({ ...low, high: high.high })
  return (
    <span className="rounded-md bg-raised px-1.5 py-0.5 text-xs font-medium text-primary">
      {text}
      {range && <span className="text-secondary">, {range} bpm</span>}
    </span>
  )
}

function StepRow({ step }: { step: Step }) {
  const amount = size(step.duration_min, step.distance_km)
  return (
    <li className="grid grid-cols-[6.5rem_1fr] gap-3 py-2.5">
      <span className="text-xs font-medium tracking-wide text-muted uppercase">{STEP_LABELS[step.kind]}</span>
      <div className="space-y-1">
        <p className="flex flex-wrap items-center gap-2 text-sm text-primary">
          <span className="font-semibold">
            {step.repeats ? `${step.repeats} × ${amount || 'repeat'}` : amount || STEP_LABELS[step.kind]}
          </span>
          {step.target && <Target text={step.target} />}
        </p>
        {step.recovery && <p className="text-xs text-secondary">Recovery: {step.recovery}</p>}
        {step.note && <p className="text-xs text-muted">{step.note}</p>}
      </div>
    </li>
  )
}

function ExerciseRow({ exercise, index }: { exercise: Exercise; index: number }) {
  return (
    <li className="grid grid-cols-[1.25rem_1fr_auto] gap-x-3 py-2.5">
      <span className="tabular pt-0.5 text-xs text-muted">{index + 1}</span>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-primary">{exercise.name}</p>
        {exercise.note && <p className="mt-0.5 text-xs text-muted">{exercise.note}</p>}
      </div>
      <div className="tabular text-right">
        <p className="text-sm text-primary">
          {exercise.sets} × {exercise.reps}
        </p>
        <p className="text-xs text-secondary">
          {[exercise.load, exercise.rest_s ? `rest ${exercise.rest_s} s` : null].filter(Boolean).join(', ')}
        </p>
      </div>
    </li>
  )
}

function Notes({ text }: { text: string }) {
  const lines = text
    .split(/\n+|(?<=[.!?])\s+(?=[A-ZÆØÅ])/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length === 1) return <p className="text-sm text-secondary">{lines[0]}</p>
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-secondary">
      {lines.map((line, index) => (
        <li key={index}>{line}</li>
      ))}
    </ul>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      <div className="mt-1">{children}</div>
    </section>
  )
}

export function SessionDialog({
  session,
  today,
  onClose,
}: {
  session: PlannedSession
  today: string
  onClose: () => void
}) {
  const theme = useTheme()
  const dialog = useRef<HTMLDialogElement>(null)
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['calendar'] })
  const skip = useMutation({
    mutationFn: (skipped: boolean) => setSkipped(session.id, skipped),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: () => deleteSession(session.id),
    onSuccess: async () => {
      await refresh()
      onClose()
    },
  })

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const status = sessionStatus(session, today)
  const targets = [
    session.duration_min ? ['Duration', `${number(session.duration_min)} min`] : null,
    session.distance_km ? ['Distance', `${number(session.distance_km, 1)} km`] : null,
    session.elevation_gain_m ? ['Climbing', `${number(session.elevation_gain_m)} m`] : null,
  ].filter((target) => target !== null)
  const color = session.sport === 'rest' ? 'var(--border)' : groupColor(theme, session.sport)

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onClick={(event) => event.target === dialog.current && dialog.current?.close()}
      className="m-auto max-h-[90dvh] w-[calc(100%-2rem)] max-w-xl overflow-y-auto rounded-xl border border-line bg-surface p-0 text-primary backdrop:bg-black/60"
    >
      <div className="space-y-5 p-5" style={{ borderTop: `4px solid ${color}` }}>
        <header>
          <p className="text-xs text-muted">
            {dayLabel(session.day)}, {session.sport === 'rest' ? 'rest' : groupLabel(session.sport).toLowerCase()},{' '}
            {session.kind}
          </p>
          <h2 className="mt-1 text-lg font-semibold">{session.title}</h2>
          {status && <p className="mt-1 text-sm text-secondary">{status}</p>}
        </header>

        {(targets.length > 0 || session.intensity) && (
          <div className="grid grid-cols-3 gap-2">
            {targets.map(([label, value]) => (
              <div key={label} className="rounded-lg bg-raised px-3 py-2">
                <p className="text-xs text-muted">{label}</p>
                <p className="tabular text-base font-semibold">{value}</p>
              </div>
            ))}
            {session.intensity && (
              <div className="col-span-3 rounded-lg bg-raised px-3 py-2">
                <p className="text-xs text-muted">Intensity</p>
                <p className="text-sm font-medium">{session.intensity}</p>
              </div>
            )}
          </div>
        )}

        {session.steps.length > 0 && (
          <Section title="Steps">
            <ol className="divide-y divide-[var(--border)]">
              {session.steps.map((step, index) => (
                <StepRow key={index} step={step} />
              ))}
            </ol>
          </Section>
        )}

        {session.exercises.length > 0 && (
          <Section title="Exercises">
            <ol className="divide-y divide-[var(--border)]">
              {session.exercises.map((exercise, index) => (
                <ExerciseRow key={index} exercise={exercise} index={index} />
              ))}
            </ol>
          </Section>
        )}

        {session.description && (
          <Section title="Notes">
            <Notes text={session.description} />
          </Section>
        )}

        <footer className="flex flex-wrap items-center gap-4 border-t border-line pt-4 text-sm">
          {session.match && (
            <a href={`#activity/${session.match.activity_id}`} className="font-semibold text-accent">
              Open the activity
            </a>
          )}
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
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            className="ml-auto rounded-lg border border-line px-3 py-1.5 text-secondary hover:bg-raised"
          >
            Close
          </button>
        </footer>
      </div>
    </dialog>
  )
}
