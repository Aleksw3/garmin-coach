import type { EChartsCoreOption } from 'echarts/core'
import type { DaySpend, GroupTotals, HrZone, HrvPoint, Load, Trends, ZoneWeek } from './api'
import { addDays, number, shortDate } from './format'
import { SPORT_GROUPS, displayGroup, type Theme } from './theme'

export const MUSCLES = [
  'quads',
  'hamstrings',
  'glutes',
  'calves',
  'core',
  'lower_back',
  'upper_back',
  'chest',
  'shoulders',
  'biceps',
  'triceps',
]

const BAR_MAX_WIDTH = 24

function axisStyle(theme: Theme) {
  return {
    axisLine: { lineStyle: { color: theme.baseline } },
    axisTick: { show: false },
    axisLabel: { color: theme.textMuted, fontSize: 11 },
    splitLine: { lineStyle: { color: theme.gridline, width: 1 } },
  }
}

function base(theme: Theme, legend: boolean) {
  return {
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'system-ui, -apple-system, Segoe UI, sans-serif' },
    grid: { left: 8, right: 8, top: legend ? 36 : 12, bottom: 4, containLabel: true },
    legend: legend
      ? {
          top: 0,
          left: 0,
          itemWidth: 12,
          itemHeight: 8,
          textStyle: { color: theme.textSecondary, fontSize: 11 },
        }
      : undefined,
    tooltip: {
      backgroundColor: theme.surface,
      borderColor: theme.baseline,
      textStyle: { color: theme.textPrimary, fontSize: 12 },
    },
  }
}

function tooltipRow(color: string, label: string, value: string): string {
  return (
    `<div style="display:flex;align-items:center;gap:6px">` +
    `<span style="display:inline-block;width:10px;height:2px;background:${color}"></span>` +
    `<b>${value}</b><span style="opacity:.75">${label}</span></div>`
  )
}

export function weekLabels(trends: Trends): string[] {
  const weeks: string[] = []
  for (let week = trends.first_week; week <= trends.last_week; week = addDays(week, 7)) {
    weeks.push(week)
  }
  return weeks
}

export function sumByWeekAndGroup(
  totals: GroupTotals[],
  metric: 'hours' | 'elevation_gain_m' | 'distance_km',
): Map<string, Map<string, number>> {
  const sums = new Map<string, Map<string, number>>()
  for (const row of totals) {
    const group = displayGroup(row.sport_group)
    const week = sums.get(row.week_start) ?? new Map<string, number>()
    week.set(group, (week.get(group) ?? 0) + row[metric])
    sums.set(row.week_start, week)
  }
  return sums
}

export function weeklyStackOption(
  theme: Theme,
  weeks: string[],
  totals: GroupTotals[],
  metric: 'hours' | 'elevation_gain_m',
  groups: string[],
  unit: string,
): EChartsCoreOption {
  const sums = sumByWeekAndGroup(totals, metric)
  const shown = SPORT_GROUPS.filter((g) => groups.includes(g.key))
  const values = shown.map((g) => weeks.map((week) => sums.get(week)?.get(g.key) ?? 0))
  const topSeries = weeks.map((_, column) =>
    values.reduce((top, series, index) => (series[column] > 0 ? index : top), -1),
  )
  const digits = metric === 'hours' ? 1 : 0
  const legendRows = shown.length > 4 ? 2 : 1
  return {
    ...base(theme, true),
    grid: { ...base(theme, true).grid, top: 20 + legendRows * 20 },
    tooltip: {
      ...base(theme, true).tooltip,
      trigger: 'item',
      formatter: (p: { seriesName: string; value: number; name: string; color: string }) =>
        `<div style="opacity:.75">Week from ${shortDate(p.name)}</div>` +
        tooltipRow(p.color, p.seriesName, `${number(p.value, digits)} ${unit}`),
    },
    xAxis: {
      type: 'category',
      data: weeks,
      ...axisStyle(theme),
      splitLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: shortDate },
    },
    yAxis: { type: 'value', ...axisStyle(theme), axisLine: { show: false } },
    series: shown.map((group, index) => ({
      name: group.label,
      type: 'bar',
      stack: 'total',
      barMaxWidth: BAR_MAX_WIDTH,
      itemStyle: { color: theme.series(group.slot), borderColor: theme.surface, borderWidth: 1 },
      emphasis: { focus: 'none' },
      data: values[index].map((value, column) => ({
        value: Number(value.toFixed(2)),
        itemStyle: topSeries[column] === index ? { borderRadius: [4, 4, 0, 0] } : undefined,
      })),
    })),
  }
}

