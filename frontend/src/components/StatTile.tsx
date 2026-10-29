import type { ReactNode } from 'react'

type Props = { label: string; value: string; detail?: ReactNode }

export function StatTile({ label, value, detail }: Props) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-primary">{value}</div>
      {detail && <div className="mt-1 text-xs text-secondary">{detail}</div>}
    </div>
  )
}

const STATUS_STYLE = {
  below: { icon: '▼', label: 'Below normal range', color: 'text-warning' },
  within: { icon: '●', label: 'Within normal range', color: 'text-good' },
  above: { icon: '▲', label: 'Above normal range', color: 'text-secondary' },
} as const

export function BaselineBadge({ status }: { status: keyof typeof STATUS_STYLE }) {
  const style = STATUS_STYLE[status]
  return (
    <span className="inline-flex items-center gap-1">
      <span className={style.color} aria-hidden>
        {style.icon}
      </span>
      <span>{style.label}</span>
    </span>
  )
}
