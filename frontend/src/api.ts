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