export function loadOption(theme: Theme, load: Load[]): EChartsCoreOption {
  const days = load.map((d) => d.day)
  const acuteColor = theme.series(1)
  const chronicColor = theme.series(2)
  return {
    ...base(theme, true),
    tooltip: {
      ...base(theme, true).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.baseline } },
      formatter: (params: { dataIndex: number }[]) => {
        const day = load[params[0].dataIndex]
        return (
          `<div style="opacity:.75">${shortDate(day.day)}</div>` +
          tooltipRow(acuteColor, 'Acute (7-day)', number(day.acute)) +
          tooltipRow(chronicColor, 'Chronic (42-day)', number(day.chronic)) +
          tooltipRow(theme.textMuted, 'Load that day', number(day.load))
        )
      },
    },
    xAxis: {
      type: 'category',
      data: days,
      ...axisStyle(theme),
      splitLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: shortDate },
    },
    yAxis: { type: 'value', ...axisStyle(theme), axisLine: { show: false } },
    series: [
      {
        name: 'Load that day',
        type: 'bar',
        barMaxWidth: 6,
        itemStyle: { color: theme.gridline, borderRadius: [2, 2, 0, 0] },
        data: load.map((d) => Math.round(d.load)),
      },
      {
        name: 'Acute (7-day)',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 2, color: acuteColor },
        itemStyle: { color: acuteColor },
        data: load.map((d) => Math.round(d.acute)),
      },
      {
        name: 'Chronic (42-day)',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 2, color: chronicColor },
        itemStyle: { color: chronicColor },
        data: load.map((d) => Math.round(d.chronic)),
      },
    ],
  }
}

export function hrvOption(theme: Theme, points: HrvPoint[]): EChartsCoreOption {
  const days = points.map((p) => p.day)
  const lineColor = theme.series(1)
  const valid = points.flatMap((p) => [p.value, p.low, p.high]).filter((v) => v !== null)
  const floor = valid.length ? Math.floor(Math.min(...(valid as number[])) / 5) * 5 - 5 : 0
  const legend = base(theme, true).legend
  return {
    ...base(theme, true),
    legend: { ...legend, data: ['Night', '7-day mean', 'Normal range'] },
    tooltip: {
      ...base(theme, true).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: theme.baseline } },
      formatter: (params: { dataIndex: number }[]) => {
        const point = points[params[0].dataIndex]
        const range =
          point.low === null || point.high === null
            ? '–'
            : `${number(point.low)} to ${number(point.high)} ms`
        return (
          `<div style="opacity:.75">${shortDate(point.day)}</div>` +
          tooltipRow(theme.textMuted, 'Night', `${number(point.value)} ms`) +
          tooltipRow(lineColor, '7-day mean', `${number(point.rolling)} ms`) +
          tooltipRow(theme.gridline, 'Normal range', range)
        )
      },
    },
    xAxis: {
      type: 'category',
      data: days,
      ...axisStyle(theme),
      splitLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: shortDate },
    },
    yAxis: { type: 'value', min: floor, ...axisStyle(theme), axisLine: { show: false } },
    series: [
      {
        name: 'band-floor',
        type: 'line',
        stack: 'band',
        showSymbol: false,
        silent: true,
        lineStyle: { opacity: 0 },
        data: points.map((p) => p.low),
        tooltip: { show: false },
      },
      {
        name: 'Normal range',
        type: 'line',
        stack: 'band',
        showSymbol: false,
        silent: true,
        lineStyle: { opacity: 0 },
        itemStyle: { color: lineColor },
        areaStyle: { color: lineColor, opacity: 0.12 },
        data: points.map((p) => (p.low === null || p.high === null ? null : p.high - p.low)),
      },
      {
        name: 'Night',
        type: 'scatter',
        symbolSize: 7,
        itemStyle: { color: theme.textMuted, borderColor: theme.surface, borderWidth: 2 },
        data: points.map((p) => p.value),
      },
      {
        name: '7-day mean',
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 2, color: lineColor },
        itemStyle: { color: lineColor },
        data: points.map((p) => (p.rolling === null ? null : Number(p.rolling.toFixed(1)))),
      },
    ],
  }
}

