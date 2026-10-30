export function hours(value: number | null | undefined): string {
  if (value === null || value === undefined) return '–'
  const whole = Math.floor(value)
  const minutes = Math.round((value - whole) * 60)
  return whole > 0 ? `${whole} h ${minutes.toString().padStart(2, '0')} min` : `${minutes} min`
}

export function duration(seconds: number | null | undefined): string {
  return seconds === null || seconds === undefined ? '–' : hours(seconds / 3600)
}

export function number(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '–'
  return value.toLocaleString('en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function shortDate(isoDate: string): string {
  return new Date(`${isoDate.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

export function weekday(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

export function sentence(value: string | null | undefined): string {
  if (!value) return '–'
  const words = value.replaceAll('_', ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function localToday(): string {
  return new Date().toLocaleDateString('sv-SE')
}

export function mondayOf(isoDate: string): string {
  const weekday = new Date(`${isoDate}T00:00:00Z`).getUTCDay()
  return addDays(isoDate, -((weekday + 6) % 7))
}

export function dayLabel(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}
