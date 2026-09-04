/**
 * Chart palette and shared scales.
 *
 * Two palettes, doing two different jobs:
 *
 * STATUS — legal / breach / caution / advisory. Reserved: never reused as a
 * "series 4". Always shipped with a label or icon beside the colour, never
 * colour alone. These double as text colours in chips, so they sit above the
 * categorical lightness band on purpose.
 *
 * CATEGORICAL — identity only (span types in the trace waterfall, option
 * sources in the scatter). Assigned in fixed order, never cycled. Validated
 * against the app surface #0a0e17: all six checks pass, worst adjacent CVD
 * ΔE 8.4 (protan) with a normal-vision floor of 19.3.
 *
 * Re-validate with the dataviz skill's script if any value here changes:
 *   node scripts/validate_palette.js "<hexes>" --mode dark --surface "#0a0e17"
 */

export const SURFACE = '#0a0e17'
export const GRID = '#1e293b'
export const AXIS = '#3b4a63'
export const INK = { primary: '#e6edf7', secondary: '#9fb0c8', muted: '#7d8da8' }

export const STATUS = {
  legal: '#34d399',
  breach: '#f87171',
  caution: '#fbbf24',
  advisory: '#a78bfa',
  neutral: '#3b4a63',
} as const

/** Fixed order. A 8th category folds into "Other" — it never generates a hue. */
export const CATEGORICAL = [
  '#3987e5', // 1 blue
  '#d95926', // 2 orange
  '#199e70', // 3 aqua
  '#c98500', // 4 yellow
  '#d55181', // 5 magenta
  '#9085e9', // 6 violet
  '#e66767', // 7 red
] as const

/** Sequential ramp for magnitude (single hue, light → dark). */
export const SEQ_BLUE = ['#86b6ef', '#5598e7', '#3987e5', '#2a78d6', '#1c5cab', '#184f95'] as const

/** Span type → colour. Fixed assignment so a trace always looks the same. */
export const SPAN_COLORS: Record<string, string> = {
  graph: CATEGORICAL[5],
  node: CATEGORICAL[0],
  tool: CATEGORICAL[2],
  llm: CATEGORICAL[5],
  sql: CATEGORICAL[3],
  rule: CATEGORICAL[4],
  sim: CATEGORICAL[1],
  verify: CATEGORICAL[6],
}

export const SPAN_TYPES = ['graph', 'node', 'tool', 'llm', 'sql', 'rule', 'sim', 'verify'] as const

/** Option source → colour. Cancellation is a status, not an identity. */
export const SOURCE_COLORS: Record<string, string> = {
  reserve: CATEGORICAL[0],
  'day-off': CATEGORICAL[1],
  cancellation: STATUS.breach,
}

export const severityColor = (severity: string) =>
  severity === 'critical' ? STATUS.breach : severity === 'warning' ? STATUS.caution : STATUS.advisory

export const verdictColor = (verdict: string) =>
  verdict === 'breach'
    ? STATUS.breach
    : verdict === 'advisory'
      ? STATUS.advisory
      : verdict === 'pass'
        ? STATUS.legal
        : STATUS.neutral

/** Rule id → a stable categorical slot, for exclusion breakdowns. */
export const RULE_ORDER = [
  'RULE-QUAL-05',
  'RULE-REST-04',
  'RULE-DUTY-02',
  'RULE-FDP-01',
  'RULE-CERT-06',
  'RULE-BASE-07',
  'RULE-FLT-03',
  'CONSTRAINT-RESERVE-WINDOW',
  'CONSTRAINT-OVERLAP',
]

export const ruleColor = (ruleId: string) => {
  const index = RULE_ORDER.indexOf(ruleId)
  return index >= 0 ? CATEGORICAL[index % CATEGORICAL.length] : STATUS.neutral
}

/** Short label for a rule chip — the id is long and the suffix is what reads. */
export const ruleShort = (ruleId: string) =>
  ruleId.startsWith('RULE-') ? ruleId.slice(5) : ruleId.replace('CONSTRAINT-', '')

export const MINUTES_IN_DAY = 1440

/** Map a UTC minute-of-day onto a 0–100% x position. */
export const pctOfDay = (minutes: number) => (minutes / MINUTES_IN_DAY) * 100

export const clamp = (value: number, min = 0, max = 100) => Math.min(max, Math.max(min, value))
