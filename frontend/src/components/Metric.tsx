import type { ReactNode } from 'react'

export type Tone = 'accent' | 'good' | 'warning' | 'critical' | 'neutral'

const FILL: Record<Tone, string> = {
  accent: 'bg-accent',
  good: 'bg-good',
  warning: 'bg-warning',
  critical: 'bg-critical',
  neutral: 'bg-muted',
}

type TileProps = { label: string; value: string; unit?: string; children?: ReactNode; detail?: ReactNode }

export function MetricTile({ label, value, unit, children, detail }: TileProps) {
  return (
    <div className="flex min-w-0 flex-col rounded-xl border border-line bg-surface p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="tabular text-2xl font-semibold tracking-tight whitespace-nowrap text-primary sm:text-3xl">{value}</span>
        {unit && <span className="text-sm text-secondary">{unit}</span>}
      </div>
      {children && <div className="mt-3">{children}</div>}
      {detail && <div className="mt-2 text-xs text-secondary">{detail}</div>}
    </div>
  )
}

type MeterProps = { label: string; value: number; max?: number; tone?: Tone }

export function Meter({ label, value, max = 100, tone = 'accent' }: MeterProps) {
  const share = Math.max(0, Math.min(1, value / max))
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={max}
      className="h-1.5 overflow-hidden rounded-full bg-raised"
    >
      <div className={`h-full rounded-full ${FILL[tone]}`} style={{ width: `${share * 100}%` }} />
    </div>
  )
}

type RangeProps = { label: string; low: number; high: number; value: number; latest?: number | null; tone: Tone }

export function RangeTrack({ label, low, high, value, latest, tone }: RangeProps) {
  const shown = [low, high, value, ...(latest === null || latest === undefined ? [] : [latest])]
  const margin = Math.max((Math.max(...shown) - Math.min(...shown)) * 0.3, 1)
  const first = Math.min(...shown) - margin
  const width = Math.max(...shown) + margin - first
  const at = (point: number) => `${((point - first) / width) * 100}%`
  return (
    <div role="img" aria-label={label} className="relative h-3">
      <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-raised" />
      <div
        className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[var(--baseline)]"
        style={{ left: at(low), right: `calc(100% - ${at(high)})` }}
      />
      {latest !== null && latest !== undefined && (
        <div
          className="absolute top-0 h-3 w-0.5 -translate-x-1/2 rounded-full bg-[var(--text-muted)]"
          style={{ left: at(latest) }}
        />
      )}
      <div
        className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-surface ${FILL[tone]}`}
        style={{ left: at(value) }}
      />
    </div>
  )
}
