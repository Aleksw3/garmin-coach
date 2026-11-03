import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import {
  createGoal,
  deleteGoal,
  deleteNote,
  fetchGoals,
  fetchNotes,
  fetchProfile,
  saveProfile,
  updateGoal,
  type Goal,
  type GoalInput,
  type Profile,
} from '../api'
import { Card } from '../components/Card'
import { number, shortDate } from '../format'

const EMPTY_GOAL: GoalInput = {
  kind: 'race',
  title: '',
  target_date: null,
  target: null,
  distance_km: null,
  elevation_gain_m: null,
  terrain: null,
  cutoffs: null,
  notes: null,
  priority: 'A',
  status: 'active',
}

const INPUT =
  'w-full min-w-0 rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary focus:border-accent focus:outline-none sm:text-sm'

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`block text-xs text-muted ${wide ? 'sm:col-span-2' : ''}`}>
      <span className="mb-1 block">{label}</span>
      {children}
    </label>
  )
}

const text = (value: string): string | null => (value.trim() ? value : null)
const numeric = (value: string): number | null => (value.trim() ? Number(value) : null)

function GoalForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: GoalInput
  onSave: (goal: GoalInput) => void
  onCancel?: () => void
}) {
  const [goal, setGoal] = useState(initial)
  const set = <K extends keyof GoalInput>(key: K, value: GoalInput[K]) => setGoal({ ...goal, [key]: value })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onSave(goal)
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field label="Title" wide>
        <input required className={INPUT} value={goal.title} onChange={(e) => set('title', e.target.value)} />
      </Field>
      <Field label="Kind">
        <select className={INPUT} value={goal.kind} onChange={(e) => set('kind', e.target.value as GoalInput['kind'])}>
          <option value="race">Race</option>
          <option value="strength">Strength</option>
          <option value="habit">Habit</option>
          <option value="other">Other</option>
        </select>
      </Field>
      <Field label="Date">
        <input
          type="date"
          className={INPUT}
          value={goal.target_date ?? ''}
          onChange={(e) => set('target_date', text(e.target.value))}
        />
      </Field>
      <Field label="Target, for example under 5 hours or 120 kg squat" wide>
        <input className={INPUT} value={goal.target ?? ''} onChange={(e) => set('target', text(e.target.value))} />
      </Field>
      {goal.kind === 'race' && (
        <>
          <Field label="Distance (km)">
            <input
              type="number"
              step="0.1"
              className={INPUT}
              value={goal.distance_km ?? ''}
              onChange={(e) => set('distance_km', numeric(e.target.value))}
            />
          </Field>
          <Field label="Climbing (m)">
            <input
              type="number"
              className={INPUT}
              value={goal.elevation_gain_m ?? ''}
              onChange={(e) => set('elevation_gain_m', numeric(e.target.value))}
            />
          </Field>
          <Field label="Terrain" wide>
            <input className={INPUT} value={goal.terrain ?? ''} onChange={(e) => set('terrain', text(e.target.value))} />
          </Field>
          <Field label="Cutoffs" wide>
            <input className={INPUT} value={goal.cutoffs ?? ''} onChange={(e) => set('cutoffs', text(e.target.value))} />
          </Field>
        </>
      )}
      <Field label="Notes" wide>
        <textarea
          rows={2}
          className={INPUT}
          value={goal.notes ?? ''}
          onChange={(e) => set('notes', text(e.target.value))}
        />
      </Field>
      <Field label="Priority">
        <select
          className={INPUT}
          value={goal.priority}
          onChange={(e) => set('priority', e.target.value as GoalInput['priority'])}
        >
          <option value="A">A, the main goal</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
      </Field>
      <Field label="Status">
        <select
          className={INPUT}
          value={goal.status}
          onChange={(e) => set('status', e.target.value as GoalInput['status'])}
        >
          <option value="active">Active</option>
          <option value="done">Done</option>
          <option value="dropped">Dropped</option>
        </select>
      </Field>
      <div className="flex gap-2 sm:col-span-2">
        <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
          Save goal
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-secondary hover:bg-raised"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  )
}

