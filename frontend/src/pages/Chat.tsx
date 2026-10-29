import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  createConversation,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  streamMessage,
  type ChatEvent,
  type ChatItem,
  type ToolCall,
} from '../api'
import { shortDate } from '../format'

const TOOL_LABELS: Record<string, string> = {
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

const STARTERS = [
  'How did my last 4 weeks of running compare to what my race needs?',
  'How am I recovering this week?',
  'What should my next week of training look like?',
]

type Pending = {
  user: string
  coach: string
  tools: ToolCall[]
  error: string | null
}

type Cost = { turn: number; month: number; budget: number }

function toolText(tool: ToolCall): string {
  const label = TOOL_LABELS[tool.name] ?? tool.name
  const { start, end } = tool.input
  if (typeof start === 'string' && typeof end === 'string') {
    return `${label}, ${shortDate(start)} to ${shortDate(end)}`
  }
  if (typeof tool.input.activity_id === 'number') return `${label} ${tool.input.activity_id}`
  return label
}

function ToolChips({ tools }: { tools: ToolCall[] }) {
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

function CoachText({ text }: { text: string }) {
  return (
    <div className="coach-text text-sm leading-relaxed text-primary">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  )
}

function Bubble({ item }: { item: Pick<ChatItem, 'role' | 'text' | 'tools'> }) {
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

function applyEvent(pending: Pending, event: ChatEvent): Pending {
  switch (event.type) {
    case 'text':
      return { ...pending, coach: pending.coach + event.text }
    case 'tool_call':
      return {
        ...pending,
        coach: pending.coach ? `${pending.coach}\n\n` : '',
        tools: [...pending.tools, { id: event.id, name: event.name, input: event.input, ok: null }],
      }
    case 'tool_result':
      return {
        ...pending,
        tools: pending.tools.map((tool) => (tool.id === event.id ? { ...tool, ok: event.ok } : tool)),
      }
    case 'error':
      return { ...pending, error: event.message }
    default:
      return pending
  }
}

function Composer({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState('')
  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    if (disabled || !text.trim()) return
    onSend(text.trim())
    setText('')
  }
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) submit(event)
  }
  return (
    <form
      onSubmit={submit}
      className="sticky bottom-0 mt-4 flex items-end gap-2 bg-page pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]"
    >
      <label htmlFor="chat-input" className="sr-only">
        Message to the coach
      </label>
      <textarea
        id="chat-input"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        placeholder="Ask your coach"
        className="min-w-0 flex-1 resize-none rounded-xl border border-line bg-surface px-3 py-2 text-base text-primary placeholder:text-muted focus:border-accent focus:outline-none sm:text-sm"
      />
      <button
        type="submit"
        disabled={disabled || !text.trim()}
        className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
      >
        Send
      </button>
    </form>
  )
}

function Thread({ id, onCreated }: { id: number | null; onCreated: (id: number) => void }) {
  const queryClient = useQueryClient()
  const conversation = useQuery({
    queryKey: ['conversation', id],
    queryFn: () => fetchConversation(id!),
    enabled: id !== null,
  })
  const [pending, setPending] = useState<Pending | null>(null)
  const [cost, setCost] = useState<Cost | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [conversation.data, pending?.coach, pending?.tools.length])

  const send = async (text: string) => {
    setPending({ user: text, coach: '', tools: [], error: null })
    setCost(null)
    let conversationId = id
    try {
      if (conversationId === null) {
        conversationId = (await createConversation()).id
        onCreated(conversationId)
      }
      await streamMessage(conversationId, text, (event) => {
        if (event.type === 'done') {
          setCost({ turn: event.turn_cost_usd, month: event.month_cost_usd, budget: event.budget_usd })
        }
        setPending((current) => (current ? applyEvent(current, event) : current))
      })
    } catch (error) {
      setPending((current) => current && { ...current, error: String(error) })
      return
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] }),
      queryClient.invalidateQueries({ queryKey: ['conversations'] }),
      queryClient.invalidateQueries({ queryKey: ['usage'] }),
    ])
    setPending((current) => (current?.error ? current : null))
  }

  const items = conversation.data?.items ?? []
  const busy = pending !== null && pending.error === null
  return (
    <div className="flex min-h-[calc(100dvh-7rem)] min-w-0 flex-col">
      <div className="flex-1 space-y-4" aria-live="polite">
        {items.length === 0 && !pending && (
          <div className="space-y-2 pt-4">
            <p className="text-sm text-muted">
              Ask about your training, recovery or race. The coach reads your Garmin data before it answers.
            </p>
            {STARTERS.map((starter) => (
              <button
                key={starter}
                type="button"
                onClick={() => void send(starter)}
                className="block w-full rounded-xl border border-line px-3 py-2 text-left text-sm text-secondary hover:bg-raised"
              >
                {starter}
              </button>
            ))}
          </div>
        )}
        {items.map((item, index) => (
          <Bubble key={index} item={item} />
        ))}
        {pending && (
          <>
            <Bubble item={{ role: 'user', text: pending.user, tools: [] }} />
            <Bubble item={{ role: 'coach', text: pending.coach, tools: pending.tools }} />
            {busy && !pending.coach && pending.tools.length === 0 && (
              <p className="text-sm text-muted">The coach is thinking…</p>
            )}
            {pending.error && <p className="text-sm text-critical">{pending.error}</p>}
          </>
        )}
        {cost && !busy && (
          <p className="tabular text-xs text-muted">
            This answer cost ${cost.turn.toFixed(3)}. This month: ${cost.month.toFixed(2)} of $
            {cost.budget.toFixed(2)}.
          </p>
        )}
        <div ref={bottom} />
      </div>
      <Composer disabled={busy} onSend={(text) => void send(text)} />
    </div>
  )
}