export function strengthOption(theme: Theme, weeks: string[], trends: Trends): EChartsCoreOption {
  const byWeek = new Map(trends.strength_weeks.map((w) => [w.week_start, w.sets_per_muscle]))
  const data: [number, number, number][] = []
  let max = 1
  weeks.forEach((week, x) => {
    MUSCLES.forEach((muscle, y) => {
      const sets = byWeek.get(week)?.[muscle] ?? 0
      max = Math.max(max, sets)
      data.push([x, y, sets])
    })
  })
  return {
    ...base(theme, false),
    grid: { left: 8, right: 8, top: 8, bottom: 40, containLabel: true },
    tooltip: {
      ...base(theme, false).tooltip,
      trigger: 'item',
      formatter: (p: { value: [number, number, number] }) =>
        `<div style="opacity:.75">Week from ${shortDate(weeks[p.value[0]])}</div>` +
        `<b>${number(p.value[2], 1)}</b> hard sets <span style="opacity:.75">${MUSCLES[
          p.value[1]
        ].replace('_', ' ')}</span>`,
    },
    xAxis: {
      type: 'category',
      data: weeks,
      ...axisStyle(theme),
      splitLine: { show: false },
      axisLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: shortDate },
    },
    yAxis: {
      type: 'category',
      data: MUSCLES.map((m) => m.replace('_', ' ')),
      inverse: true,
      ...axisStyle(theme),
      axisLine: { show: false },
      splitLine: { show: false },
    },
    visualMap: {
      min: 0,
      max,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemHeight: 120,
      itemWidth: 10,
      text: [`${number(max, 1)} sets`, '0'],
      textStyle: { color: theme.textMuted, fontSize: 11 },
      inRange: { color: [theme.surface, theme.sequentialLow, theme.sequentialHigh] },
    },
    series: [
      {
        type: 'heatmap',
        data,
        itemStyle: { borderColor: theme.surface, borderWidth: 2, borderRadius: 3 },
      },
    ],
  }
}

function mix(low: string, high: string, share: number): string {
  const channels = (hex: string) => [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16))
  const [a, b] = [channels(low), channels(high)]
  return `#${a.map((value, index) => Math.round(value + (b[index] - value) * share).toString(16).padStart(2, '0')).join('')}`
}

export function zoneColor(theme: Theme, zone: number): string {
  return mix(theme.sequentialLow, theme.sequentialHigh, (zone - 1) / 4)
}

export function zoneLabel(zone: HrZone): string {
  if (zone.low === null) return `up to ${zone.high}`
  if (zone.high === null) return `${zone.low}+`
  return `${zone.low}–${zone.high}`
}

