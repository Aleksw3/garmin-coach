export type Wellness = {
  day: string
  sleep_day: string | null
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

const PROFILE_KEY = 'profile'

function readStoredProfile(): string | null {
  try {
    return localStorage.getItem(PROFILE_KEY)
  } catch {
    return null
  }
}

let activeProfile: string | null = readStoredProfile()

export function currentProfile(): string | null {
  return activeProfile
}

export function chooseProfile(slug: string): void {
  activeProfile = slug
  try {
    localStorage.setItem(PROFILE_KEY, slug)
  } catch {
    // The choice then lasts until the page reloads
  }
}

const linkedProfile = new URLSearchParams(window.location.search).get('profile')
if (linkedProfile) {
  chooseProfile(linkedProfile)
  window.history.replaceState(null, '', window.location.pathname + window.location.hash)
}

function withProfile(init?: RequestInit): RequestInit {
  if (!activeProfile) return init ?? {}
  const headers = new Headers(init?.headers)
  headers.set('X-Profile', activeProfile)
  return { ...init, headers }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, withProfile(init))
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null
    if (typeof body?.detail === 'string') throw new Error(body.detail)
    throw new Error(`${init?.method ?? 'GET'} ${path} failed with ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const fetchToday = () => request<Today>('/api/today')
export const fetchTrends = (weeks: number) => request<Trends>(`/api/trends?weeks=${weeks}`)
export const fetchSyncStatus = () => request<SyncStatus>('/api/sync')
export const startSync = () => request<SyncStatus>('/api/sync', { method: 'POST' })

export type Version = { commit: string | null; committed_at: string | null; subject: string | null }

export const fetchVersion = () => request<Version>('/api/version')

export type Conversation = { id: number; kind: 'chat' | 'coach'; title: string | null; updated_at: string }

export type ToolCall = { id: string; name: string; input: Record<string, unknown>; ok: boolean | null }

export type ChatItem = { role: 'user' | 'coach' | 'event' | 'summary'; text: string; tools: ToolCall[]; created_at: string }

export type ConversationDetail = Conversation & { items: ChatItem[]; cost_usd: number; context_tokens: number }

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
  trimp_coefficient?: number | null
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

export type CourseSlope = { start_km: number; end_km: number; change_m: number; grade: number }

export type CourseLeg = { name: string; start_km: number; end_km: number; gain_m: number; loss_m: number }

export type Course = {
  name: string | null
  distance_km: number
  gain_m: number
  loss_m: number
  profile: [number, number][]
  waypoints: { name: string; km: number }[]
  legs: CourseLeg[]
  climbs: CourseSlope[]
  descents: CourseSlope[]
}

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

export type DaySpend = {
  day: string
  purpose: string
  cost_usd: number
  calls: number
}

export type Usage = {
  month_cost_usd: number
  household_cost_usd: number
  budget_usd: number
  calls_this_month: number
  chat_model: string
  plan_model: string
  background_model: string
  recent: UsageRow[]
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

async function send(path: string, init: RequestInit): Promise<void> {
  const response = await fetch(path, withProfile(init))
  if (!response.ok) throw new Error(`${init.method} ${path} failed with ${response.status}`)
}

export const fetchConversations = () => request<Conversation[]>('/api/conversations')
export const createConversation = () => request<Conversation>('/api/conversations', { method: 'POST' })
export const fetchConversation = (id: number) => request<ConversationDetail>(`/api/conversations/${id}`)
export const compactConversation = (id: number) =>
  request<ConversationDetail>(`/api/conversations/${id}/compact`, { method: 'POST' })
export const deleteConversation = (id: number) => send(`/api/conversations/${id}`, { method: 'DELETE' })
export const fetchProfile = () => request<Profile>('/api/profile')
export const saveProfile = (profile: Profile) => request<Profile>('/api/profile', json('PUT', profile))
export const fetchGoals = () => request<Goal[]>('/api/goals')
export const createGoal = (goal: GoalInput) => request<Goal>('/api/goals', json('POST', goal))
export const updateGoal = (id: number, goal: GoalInput) => request<Goal>(`/api/goals/${id}`, json('PUT', goal))
export const deleteGoal = (id: number) => send(`/api/goals/${id}`, { method: 'DELETE' })
export type Projection = {
  distance_km: number
  gain_m: number
  effort_km: number
  fast_s: number
  slow_s: number
  references: { activity_id: number; day: string; name: string | null; distance_km: number; gain_m: number; seconds: number }[]
  arrivals: { name: string; km: number; fast_s: number; slow_s: number }[]
}

export const fetchProjection = (goalId: number) => request<Projection | null>(`/api/goals/${goalId}/projection`)
export const fetchCourse = (goalId: number) => request<Course | null>(`/api/goals/${goalId}/course`)
export const uploadCourse = (goalId: number, file: File) =>
  request<Course>(`/api/goals/${goalId}/course`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/gpx+xml' },
    body: file,
  })
export const deleteCourse = (goalId: number) => send(`/api/goals/${goalId}/course`, { method: 'DELETE' })
export const fetchNotes = () => request<Note[]>('/api/notes')
export const deleteNote = (id: number) => send(`/api/notes/${id}`, { method: 'DELETE' })
export const fetchUsage = (recent: number) => request<Usage>(`/api/usage?recent=${recent}`)
export const fetchDailyUsage = (days: number) => request<DaySpend[]>(`/api/usage/daily?days=${days}`)

export async function streamMessage(
  conversationId: number,
  text: string,
  onEvent: (event: ChatEvent) => void,
  purpose: 'chat' | 'plan' = 'chat',
): Promise<void> {
  const response = await fetch(
    `/api/conversations/${conversationId}/messages`,
    withProfile(json('POST', { text, purpose })),
  )
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

export type Step = {
  kind: 'warmup' | 'steady' | 'intervals' | 'cooldown'
  duration_min?: number | null
  distance_km?: number | null
  repeats?: number | null
  grade_pct?: number | null
  target?: string | null
  recovery?: string | null
  note?: string | null
}

export type Exercise = {
  name: string
  sets: number
  reps: string
  load?: string | null
  rest_s?: number | null
  warmup_sets?: { reps: number; weight_kg: number }[]
  note?: string | null
}

export type SessionSpec = {
  day: string
  sport: 'run' | 'vertical' | 'ski' | 'cycling' | 'strength' | 'other' | 'rest'
  kind: string
  title: string
  duration_min: number | null
  distance_km: number | null
  elevation_gain_m: number | null
  intensity: string | null
  steps: Step[]
  exercises: Exercise[]
  description: string | null
}

export type SessionMatch = { activity_id: number; compliance: number | null; details: Record<string, number[]> }

export type PlannedSession = SessionSpec & {
  id: number
  plan_id: number
  skipped: boolean
  sent_to_watch_at: string | null
  match: SessionMatch | null
}

export type PlanInfo = {
  id: number
  goal_id: number | null
  title: string
  description: string | null
  start_date: string
  end_date: string
}

export type Calendar = {
  start: string
  end: string
  plans: PlanInfo[]
  sessions: PlannedSession[]
  activities: Activity[]
}

export type ProposalChange = {
  op: 'add' | 'update' | 'remove'
  session_id: number | null
  session: SessionSpec | null
  current: PlannedSession | null
}

export type Proposal = {
  id: number
  created_at: string
  conversation_id: number | null
  summary: string
  reason: string
  status: string
  plan: { title: string; goal_id: number | null; description: string | null; sessions: SessionSpec[] } | null
  changes: ProposalChange[]
  season: { goal_id: number | null; weeks: SeasonWeekSpec[] } | null
}

export type SeasonWeekSpec = {
  week_start: string
  phase: string
  hours: number
  climb_m: number | null
  longest_h: number | null
  focus: string | null
}

export type SeasonWeek = SeasonWeekSpec & { done_hours: number; done_climb_m: number; done_longest_h: number }

export const fetchSeason = (start: string, end: string) =>
  request<SeasonWeek[]>(`/api/season?start=${start}&end=${end}`)

export const fetchCalendar = (start: string, end: string) =>
  request<Calendar>(`/api/plan?start=${start}&end=${end}`)
export const fetchProposals = () => request<Proposal[]>('/api/proposals')
export const acceptProposal = (id: number) => request<Proposal>(`/api/proposals/${id}/accept`, { method: 'POST' })
export const rejectProposal = (id: number) => request<Proposal>(`/api/proposals/${id}/reject`, { method: 'POST' })
export const setSkipped = (id: number, skipped: boolean) =>
  request<PlannedSession>(`/api/sessions/${id}`, json('PATCH', { skipped }))
export const deleteSession = (id: number) => send(`/api/sessions/${id}`, { method: 'DELETE' })
export const sendToWatch = (id: number) => request<PlannedSession>(`/api/sessions/${id}/watch`, { method: 'POST' })
export const removeFromWatch = (id: number) =>
  request<PlannedSession>(`/api/sessions/${id}/watch`, { method: 'DELETE' })

export type SetValues = {
  exercise_category: string | null
  exercise_name: string | null
  reps: number | null
  weight_kg: number | null
}

export type StrengthSetRow = SetValues & {
  set_index: number
  duration_s: number | null
  original: SetValues
  edited: boolean
  deleted: boolean
}

export type Lap = {
  lap_index: number
  distance_m: number | null
  duration_s: number | null
  elevation_gain_m: number | null
  elevation_loss_m: number | null
  avg_hr: number | null
  max_hr: number | null
  avg_speed_mps: number | null
  avg_grade_adjusted_speed_mps: number | null
  avg_power_w: number | null
  intensity_type: string | null
}

export type ActivityDetail = Activity & {
  drift_first_hr: number | null
  drift_second_hr: number | null
  hr_drift_pct: number | null
  decoupling_pct: number | null
  moving_s: number | null
  elevation_loss_m: number | null
  max_hr: number | null
  avg_speed_mps: number | null
  avg_grade_adjusted_speed_mps: number | null
  avg_power_w: number | null
  calories: number | null
  aerobic_training_effect: number | null
  anaerobic_training_effect: number | null
  training_effect_label: string | null
  location_name: string | null
  laps: Lap[]
  zones: { kind: string; zone: number; seconds: number; low_boundary: number | null }[]
  sets: StrengthSetRow[]
  planned: { session_id: number; title: string; compliance: number | null; details: Record<string, number[]> } | null
  rating: Rating | null
  exercise_categories: string[]
}

export type Rating = { effort: number | null; legs: number | null; pain: string | null; note: string | null }

export const rateActivity = (id: number, rating: Rating) =>
  request<Rating>(`/api/activities/${id}/rating`, json('PUT', rating))

export const fetchActivity = (id: number) => request<ActivityDetail>(`/api/activities/${id}`)
export const editSet = (activityId: number, setIndex: number, values: SetValues & { deleted: boolean }) =>
  request<StrengthSetRow[]>(`/api/activities/${activityId}/sets/${setIndex}`, json('PUT', values))
export const restoreSet = (activityId: number, setIndex: number) =>
  send(`/api/activities/${activityId}/sets/${setIndex}/edit`, { method: 'DELETE' })

export type LatestCoachMessage = {
  conversation_id: number
  title: string | null
  label: string | null
  text: string
  created_at: string
}

export type Notifications = {
  enabled: boolean
  url: string
  topic: string | null
  checkin_time: string | null
  review: string | null
  watch_time: string | null
}

export const fetchLatestCoach = () => request<LatestCoachMessage | null>('/api/coach/latest')
export const fetchNotifications = () => request<Notifications>('/api/notifications')
export const sendTestNotification = () => request<{ sent: boolean }>('/api/notifications/test', { method: 'POST' })

export type EvidenceFields = {
  claim: string
  population: string
  intervention: string
  outcome: string
  design: string
  sample_size: number | null
  effect: string
  takeaway: string
  limitations: string
  notes: string | null
}

export type EvidenceEntry = EvidenceFields & {
  id: number
  topic_id: number | null
  pmid: string
  doi: string | null
  title: string
  authors: string
  journal: string | null
  year: number | null
  abstract: string
  publication_types: string
  grade: string
  status: 'pending' | 'approved' | 'rejected' | 'skipped'
  disputed_by_id: number | null
  citation: string
  created_at: string
  reviewed_at: string | null
}

export type EvidenceTopicInput = { name: string; query: string; weekly_limit: number; active: boolean }

export type EvidenceTopic = EvidenceTopicInput & {
  id: number
  last_fetched_at: string | null
  approved: number
  pending: number
}

export type EvidenceFetchStatus = {
  running: boolean
  task: 'fetch' | 'rewrite' | 'add' | null
  available: boolean
  last: { started_at: string; finished_at: string | null; added: number; errors: string[] } | null
}

export type PubMedHit = {
  pmid: string
  doi: string | null
  title: string
  authors: string[]
  journal: string | null
  year: number | null
  publication_types: string[]
  abstract: string
  status: EvidenceEntry['status'] | null
}

export const searchPubMed = (q: string, limit: number) =>
  request<PubMedHit[]>(`/api/evidence/pubmed?q=${encodeURIComponent(q)}&limit=${limit}`)
export const addPapers = (pmids: string[]) =>
  request<EvidenceFetchStatus>('/api/evidence/add', json('POST', { pmids }))
export const fetchEvidence = (status: EvidenceEntry['status'], q = '') =>
  request<EvidenceEntry[]>(`/api/evidence?status=${status}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const saveEvidence = (id: number, fields: EvidenceFields) =>
  request<EvidenceEntry>(`/api/evidence/${id}`, json('PUT', fields))
export const setEvidenceStatus = (id: number, status: EvidenceEntry['status']) =>
  request<EvidenceEntry>(`/api/evidence/${id}/status`, json('POST', { status }))
export const setDisputedBy = (id: number, disputedById: number | null) =>
  request<EvidenceEntry>(`/api/evidence/${id}/disputed`, json('PUT', { disputed_by_id: disputedById }))
export const fetchEvidenceTopics = () => request<EvidenceTopic[]>('/api/evidence/topics')
export const createEvidenceTopic = (topic: EvidenceTopicInput) =>
  request<EvidenceTopic>('/api/evidence/topics', json('POST', topic))
export const updateEvidenceTopic = (id: number, topic: EvidenceTopicInput) =>
  request<EvidenceTopic>(`/api/evidence/topics/${id}`, json('PUT', topic))
export const deleteEvidenceTopic = (id: number) => send(`/api/evidence/topics/${id}`, { method: 'DELETE' })
export const fetchEvidenceStatus = () => request<EvidenceFetchStatus>('/api/evidence/fetch')
export const startEvidenceFetch = () => request<EvidenceFetchStatus>('/api/evidence/fetch', { method: 'POST' })
export const startTakeawayRewrite = () =>
  request<EvidenceFetchStatus>('/api/evidence/rewrite-takeaways', { method: 'POST' })

export type ThresholdMethod = 'drift_test' | 'lab' | 'time_trial' | 'estimate'

export type ThresholdTestInput = {
  day: string
  lt1_hr: number
  lt2_hr: number
  method: ThresholdMethod
  activity_id?: number | null
  notes?: string | null
}

export type ThresholdTest = ThresholdTestInput & { id: number }

export type HrZone = { number: number; name: string; low: number | null; high: number | null }

export type Zones = { current: ThresholdTest | null; zones: HrZone[]; tests: ThresholdTest[] }

export type ZoneWeek = { week_start: string; seconds: number[] }

export const fetchZones = () => request<Zones>('/api/zones')
export const addThresholdTest = (test: ThresholdTestInput) => request<Zones>('/api/zones/tests', json('POST', test))
export const deleteThresholdTest = (id: number) => send(`/api/zones/tests/${id}`, { method: 'DELETE' })
export const fetchZoneWeeks = (weeks: number, sports: 'running' | 'all') =>
  request<ZoneWeek[]>(`/api/zones/weekly?weeks=${weeks}&sports=${sports}`)

export type Hill = {
  start: [number, number]
  end: [number, number]
  length_m: number
  gain_m: number
  grade_pct: number
  steepest_pct: number
  rep_seconds: number
  away_m: number
  visits: number
  last_day: string
  map_url: string
}

export type Hills = { flat_speed_mps: number; speed_from_data: boolean; hills: Hill[] }

export const fetchHills = (minutes: number | null, meters: number | null, grade: number) =>
  request<Hills>(
    `/api/hills?grade=${grade}&` + (minutes !== null ? `minutes=${minutes}` : `meters=${meters}`),
  )

export type ProfileSummary = { slug: string; name: string }

export const fetchProfiles = () => request<ProfileSummary[]>('/api/profiles')
export const saveTopic = (topic: string | null) =>
  request<Notifications>('/api/notifications', json('PUT', { topic }))
export const addProfile = (name: string, trimp_coefficient: number) =>
  request<ProfileSummary>('/api/profiles', json('POST', { name, trimp_coefficient }))

export type Claude = {
  available: boolean
  key_set: boolean
  key_hint: string | null
  source: 'app' | 'env' | null
  monthly_budget_usd: number | null
}

export const fetchClaude = () => request<Claude>('/api/claude')
export const saveClaude = (settings: { api_key?: string; monthly_budget_usd?: number }) =>
  request<Claude>('/api/claude', json('PUT', settings))

export type Garmin = {
  connected: boolean
  waiting_for_code: boolean
  syncing: boolean
  backfill: { days: number; started_at: string } | null
  backfill_reached: string | null
  oldest_activity: string | null
  last_sync: string | null
}

export const fetchGarmin = () => request<Garmin>('/api/garmin')
export const garminLogin = (email: string, password: string) =>
  request<Garmin>('/api/garmin/login', json('POST', { email, password }))
export const garminCode = (code: string) => request<Garmin>('/api/garmin/code', json('POST', { code }))
export const startBackfill = (days: number) => request<Garmin>('/api/garmin/backfill', json('POST', { days }))