function goalFacts(goal: Goal): string[] {
  return [
    goal.target_date ? new Date(`${goal.target_date}T00:00:00Z`).toLocaleDateString('en-GB', { dateStyle: 'long', timeZone: 'UTC' }) : null,
    goal.target,
    goal.distance_km !== null ? `${number(goal.distance_km, 1)} km` : null,
    goal.elevation_gain_m !== null ? `${number(goal.elevation_gain_m)} m climbing` : null,
  ].filter((fact): fact is string => fact !== null)
}

function GoalCard({ goal, onSave, onDelete }: { goal: Goal; onSave: (g: GoalInput) => void; onDelete: () => void }) {
  const [editing, setEditing] = useState(false)
  if (editing) {
    return (
      <GoalForm
        initial={goal}
        onSave={(input) => {
          onSave(input)
          setEditing(false)
        }}
        onCancel={() => setEditing(false)}
      />
    )
  }
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-base font-semibold text-primary">{goal.title}</h3>
        <span className="text-xs text-muted">
          {goal.kind}, priority {goal.priority}
          {goal.status !== 'active' && `, ${goal.status}`}
        </span>
      </div>
      <p className="text-sm text-secondary">{goalFacts(goal).join(' · ')}</p>
      {goal.terrain && <p className="text-sm text-secondary">{goal.terrain}</p>}
      {goal.cutoffs && <p className="text-sm text-secondary">Cutoffs: {goal.cutoffs}</p>}
      {goal.notes && <p className="text-xs text-muted">{goal.notes}</p>}
      <div className="flex gap-3 pt-1 text-xs">
        <button type="button" onClick={() => setEditing(true)} className="text-accent">
          Edit
        </button>
        <button
          type="button"
          onClick={() => window.confirm(`Delete ${goal.title}?`) && onDelete()}
          className="text-muted hover:text-critical"
        >
          Delete
        </button>
      </div>
    </div>
  )
}

