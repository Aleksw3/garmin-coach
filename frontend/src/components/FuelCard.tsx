import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { logFuel, type Fuel } from '../api'
import { number } from '../format'
import { Card } from './Card'
import { SaveStatus } from './SaveStatus'

const NO_FUEL: Fuel = { carbs_g: null, fluid_ml: null, gut: null, note: null }

function perHour(amount: number | null, seconds: number | null): string {
  return amount === null || !seconds ? '' : `${number(amount / (seconds / 3600))} per hour`
}

type Props = {
  activityId: number
  durationS: number | null
  saved: Fuel | null
  title: string
  subtitle?: string
  onSaved?: () => void
  onSkip?: () => void
}

export function FuelCard({ activityId, durationS, saved, title, subtitle, onSaved, onSkip }: Props) {
  const queryClient = useQueryClient()
  const [fuel, setFuel] = useState<Fuel>(saved ?? NO_FUEL)
  const save = useMutation({
    mutationFn: (next: Fuel) => logFuel(activityId, next),
    onSuccess: () => {
      onSaved?.()
      return queryClient.invalidateQueries({ queryKey: ['activity', activityId] })
    },
  })
  const input = 'w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm'
  const amount = (key: 'carbs_g' | 'fluid_ml', label: string) => (
    <label className="block text-xs text-muted">
      <span className="mb-1 block">
        {label} {perHour(fuel[key], durationS)}
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
    <Card title={title} subtitle={subtitle}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          {amount('carbs_g', 'Carbohydrate, g')}
          {amount('fluid_ml', 'Fluid, ml')}
        </div>
        {text('gut', 'Stomach problems, and when')}
        {text('note', 'What you used, for example gels, drink mix or real food')}
        <SaveStatus save={save} onSkip={onSkip} />
      </div>
    </Card>
  )
}