export function ChatPage() {
  const queryClient = useQueryClient()
  const conversations = useQuery({ queryKey: ['conversations'], queryFn: fetchConversations })
  const [selected, setSelected] = useState<number | null | undefined>(undefined)
  const [threadKey, setThreadKey] = useState(0)
  const list = conversations.data ?? []
  const active = selected === undefined ? (list[0]?.id ?? null) : selected

  const open = (id: number | null | undefined) => {
    setSelected(id)
    setThreadKey((key) => key + 1)
  }

  const remove = async () => {
    if (active === null || !window.confirm('Delete this conversation?')) return
    await deleteConversation(active)
    open(undefined)
    await queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }

  return (
    <div className="grid min-w-0 gap-4 md:grid-cols-[14rem_1fr]">
      <aside className="min-w-0">
        <div className="flex gap-2 md:flex-col">
          <button
            type="button"
            onClick={() => open(null)}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-primary hover:bg-raised"
          >
            New conversation
          </button>
          <label htmlFor="thread-select" className="sr-only">
            Conversation
          </label>
          <select
            id="thread-select"
            value={active ?? ''}
            onChange={(event) => open(event.target.value ? Number(event.target.value) : null)}
            className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-primary md:hidden"
          >
            <option value="">New conversation</option>
            {list.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title ?? 'Untitled'}
              </option>
            ))}
          </select>
        </div>
        <ul className="mt-3 hidden space-y-1 md:block">
          {list.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => open(c.id)}
                aria-current={c.id === active ? 'true' : undefined}
                className={`w-full truncate rounded-lg px-3 py-1.5 text-left text-sm ${
                  c.id === active ? 'bg-raised text-primary' : 'text-secondary hover:bg-raised'
                }`}
              >
                {c.title ?? 'Untitled'}
              </button>
            </li>
          ))}
        </ul>
        {active !== null && (
          <button
            type="button"
            onClick={() => void remove()}
            className="mt-2 text-xs text-muted hover:text-critical md:mt-3"
          >
            Delete this conversation
          </button>
        )}
      </aside>
      <Thread key={threadKey} id={active} onCreated={(id) => setSelected(id)} />
    </div>
  )
}
