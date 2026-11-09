import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import {
  currentProfile,
  fetchClaude,
  fetchDailyUsage,
  fetchNotifications,
  fetchUsage,
  saveTopic,
  sendTestNotification,
  type Usage,
} from '../api'
import { dailyCostOption } from '../charts'
import { Card, DataTable, TableToggle } from '../components/Card'
import { Chart } from '../components/Chart'
import { ClaudeForm, GarminStatus, KeyHelp } from '../components/Setup'
import { addDays, localToday, number } from '../format'
import { useTheme } from '../theme'

const WARN_SHARE = 0.8
const COST_RANGES = [30, 90, 365]
const HISTORY_DAYS = 365
const RECENT_ROWS = 20
const MORE_RECENT_ROWS = 200

function dollars(value: number, digits = 2): string {
  return `$${value.toFixed(digits)}`
}

function BudgetMeter({ usage }: { usage: Usage }) {
  const share = usage.budget_usd > 0 ? usage.household_cost_usd / usage.budget_usd : 1
  const state =
    share >= 1
      ? { color: 'bg-critical', text: 'text-critical', label: '■ Budget used up, chat is paused until the 1st' }
      : share >= WARN_SHARE
        ? { color: 'bg-warning', text: 'text-warning', label: '▲ Over 80% of the budget' }
        : { color: 'bg-accent', text: 'text-muted', label: null }
  return (
    <div>
      <p className="tabular text-2xl font-semibold text-primary">
        {dollars(usage.household_cost_usd)}
        <span className="text-sm font-normal text-muted"> of {dollars(usage.budget_usd)}</span>
      </p>
      {usage.household_cost_usd > usage.month_cost_usd && (
        <p className="tabular text-xs text-secondary">
          {dollars(usage.month_cost_usd)} from this profile, the rest from other profiles and research
        </p>
      )}
      <div
        className="mt-2 h-2 overflow-hidden rounded-full bg-raised"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={usage.budget_usd}
        aria-valuenow={usage.household_cost_usd}
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

function monthLabel(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

function CostHistoryCard() {
  const theme = useTheme()
  const [days, setDays] = useState(30)
  const daily = useQuery({ queryKey: ['usage', 'daily'], queryFn: () => fetchDailyUsage(HISTORY_DAYS) })
  const rows = useMemo(() => daily.data ?? [], [daily.data])
  const today = localToday()
  const shownDays = useMemo(
    () => Array.from({ length: days }, (_, index) => addDays(today, index - days + 1)),
    [days, today],
  )
  const shownRows = useMemo(() => rows.filter((row) => row.day >= shownDays[0]), [rows, shownDays])
  const option = useMemo(() => dailyCostOption(theme, shownDays, shownRows), [theme, shownDays, shownRows])
  const total = shownRows.reduce((sum, row) => sum + row.cost_usd, 0)
  const months = useMemo(() => {
    const totals = new Map<string, { cost: number; calls: number }>()
    for (const row of rows) {
      const month = totals.get(row.day.slice(0, 7)) ?? { cost: 0, calls: 0 }
      month.cost += row.cost_usd
      month.calls += row.calls
      totals.set(row.day.slice(0, 7), month)
    }
    return [...totals.entries()].sort(([a], [b]) => b.localeCompare(a))
  }, [rows])

  return (
    <Card
      title="API cost per day"
      subtitle="Everyone's Claude API spending, split by what the coach was doing"
      className="lg:col-span-2"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="tabular text-sm text-secondary">
          {dollars(total)} over the last {days} days, {dollars(total / days, 3)} a day on average
        </p>
        <div className="flex gap-2" role="group" aria-label="Time range">
          {COST_RANGES.map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => setDays(range)}
              aria-pressed={days === range}
              className={`rounded-lg border px-3 py-1.5 text-sm ${
                days === range
                  ? 'border-accent bg-raised font-semibold text-primary'
                  : 'border-line text-secondary hover:bg-raised'
              }`}
            >
              {range === HISTORY_DAYS ? '1 year' : `${range} days`}
            </button>
          ))}
        </div>
      </div>
      {daily.error && <p className="text-xs text-critical">{daily.error.message}</p>}
      <Chart option={option} label={`Stacked bar chart of API cost per day over the last ${days} days`} />
      {months.length > 0 && (
        <TableToggle
          columns={['Month', 'Calls', 'Cost']}
          rows={months.map(([month, totals]) => [monthLabel(month), number(totals.calls), dollars(totals.cost)])}
        />
      )}
    </Card>
  )
}

