import type { PlannedSession } from './api'
import { number } from './format'

export function sessionStatus(session: PlannedSession, today: string): string | null {
  if (session.skipped) return 'Skipped'
  if (session.match) {
    return `✓ Done${session.match.compliance !== null ? `, ${number(session.match.compliance)}% of the targets` : ''}`
  }
  if (session.day < today && session.sport !== 'rest') return '▲ Not done'
  return null
}