export function zoneWeeksOption(theme: Theme, weeks: ZoneWeek[], zones: HrZone[]): EChartsCoreOption {
  const topZone = weeks.map((week) => week.seconds.reduce((top, value, index) => (value > 0 ? index : top), -1))
  return {
    ...base(theme, true),
    tooltip: {
      ...base(theme, true).tooltip,
      trigger: 'item',
      formatter: (p: { seriesName: string; value: number; name: string; color: string }) =>
        `<div style="opacity:.75">Week from ${shortDate(p.name)}</div>` +
        tooltipRow(p.color, p.seriesName, `${number(p.value, 1)} h`),
    },
    xAxis: {
      type: 'category',
      data: weeks.map((week) => week.week_start),
      ...axisStyle(theme),
      splitLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: shortDate },
    },
    yAxis: { type: 'value', ...axisStyle(theme), axisLine: { show: false } },
    series: zones.map((zone, index) => ({
      name: `Z${zone.number} ${zoneLabel(zone)}`,
      type: 'bar',
      stack: 'total',
      barMaxWidth: BAR_MAX_WIDTH,
      itemStyle: { color: zoneColor(theme, zone.number), borderColor: theme.surface, borderWidth: 1 },
      emphasis: { focus: 'none' },
      data: weeks.map((week, column) => ({
        value: Number((week.seconds[index] / 3600).toFixed(2)),
        itemStyle: topZone[column] === index ? { borderRadius: [4, 4, 0, 0] } : undefined,
      })),
    })),
  }
}

export const COST_GROUPS = [
  { key: 'chat', label: 'Chat', purposes: ['chat'], slot: 1 },
  { key: 'plan', label: 'Plans', purposes: ['plan', 'structure'], slot: 2 },
  { key: 'proactive', label: 'Check-ins and reviews', purposes: ['checkin', 'feedback', 'review'], slot: 3 },
  { key: 'research', label: 'Research', purposes: ['evidence'], slot: 4 },
  { key: 'other', label: 'Other', purposes: [], slot: 7 },
] as const

export function costGroup(purpose: string): string {
  return COST_GROUPS.find((g) => (g.purposes as readonly string[]).includes(purpose))?.key ?? 'other'
}

export function dailyCostOption(theme: Theme, days: string[], rows: DaySpend[]): EChartsCoreOption {
  const sums = new Map<string, Map<string, number>>()
  for (const row of rows) {
    const day = sums.get(row.day) ?? new Map<string, number>()
    const group = costGroup(row.purpose)
    day.set(group, (day.get(group) ?? 0) + row.cost_usd)
    sums.set(row.day, day)
  }
  const shown = COST_GROUPS.filter((g) => rows.some((row) => costGroup(row.purpose) === g.key))
  const values = shown.map((g) => days.map((day) => sums.get(day)?.get(g.key) ?? 0))
  const topSeries = days.map((_, column) =>
    values.reduce((top, series, index) => (series[column] > 0 ? index : top), -1),
  )
  const gapWidth = days.length > 120 ? 0 : 1
  return {
    ...base(theme, true),
    tooltip: {
      ...base(theme, true).tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: theme.gridline, opacity: 0.4 } },
      formatter: (params: { dataIndex: number }[]) => {
        const column = params[0].dataIndex
        const total = values.reduce((sum, series) => sum + series[column], 0)
        const lines = shown
          .map((group, index) => ({ group, value: values[index][column] }))
          .filter((line) => line.value > 0)
          .map((line) => tooltipRow(theme.series(line.group.slot), line.group.label, `$${line.value.toFixed(3)}`))
        return (
          `<div style="opacity:.75">${shortDate(days[column])}</div>` +
          `<div style="font-weight:600">$${total.toFixed(3)}</div>` +
          lines.join('')
        )
      },
    },
    xAxis: {
      type: 'category',
      data: days,
      ...axisStyle(theme),
      splitLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: shortDate },
    },
    yAxis: {
      type: 'value',
      ...axisStyle(theme),
      axisLine: { show: false },
      axisLabel: { ...axisStyle(theme).axisLabel, formatter: (value: number) => `$${value}` },
    },
    series: shown.map((group, index) => ({
      name: group.label,
      type: 'bar',
      stack: 'total',
      barMaxWidth: BAR_MAX_WIDTH,
      itemStyle: { color: theme.series(group.slot), borderColor: theme.surface, borderWidth: gapWidth },
      emphasis: { focus: 'none' },
      data: values[index].map((value, column) => ({
        value: Number(value.toFixed(4)),
        itemStyle: topSeries[column] === index ? { borderRadius: [4, 4, 0, 0] } : undefined,
      })),
    })),
  }
}
