import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatItem, ToolCall } from '../api'
import { shortDate } from '../format'

const TOOL_LABELS: Record<string, string> = {
  get_plan: 'Plan',
  propose_changes: 'Proposed changes',
  propose_plan: 'Proposed a plan',
  propose_season: 'Proposed a season outline',
  get_activity: 'Activity details',
  get_goals: 'Goals',
  get_load: 'Training load',
  get_notes: 'Notes',
  get_profile: 'Profile',
  get_running_weeks: 'Running weeks',
  get_strength: 'Strength',
  get_weekly_summary: 'Weekly summary',
  get_wellness: 'Sleep and recovery',
  list_activities: 'Activities',
  save_note: 'Saved a note',
  set_activity_climbing: 'Saved climbing for activity',
}


function toolText(tool: ToolCall): string {
  const label = TOOL_LABELS[tool.name] ?? tool.name
  const { start, end } = tool.input
  if (typeof start === 'string' && typeof end === 'string') {
    return `${label}, ${shortDate(start)} to ${shortDate(end)}`
  }
  if (typeof tool.input.activity_id === 'number') return `${label} ${tool.input.activity_id}`
  return label
}

const PROPOSAL_TOOLS = ['propose_plan', 'propose_changes', 'propose_season']

function isLookup(tool: ToolCall): boolean {
  return tool.name.startsWith('get_') || tool.name.startsWith('list_')
}

function toolSummary(tools: ToolCall[]): string {
  const lookups = tools.filter(isLookup).length
  const actions = tools.filter((tool) => !isLookup(tool)).map((tool) => (TOOL_LABELS[tool.name] ?? tool.name).toLowerCase())
  const failed = tools.filter((tool) => tool.ok === false).length
  const parts = [
    lookups > 0 ? `read ${lookups} ${lookups === 1 ? 'source' : 'sources'}` : null,
    ...actions,
    failed > 0 ? `${failed} failed` : null,
  ].filter((part) => part !== null)
  const text = parts.join(', ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function ToolChips({ tools }: { tools: ToolCall[] }) {
  if (tools.length === 0) return null
  const working = tools.some((tool) => tool.ok === null)
  return (
    <details className="mb-2 text-xs text-muted">
      <summary className="cursor-pointer select-none">
        {working ? `Working: ${toolText(tools[tools.length - 1])}` : toolSummary(tools)}
      </summary>
      <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label="Data the coach looked up">
        {tools.map((tool) => (
          <li key={tool.id} className="rounded-md border border-line px-2 py-0.5" title={JSON.stringify(tool.input)}>
            {tool.ok === false ? <span className="text-warning">▲ </span> : tool.ok ? '✓ ' : '… '}
            {toolText(tool)}
          </li>
        ))}
      </ul>
    </details>
  )
}

export function CoachText({ text }: { text: string }) {
  return (
    <div className="coach-text text-sm leading-relaxed text-primary">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  )
}

export function Bubble({ item }: { item: Pick<ChatItem, 'role' | 'text' | 'tools'> }) {
  if (item.role === 'event') {
    return (
      <p className="text-center text-xs text-muted">
        <span className="rounded-full border border-line px-2 py-0.5">Scheduled: {item.text}</span>
      </p>
    )
  }
  if (item.role === 'summary') {
    return (
      <details className="rounded-xl border border-line px-3 py-2">
        <summary className="cursor-pointer text-xs text-muted">
          Summary of the earlier messages. The coach reads from here on.
        </summary>
        <div className="mt-2">
          <CoachText text={item.text} />
        </div>
      </details>
    )
  }
  if (item.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-xl bg-raised px-3 py-2 text-sm whitespace-pre-wrap text-primary">
          {item.text}
        </p>
      </div>
    )
  }
  return (
    <div className="min-w-0">
      <ToolChips tools={item.tools} />
      {item.text && <CoachText text={item.text} />}
      {item.tools.some((tool) => PROPOSAL_TOOLS.includes(tool.name) && tool.ok) && (
        <a
          href="#plan"
          className="mt-3 inline-block rounded-lg border border-accent px-3 py-1.5 text-sm font-semibold text-accent hover:bg-raised"
        >
          Review the proposal on Plan
        </a>
      )}
    </div>
  )
}