function GoalsCard() {
  const queryClient = useQueryClient()
  const goals = useQuery({ queryKey: ['goals'], queryFn: fetchGoals })
  const [adding, setAdding] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['goals'] })
  const create = useMutation({ mutationFn: createGoal, onSuccess: refresh })
  const update = useMutation({
    mutationFn: ({ id, goal }: { id: number; goal: GoalInput }) => updateGoal(id, goal),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: deleteGoal, onSuccess: refresh })
  return (
    <Card title="Goals" subtitle="The coach reads these before it answers" className="lg:col-span-2">
      <div className="space-y-4">
        {goals.data?.length === 0 && !adding && <p className="text-sm text-muted">No goals yet.</p>}
        {goals.data?.map((goal) => (
          <div key={goal.id} className="border-b border-line pb-4 last:border-0 last:pb-0">
            <GoalCard
              goal={goal}
              onSave={(input) => update.mutate({ id: goal.id, goal: input })}
              onDelete={() => remove.mutate(goal.id)}
            />
          </div>
        ))}
        {adding ? (
          <GoalForm
            initial={EMPTY_GOAL}
            onSave={(goal) => {
              create.mutate(goal)
              setAdding(false)
            }}
            onCancel={() => setAdding(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised"
          >
            Add goal
          </button>
        )}
      </div>
    </Card>
  )
}

function ProfileForm({ initial }: { initial: Profile }) {
  const queryClient = useQueryClient()
  const [profile, setProfile] = useState(initial)
  const save = useMutation({
    mutationFn: saveProfile,
    onSuccess: (data) => queryClient.setQueryData(['profile'], data),
  })
  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setProfile({ ...profile, [key]: value })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate(profile)
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field label="Name">
        <input className={INPUT} value={profile.name ?? ''} onChange={(e) => set('name', text(e.target.value))} />
      </Field>
      <Field label="Birth year">
        <input
          type="number"
          className={INPUT}
          value={profile.birth_year ?? ''}
          onChange={(e) => set('birth_year', numeric(e.target.value))}
        />
      </Field>
      <Field label="Sex">
        <input className={INPUT} value={profile.sex ?? ''} onChange={(e) => set('sex', text(e.target.value))} />
      </Field>
      <Field label="Height (cm)">
        <input
          type="number"
          className={INPUT}
          value={profile.height_cm ?? ''}
          onChange={(e) => set('height_cm', numeric(e.target.value))}
        />
      </Field>
      <Field label="Max HR">
        <input
          type="number"
          className={INPUT}
          value={profile.max_hr ?? ''}
          onChange={(e) => set('max_hr', numeric(e.target.value))}
        />
      </Field>
      <Field label="TRIMP factor for training load, 1.92 for men, 1.67 for women">
        <input
          type="number"
          step="0.01"
          min="1"
          max="3"
          className={INPUT}
          value={profile.trimp_coefficient ?? ''}
          onChange={(e) => set('trimp_coefficient', numeric(e.target.value))}
        />
      </Field>
      <Field label="Training days, for example long run Saturday, strength Tuesday and Thursday" wide>
        <textarea
          rows={2}
          className={INPUT}
          value={profile.training_days ?? ''}
          onChange={(e) => set('training_days', text(e.target.value))}
        />
      </Field>
      <Field label="Injuries and niggles" wide>
        <textarea
          rows={2}
          className={INPUT}
          value={profile.injuries ?? ''}
          onChange={(e) => set('injuries', text(e.target.value))}
        />
      </Field>
      <Field label="Equipment, for example gym access, treadmill, poles" wide>
        <textarea
          rows={2}
          className={INPUT}
          value={profile.equipment ?? ''}
          onChange={(e) => set('equipment', text(e.target.value))}
        />
      </Field>
      <Field label="Anything else the coach should know" wide>
        <textarea
          rows={2}
          className={INPUT}
          value={profile.notes ?? ''}
          onChange={(e) => set('notes', text(e.target.value))}
        />
      </Field>
      <div className="flex items-center gap-3 sm:col-span-2">
        <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
          Save profile
        </button>
        {save.isSuccess && <span className="text-xs text-muted">Saved</span>}
        {save.isError && <span className="text-xs text-critical">{save.error.message}</span>}
      </div>
    </form>
  )
}

function ProfileCard() {
  const profile = useQuery({ queryKey: ['profile'], queryFn: fetchProfile })
  return (
    <Card title="Profile" subtitle="Background the coach uses when it plans">
      {profile.data ? <ProfileForm initial={profile.data} /> : <p className="text-sm text-muted">Loading…</p>}
    </Card>
  )
}

function NotesCard() {
  const queryClient = useQueryClient()
  const notes = useQuery({ queryKey: ['notes'], queryFn: fetchNotes })
  const remove = useMutation({
    mutationFn: deleteNote,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['notes'] }),
  })
  return (
    <Card title="Coach notes" subtitle="Facts the coach saved from your conversations">
      {notes.data?.length === 0 && <p className="text-sm text-muted">No notes yet.</p>}
      <ul className="space-y-2">
        {notes.data?.map((note) => (
          <li key={note.id} className="flex items-start justify-between gap-3 text-sm">
            <span className="text-secondary">
              <span className="text-xs text-muted">{shortDate(note.created_at)} </span>
              {note.text}
            </span>
            <button
              type="button"
              onClick={() => remove.mutate(note.id)}
              aria-label={`Delete note: ${note.text}`}
              className="shrink-0 text-xs text-muted hover:text-critical"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function GoalsPage() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <GoalsCard />
      <ProfileCard />
      <NotesCard />
    </div>
  )
}
