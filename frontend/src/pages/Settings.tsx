import { useQuery } from '@tanstack/react-query'
import { fetchUsage, type Usage } from '../api'
import { Card, DataTable } from '../components/Card'
import { number } from '../format'

const WARN_SHARE = 0.8

function dollars(value: number, digits = 2): string {
  return `$${value.toFixed(digits)}`
}

function BudgetMeter({ usage }: { usage: Usage }) {
  const share = usage.budget_usd > 0 ? usage.month_cost_usd / usage.budget_usd : 1
  const state =
    share >= 1
      ? { color: 'bg-critical', text: 'text-critical', label: '■ Budget used up, chat is paused until the 1st' }
      : share >= WARN_SHARE
        ? { color: 'bg-warning', text: 'text-warning', label: '▲ Over 80% of the budget' }
        : { color: 'bg-accent', text: 'text-muted', label: null }
  return (
    <div>
      <p className="tabular text-2xl font-semibold text-primary">
        {dollars(usage.month_cost_usd)}
        <span className="text-sm font-normal text-muted"> of {dollars(usage.budget_usd)}</span>
      </p>
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-raised"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={usage.budget_usd}
        aria-valuenow={usage.month_cost_usd}
        aria-label="API cost this month against the budget"
      >
        <div className={`h-full rounded-full ${state.color}`} style={{ width: `${Math.min(share, 1) * 100}%` }} />
      </div>
      <p className={`mt-2 text-xs ${state.text}`}>
        {state.label ?? `${usage.calls_this_month} API calls this month`}
      </p>
    </div>
  )
}

export function SettingsPage() {
  const usage = useQuery({ queryKey: ['usage'], queryFn: fetchUsage })
  if (usage.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (usage.error) return <p className="text-sm text-critical">{usage.error.message}</p>
  const data = usage.data
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="API cost this month" subtitle="Claude API spending against the monthly budget">
        <BudgetMeter usage={data} />
      </Card>
      <Card title="Coach settings" subtitle="Change these in .env at the repo root, then restart">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">Chat model</dt>
          <dd className="text-primary">{data.chat_model}</dd>
          <dt className="text-muted">Monthly budget</dt>
          <dd className="text-primary">
            {dollars(data.budget_usd)} <span className="text-xs text-muted">MONTHLY_BUDGET_USD</span>
          </dd>
        </dl>
      </Card>
      <Card title="Recent API calls" subtitle="Cache reads cost a tenth of normal input or less" className="lg:col-span-2">
        {data.recent.length === 0 ? (
          <p className="text-sm text-muted">No calls yet.</p>
        ) : (
          <DataTable
            columns={['Time', 'Model', 'Purpose', 'Input', 'Cache write', 'Cache read', 'Output', 'Cost']}
            rows={data.recent.map((row) => [
              new Date(row.created_at).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }),
              row.model,
              row.purpose,
              number(row.input_tokens),
              number(row.cache_write_tokens),
              number(row.cache_read_tokens),
              number(row.output_tokens),
              dollars(row.cost_usd, 4),
            ])}
          />
        )}
      </Card>
    </div>
  )
}
