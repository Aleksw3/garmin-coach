export type Wellness = {
  day: string
  sleep_h: number | null
  sleep_score: number | null
  hrv_last_night: number | null
  hrv_status: string | null
  resting_hr: number | null
  readiness_score: number | null
  readiness_level: string | null
  training_status: string | null
  body_battery_at_wake: number | null
}

export type Baseline = {
  day: string
  rolling: number
  low: number
  high: number
  status: 'below' | 'within' | 'above'
}

export type Load = { day: string; load: number; acute: number; chronic: number }

export type GroupTotals = {
  week_start: string
  sport_group: string
  activities: number
  distance_km: number
  hours: number
  elevation_gain_m: number
}

export type Activity = {
  id: number
  name: string | null
  type_key: string
  sport_group: string
  start_time_local: string
  duration_s: number | null
  distance_km: number | null
  elevation_gain_m: number | null
  avg_hr: number | null
  training_load: number | null
  terrain: string | null
  is_commute: boolean
}

export type Today = {
  day: string
  wellness: Wellness | null
  hrv: Baseline | null
  resting_hr: Baseline | null
  load: Load | null
  week: GroupTotals[]
  recent_activities: Activity[]
}

export type HrvPoint = {
  day: string
  value: number | null
  rolling: number | null
  low: number | null
  high: number | null
}

export type RunWeek = {
  week_start: string
  runs: number
  distance_km: number
  hours: number
  elevation_gain_m: number
  elevation_loss_m: number
  longest_run_h: number
  flat_h: number
  rolling_h: number
  mountain_h: number
  back_to_back_long_days: number
}

export type Trends = {
  first_week: string
  last_week: string
  weekly_totals: GroupTotals[]
  load: Load[]
  hrv: HrvPoint[]
  run_weeks: RunWeek[]
  strength_weeks: { week_start: string; sets_per_muscle: Record<string, number> }[]
  one_rep_max: { exercise: string; day: string; kg: number }[]
}

export type SyncRun = {
  started_at: string
  finished_at: string | null
  kind: string
  status: string
  calls: number
  failed_calls: number
  error: string | null
}

export type SyncStatus = { running: boolean; last_sync: string | null; runs: SyncRun[] }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} failed with ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const fetchToday = () => request<Today>('/api/today')
export const fetchTrends = (weeks: number) => request<Trends>(`/api/trends?weeks=${weeks}`)
export const fetchSyncStatus = () => request<SyncStatus>('/api/sync')
export const startSync = () => request<SyncStatus>('/api/sync', { method: 'POST' })

export type Conversation = { id: number; title: string | null; updated_at: string }

export type ToolCall = { id: string; name: string; input: Record<string, unknown>; ok: boolean | null }

export type ChatItem = { role: 'user' | 'coach'; text: string; tools: ToolCall[]; created_at: string }

export type ConversationDetail = Conversation & { items: ChatItem[] }

export type ChatEvent =
  | { type: 'text'; text: string }
  | { type: 'tool_call'; id: string; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; id: string; ok: boolean }
  | { type: 'error'; message: string }
  | { type: 'done'; turn_cost_usd: number; month_cost_usd: number; budget_usd: number }

export type Profile = {
  name: string | null
  birth_year: number | null
  sex: string | null
  height_cm: number | null
  max_hr: number | null
  training_days: string | null
  injuries: string | null
  equipment: string | null
  notes: string | null
}

export type GoalInput = {
  kind: 'race' | 'strength' | 'habit' | 'other'
  title: string
  target_date: string | null
  target: string | null
  distance_km: number | null
  elevation_gain_m: number | null
  terrain: string | null
  cutoffs: string | null
  notes: string | null
  priority: 'A' | 'B' | 'C'
  status: 'active' | 'done' | 'dropped'
}

export type Goal = GoalInput & { id: number }

export type Note = { id: number; created_at: string; text: string }

export type UsageRow = {
  created_at: string
  model: string
  purpose: string
  input_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  output_tokens: number
  cost_usd: number
}

export type Usage = {
  month_cost_usd: number
  budget_usd: number
  calls_this_month: number
  chat_model: string
  recent: UsageRow[]
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

async function send(path: string, init: RequestInit): Promise<void> {
  const response = await fetch(path, init)
  if (!response.ok) throw new Error(`${init.method} ${path} failed with ${response.status}`)
}

export const fetchConversations = () => request<Conversation[]>('/api/conversations')
export const createConversation = () => request<Conversation>('/api/conversations', { method: 'POST' })
export const fetchConversation = (id: number) => request<ConversationDetail>(`/api/conversations/${id}`)
export const deleteConversation = (id: number) => send(`/api/conversations/${id}`, { method: 'DELETE' })
export const fetchProfile = () => request<Profile>('/api/profile')
export const saveProfile = (profile: Profile) => request<Profile>('/api/profile', json('PUT', profile))
export const fetchGoals = () => request<Goal[]>('/api/goals')
export const createGoal = (goal: GoalInput) => request<Goal>('/api/goals', json('POST', goal))
export const updateGoal = (id: number, goal: GoalInput) => request<Goal>(`/api/goals/${id}`, json('PUT', goal))
export const deleteGoal = (id: number) => send(`/api/goals/${id}`, { method: 'DELETE' })
export const fetchNotes = () => request<Note[]>('/api/notes')
export const deleteNote = (id: number) => send(`/api/notes/${id}`, { method: 'DELETE' })
export const fetchUsage = () => request<Usage>('/api/usage')

export async function streamMessage(
  conversationId: number,
  text: string,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, json('POST', { text }))
  if (!response.ok || !response.body) throw new Error(`Sending failed with ${response.status}`)
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += value
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      if (chunk.startsWith('data: ')) onEvent(JSON.parse(chunk.slice(6)) as ChatEvent)
    }
  }
}
