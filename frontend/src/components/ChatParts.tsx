import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatItem, ToolCall } from '../api'
import { shortDate } from '../format'

const TOOL_LABELS: Record<string, string> = {
  get_plan: 'Plan',
  propose_changes: 'Proposed changes',
  propose_plan: 'Proposed a plan',
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

export function ToolChips({ tools }: { tools: ToolCall[] }) {
  if (tools.length === 0) return null
  return (
    <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Data the coach looked up">
      {tools.map((tool) => (
        <li
          key={tool.id}
          className="rounded-md border border-line px-2 py-0.5 text-xs text-muted"
          title={JSON.stringify(tool.input)}
        >
          {tool.ok === false ? <span className="text-warning">▲ </span> : tool.ok ? '✓ ' : '… '}
          {toolText(tool)}
        </li>
      ))}
    </ul>
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
    </div>
  )
}
