import { useSyncExternalStore } from 'react'

export const SPORT_GROUPS = [
  { key: 'run', label: 'Running', slot: 1 },
  { key: 'vertical', label: 'Hiking and stairs', slot: 2 },
  { key: 'ski', label: 'Skiing', slot: 3 },
  { key: 'cycling', label: 'Cycling', slot: 4 },
  { key: 'commute', label: 'Bike commute', slot: 5 },
  { key: 'strength', label: 'Strength', slot: 6 },
  { key: 'other', label: 'Other', slot: 7 },
] as const

const FOLDED_INTO_OTHER = new Set(['other_endurance', 'alpine', 'other'])

export function displayGroup(group: string): string {
  return FOLDED_INTO_OTHER.has(group) ? 'other' : group
}

export function groupLabel(group: string): string {
  return SPORT_GROUPS.find((g) => g.key === displayGroup(group))?.label ?? group
}

export type Theme = {
  surface: string
  textPrimary: string
  textSecondary: string
  textMuted: string
  gridline: string
  baseline: string
  series: (slot: number) => string
  sequentialLow: string
  sequentialHigh: string
}

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

function subscribe(onChange: () => void): () => void {
  darkQuery.addEventListener('change', onChange)
  return () => darkQuery.removeEventListener('change', onChange)
}

function readTheme(): Theme {
  const style = getComputedStyle(document.documentElement)
  const token = (name: string) => style.getPropertyValue(name).trim()
  return {
    surface: token('--surface'),
    textPrimary: token('--text-primary'),
    textSecondary: token('--text-secondary'),
    textMuted: token('--text-muted'),
    gridline: token('--gridline'),
    baseline: token('--baseline'),
    series: (slot: number) => token(`--series-${slot}`),
    sequentialLow: token('--sequential-low'),
    sequentialHigh: token('--sequential-high'),
  }
}

let cached: { dark: boolean; theme: Theme } | null = null

function snapshot(): Theme {
  if (cached === null || cached.dark !== darkQuery.matches) {
    cached = { dark: darkQuery.matches, theme: readTheme() }
  }
  return cached.theme
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, snapshot)
}

export function groupColor(theme: Theme, group: string): string {
  const slot = SPORT_GROUPS.find((g) => g.key === displayGroup(group))?.slot ?? 7
  return theme.series(slot)
}
