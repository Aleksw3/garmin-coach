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
