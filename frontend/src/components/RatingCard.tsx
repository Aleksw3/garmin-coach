import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { rateActivity, type Rating } from '../api'
import { Card } from './Card'
import { SaveStatus } from './SaveStatus'

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

type Props = {
  activityId: number
  saved: Rating | null
  title: string
  subtitle?: string
  onSaved?: () => void
  onSkip?: () => void
}

export function RatingCard({ activityId, saved, title, subtitle, onSaved, onSkip }: Props) {
  const queryClient = useQueryClient()
  const [rating, setRating] = useState<Rating>(saved ?? NO_RATING)
  const save = useMutation({
    mutationFn: (next: Rating) => rateActivity(activityId, next),
    onSuccess: () => {
      onSaved?.()
      return queryClient.invalidateQueries({ queryKey: ['activity', activityId] })
    },
  })
  const choose = (change: Partial<Rating>) => {
    const next = { ...rating, ...change }
    setRating(next)
    save.mutate(next)
  }
  const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
  return (
    <Card title={title} subtitle={subtitle}>
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
        <SaveStatus save={save} onSkip={onSkip} />
      </div>
    </Card>
  )
}
