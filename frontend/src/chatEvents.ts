import type { ChatEvent, ToolCall } from './api'

export type Pending = {
  user: string
  coach: string
  tools: ToolCall[]
  error: string | null
}

export function applyEvent(pending: Pending, event: ChatEvent): Pending {
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