function TopicForm({ topic }: { topic: string | null }) {
  const queryClient = useQueryClient()
  const [value, setValue] = useState(topic ?? '')
  const save = useMutation({
    mutationFn: () => saveTopic(value.trim() || null),
    onSuccess: (data) => queryClient.setQueryData(['notifications'], data),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1 text-xs text-muted">
        <span className="mb-1 block">ntfy topic for this profile</span>
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          pattern="[A-Za-z0-9_\-]*"
          placeholder="a long, hard to guess name"
          className="w-full rounded-lg border border-line bg-page px-2 py-1.5 text-base text-primary sm:text-sm"
        />
      </label>
      <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-white">
        Save
      </button>
      {save.error && <span className="w-full text-xs text-critical">{save.error.message}</span>}
    </form>
  )
}

function NotificationsCard() {
  const notifications = useQuery({ queryKey: ['notifications'], queryFn: fetchNotifications })
  const test = useMutation({ mutationFn: sendTestNotification })
  const data = notifications.data
  if (!data) return null
  return (
    <Card title="Notifications" subtitle="Coach messages sent to this person's phone with ntfy">
      {data.enabled ? (
        <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">Subscribe to</dt>
          <dd className="break-all text-primary">
            {data.url.replace(/\/$/, '')}/{data.topic}
          </dd>
          <dt className="text-muted">Morning check-in</dt>
          <dd className="text-primary">{data.checkin_time ?? 'off, no API key'}</dd>
          <dt className="text-muted">Weekly review</dt>
          <dd className="text-primary">{data.review ?? 'off, no API key'}</dd>
          <dt className="text-muted">Activity feedback</dt>
          <dd className="text-primary">after each sync with a new activity</dd>
          {data.watch_time && (
            <>
              <dt className="text-muted">Watch workouts</dt>
              <dd className="text-primary">{data.watch_time}, tomorrow's sessions sent to Garmin</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="mb-3 text-sm text-secondary">
          Off. Pick a topic, save it, and subscribe to the same topic in the ntfy app. The coach still writes its
          messages to the Coach thread in Chat.
        </p>
      )}
      <TopicForm key={data.topic ?? ''} topic={data.topic} />
      {data.enabled && (
        <div className="mt-3 flex items-center gap-3">
          <button
            type="button"
            onClick={() => test.mutate()}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised"
          >
            Send a test notification
          </button>
          {test.data && (
            <span className={`text-xs ${test.data.sent ? 'text-secondary' : 'text-critical'}`}>
              {test.data.sent ? 'Sent' : 'Sending failed, check the server log'}
            </span>
          )}
        </div>
      )}
    </Card>
  )
}

function ClaudeCard({ usage }: { usage: Usage }) {
  const claude = useQuery({ queryKey: ['claude'], queryFn: fetchClaude })
  const data = claude.data
  return (
    <Card title="Claude" subtitle="The API key and monthly budget, shared by everyone">
      <dl className="mb-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">API key</dt>
        <dd className={data?.key_set ? 'text-primary' : 'text-warning'}>
          {!data
            ? '–'
            : data.key_set
              ? `ends in ${data.key_hint}, ${data.source === 'env' ? 'from .env' : 'saved in the app'}`
              : '▲ None yet, the coach is off'}
        </dd>
        <dt className="text-muted">Chat and weekly review</dt>
        <dd className="text-primary">{usage.chat_model}</dd>
        <dt className="text-muted">Plan building</dt>
        <dd className="text-primary">{usage.plan_model}</dd>
        <dt className="text-muted">Check-ins, feedback, papers</dt>
        <dd className="text-primary">{usage.background_model}</dd>
      </dl>
      {data && !data.key_set && (
        <div className="mb-3">
          <KeyHelp />
        </div>
      )}
      {data && <ClaudeForm key={`${data.key_hint}-${data.monthly_budget_usd}`} claude={data} />}
      {claude.error && <p className="text-xs text-critical">{claude.error.message}</p>}
    </Card>
  )
}

export function SettingsPage() {
  const [recentRows, setRecentRows] = useState(RECENT_ROWS)
  const usage = useQuery({ queryKey: ['usage', recentRows], queryFn: () => fetchUsage(recentRows) })
  if (usage.isPending) return <p className="text-sm text-muted">Loading…</p>
  if (usage.error) return <p className="text-sm text-critical">{usage.error.message}</p>
  const data = usage.data
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="API cost this month" subtitle="Claude API spending for everyone against the shared monthly budget">
        <BudgetMeter usage={data} />
      </Card>
      <ClaudeCard usage={data} />
      <Card title="Garmin" subtitle="This person's Garmin Connect login and history">
        <GarminStatus slug={currentProfile() ?? ''} />
        <a href="#add-person" className="mt-4 inline-block text-sm text-accent">
          Add another person
        </a>
      </Card>
      <NotificationsCard />
      <CostHistoryCard />
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
        {recentRows < MORE_RECENT_ROWS && data.recent.length === recentRows && (
          <button
            type="button"
            onClick={() => setRecentRows(MORE_RECENT_ROWS)}
            className="mt-3 rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised"
          >
            Show the last {MORE_RECENT_ROWS} calls
          </button>
        )}
      </Card>
    </div>
  )
}
