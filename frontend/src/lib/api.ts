/**
 * Backend client.
 *
 * `chat` goes through the agent and requires an LLM API key. Everything else
 * hits the rules engine directly — the console uses those lookups rather than
 * asking a question.
 */

const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: unknown,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    let body: unknown
    try {
      body = await res.json()
    } catch {
      body = await res.text().catch(() => undefined)
    }
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText
    throw new ApiError(detail, res.status, body)
  }
  return res.json() as Promise<T>
}

const get = <T,>(path: string) => request<T>(path)
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') search.set(k, String(v))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

// ---------------------------------------------------------------- types

export interface Verification {
  passed: boolean
  checks: { name: string; passed: boolean; detail?: string; checked?: number }[]
  violations: { check: string; value: string; reason: string }[]
  repair_attempts: number
  downgraded: boolean
  summary: string
}

export interface ChatAnswer {
  run_id: string
  conversation_id?: string
  question: string
  answer: string
  structured: StructuredAnswer | null
  intent: { name: string; tier: number; confidence: number; source: string; rationale: string } | null
  entities: Record<string, unknown>
  tier: number | null
  citations: string[]
  verification: Verification | null
  abstained: boolean
  plan: { tool: string; args: Record<string, unknown> }[]
  plan_source: string
  tool_calls: { tool: string; args: Record<string, unknown>; ok: boolean; duration_ms: number }[]
  latency_ms: number | null
  trace_summary: Record<string, unknown>
}

export interface StructuredAnswer {
  schema: string
  intent?: string
  headline: string
  tier?: number
  primary?: any
  options?: CoverOption[]
  excluded_candidates?: ExcludedCandidate[]
  exclusion_summary?: Record<string, number>
  evaluated_count?: number
  excluded_count?: number
  legal_option_count?: number
  impact?: ImpactPayload
  detail?: any
  citations?: string[]
  as_of?: string
  tools_used?: string[]
  [key: string]: any
}

export interface RuleVerdict {
  rule_id: string
  verdict: 'pass' | 'breach' | 'advisory' | 'not_applicable'
  message: string
  crew_id: string | null
  date: string | null
  actual: number | null
  limit: number | null
  margin: number | null
  arithmetic: { label: string; expression: string; value: number | string; unit: string }[]
}

export interface CostLine {
  label: string
  amount: number
  basis: string
}

export interface ScheduleDay {
  date: string
  status: 'rostered' | 'cover' | 'conflict' | 'off'
  pairing_id: string | null
  duty_hours: number | null
  flight_hours: number | null
  report_utc: string | null
  release_utc: string | null
  conflicts: { rule: string; message: string }[]
}

export interface ScheduleWindow {
  crew_id: string
  window_start: string
  window_end: string
  cover_pairing_id: string | null
  conflict_count: number
  safe_to_assign: boolean
  days: ScheduleDay[]
}

export interface CoverOption {
  rank: number
  action: string
  crew_id: string | null
  legal: boolean
  rules_checked: string[]
  cost_inr: number
  delay_hours: number
  crew_name?: string
  crew_rank?: string
  base?: string
  ratings?: string[]
  seniority?: number
  reachability_minutes?: number
  source?: 'reserve' | 'day-off' | 'cancellation'
  cost_breakdown?: { currency: string; total: number; lines: CostLine[] }
  positioning?: {
    from_station: string
    to_station: string
    flight_no: string
    arrival_utc: string
    new_report_utc: string
    delay_hours: number
  } | null
  ops_rank?: number
  ops_score?: number
  ops_factors?: Record<string, unknown>
  verdicts?: RuleVerdict[]
  seats_at_risk?: number
  flight_ids?: string[]
  schedule_window?: ScheduleWindow
}

export interface ExcludedCandidate {
  crew_id: string
  reason: string
  rule_ids: string[]
  verdicts?: RuleVerdict[]
}

export interface ImpactPayload {
  crew_id: string
  crew_name: string
  role: string
  pairing_id: string
  reported_utc: string
  uncovered_flights_day1: string[]
  uncovered_flights_day2: string[]
  passengers_at_risk_day1: number
  passengers_at_risk_total: number
  days: {
    day_index: number
    date: string
    report_utc: string
    release_utc: string
    sectors: number
    flight_ids: string[]
    seats: number
  }[]
  flights_detail: {
    flight_id: string
    flight_no: string
    date: string
    dep_station: string
    arr_station: string
    dep_utc: string
    seats: number
    reason: string
  }[]
  other_crew_on_pairing: { crew_id: string; role: string; name: string }[]
}

export interface CandidateSetPayload {
  role: string
  pairing_id: string
  cover_dates: string[]
  evaluated_count: number
  eligible_count: number
  excluded_count: number
  exclusion_summary: Record<string, number>
  options: CoverOption[]
  excluded_candidates: ExcludedCandidate[]
  run_id?: string
}

export interface Alert {
  id: string
  type: string
  severity: 'critical' | 'warning' | 'info'
  title: string
  detail: string
  entity_ref: string | null
  payload: Record<string, any>
  suggested_question: string | null
  state: string
  detected_at: string
}

export interface Snapshot {
  snapshot_utc: string
  clock: { now_utc: string; date: string; snapshot_utc: string; offset_hours: number }
  schedule: { start: string; end: string }
  counts: Record<string, number>
  stations: string[]
  aircraft: string[]
  currency: string
  flagged_exceptions: Record<string, unknown>[]
}

export interface GanttRow {
  aircraft: string
  aircraft_type: string
  pairings: {
    pairing_id: string
    date: string
    day_index: number
    report_utc: string
    release_utc: string
    sectors: number
    seats: number
    crew: { crew_id: string; role: string }[]
    legs: { flight_id: string; flight_no: string; route: string; dep_utc: string; arr_utc: string }[]
  }[]
}

export interface EvalReport {
  suite: string
  total: number
  passed: number
  failed: number
  pass_rate: number
  by_tier?: Record<string, { total: number; passed: number; pass_rate: number }>
  suites?: Record<string, EvalReport>
  duration_ms?: number
  description?: string
  cases: EvalCase[]
  // present on suite="live" only
  available?: boolean
  provider?: string
  model?: string
  wall_ms?: number
  concurrency?: number
  latency_ms?: { avg: number; max: number; min: number }
}

export interface EvalCase {
  case_id: string
  tier: number | null
  title: string
  passed: boolean
  error: string | null
  checks: { name: string; passed: boolean; expected: unknown; actual: unknown; detail: string }[]
  failed_checks: { name: string; expected: unknown; actual: unknown; detail: string }[]
  meta?: { latency_ms?: number; intent?: string | null; intent_source?: string; plan_source?: string }
}

export interface RunSummary {
  run_id: string
  question: string
  intent: string | null
  tier: number | null
  status: string
  latency_ms: number | null
  abstained: boolean
  verified: boolean | null
  span_count: number
  tool_call_count: number
  fact_count: number
  started_at: string | null
  plan_source?: string | null
}

export interface Span {
  span_id: string
  parent_span_id: string | null
  name: string
  type: string
  started_at: string
  duration_ms: number | null
  status: string
  error: string | null
  input: any
  output: any
  attrs: Record<string, any>
  depth?: number
  offset_ms?: number
}

export interface RunDetail extends RunSummary {
  spans: Span[]
  waterfall?: Span[]
  facts: { fact_id: string; key: string; value: string; source_tool: string | null; source_span_id: string | null }[]
  rule_evaluations: RuleVerdict[]
  source?: string
}

// ---------------------------------------------------------------- api

export const api = {
  // meta
  health: () => get<any>('/api/health'),
  snapshot: () => get<Snapshot>('/api/snapshot'),
  capabilities: () => get<any>('/api/agent/capabilities'),
  clock: () => get<Snapshot['clock']>('/api/clock'),
  setClock: (body: { now_utc?: string; advance_hours?: number; advance_days?: number; reset?: boolean }) =>
    post<any>('/api/clock', body),

  // chat
  chat: (question: string, conversationId?: string) =>
    post<ChatAnswer>('/api/chat', { question, conversation_id: conversationId }),

  conversations: (limit = 25) =>
    get<{ count: number; conversations: { id: string; title: string; created_at: string; message_count: number }[] }>(
      `/api/conversations${qs({ limit })}`
    ),
  conversation: (id: string) =>
    get<{
      id: string
      title: string
      messages: { role: string; content: string; structured: any; run_id: string; created_at: string }[]
    }>(`/api/conversations/${id}`),

  // world
  gantt: (start?: string) => get<{ dates: string[]; rows: GanttRow[] }>(`/api/gantt${qs({ start })}`),
  crew: (params: { rank?: string; base?: string; rating?: string; status?: string } = {}) =>
    get<any>(`/api/crew${qs(params)}`),
  crewDetail: (id: string) => get<any>(`/api/crew/${id}`),
  crewTimeline: (id: string, asOf?: string) => get<any>(`/api/crew/${id}/timeline${qs({ as_of: asOf })}`),
  pairing: (id: string) => get<any>(`/api/pairings/${id}`),
  pairings: (params: { on?: string; aircraft?: string; crew_id?: string } = {}) =>
    get<any>(`/api/pairings${qs(params)}`),
  flights: (params: Record<string, string | undefined> = {}) => get<any>(`/api/flights${qs(params)}`),
  flight: (id: string) => get<any>(`/api/flights/${encodeURIComponent(id)}`),
  reserves: (params: { on?: string; base?: string; rank?: string; report_utc?: string } = {}) =>
    get<any>(`/api/reserves${qs(params)}`),
  certsExpiring: (withinDays = 30, asOf?: string) =>
    get<any>(`/api/certifications/expiring${qs({ within_days: withinDays, as_of: asOf })}`),
  dutyScan: (params: { as_of?: string; threshold_hours?: number } = {}) => get<any>(`/api/duty-scan${qs(params)}`),
  rules: () => get<{ count: number; rules: { rule_id: string; text: string; params: any }[] }>('/api/rules'),
  costs: () => get<any>('/api/costs'),
  risk: (top = 10) => get<any>(`/api/risk${qs({ top })}`),
  briefing: (on?: string) => get<any>(`/api/briefing${qs({ on })}`),
  networkSummary: (on?: string, fromStation?: string) =>
    get<any>(`/api/network/summary${qs({ on, from_station: fromStation })}`),

  // simulate + recommend
  scenarios: (includeHoldout = false) => get<any>(`/api/scenarios${qs({ include_holdout: includeHoldout })}`),
  replayScenario: (id: string) => post<any>(`/api/scenarios/${id}/replay`),
  simulateSick: (body: { crew_id: string; pairing_id?: string; reported_utc?: string }) =>
    post<any>('/api/simulate/sick', body),
  simulateClosure: (body: { station: string; start_utc: string; end_utc: string }) =>
    post<any>('/api/simulate/station-closure', body),
  simulateDelay: (body: { aircraft: string; date: string; delay_hours: number }) =>
    post<any>('/api/simulate/delay', body),
  simulateCert: (body: { crew_id: string; pairing_id: string; reported_utc?: string }) =>
    post<any>('/api/simulate/cert-lapse', body),
  simulateCancellation: (body: { flight_ids: string[] }) => post<any>('/api/simulate/cancellation', body),
  simulateMultiSick: (body: { events: { crew_id: string; pairing_id: string; reported_utc?: string }[] }) =>
    post<any>('/api/simulate/multi-sick', body),
  simulateChain: (events: Record<string, unknown>[]) => post<any>('/api/simulate/chain', { events }),
  recommendCover: (body: { pairing_id: string; role?: string; sick_crew_id?: string }) =>
    post<CandidateSetPayload>('/api/recommend/cover', body),
  legalityCheck: (body: { crew_id: string; pairing_id: string; delay_hours?: number }) =>
    post<any>('/api/legality/check', body),

  // actions
  createDecision: (body: Record<string, unknown>) => post<any>('/api/decisions', body),
  decisions: () => get<any>('/api/decisions'),
  draftNotification: (body: { crew_id: string; pairing_id: string; cost_inr?: number }) =>
    post<any>('/api/notifications/draft', body),

  // alerts
  alerts: (state = 'open') => get<{ count: number; open_by_severity: Record<string, number>; alerts: Alert[] }>(
    `/api/alerts${qs({ state, limit: 200 })}`,
  ),
  sweepAlerts: () => post<any>('/api/alerts/sweep'),
  ackAlert: (id: string) => post<any>(`/api/alerts/${encodeURIComponent(id)}/ack`),
  resolveAlert: (id: string) => post<any>(`/api/alerts/${encodeURIComponent(id)}/resolve`),

  // observability
  runs: (limit = 50) => get<{ count: number; runs: RunSummary[] }>(`/api/runs${qs({ limit })}`),
  run: (id: string) => get<RunDetail>(`/api/runs/${id}`),
  runRuleEvaluations: (id: string) => get<any>(`/api/runs/${id}/rule-evaluations`),
  replayRun: (id: string) => post<any>(`/api/runs/${id}/replay`),
  receiptUrl: (id: string) => `${BASE}/api/runs/${id}/receipt`,
  metrics: (hours = 24) => get<any>(`/api/metrics${qs({ hours })}`),

  // eval
  evalRun: (suite = 'all', opts: { concurrency?: number; limit?: number } = {}) =>
    post<EvalReport>(`/api/eval/run${qs({ suite, ...opts })}`),
  evalLatest: (suite = 'all') => get<EvalReport>(`/api/eval/latest${qs({ suite })}`),
  evalQuestions: () => get<{ questions: { question_id: string; tier: number; prompt: string }[] }>(
    '/api/eval/questions',
  ),
}

// ---------------------------------------------------------------- formatting

export const inr = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : `₹${n.toLocaleString('en-IN')}`

export const hoursLabel = (h: number | null | undefined) =>
  h === null || h === undefined ? '—' : `${h}h`

/** 1.33 → "1h20m". Mirrors the engine's breach formatting. */
export const hm = (hours: number) => {
  const sign = hours < 0 ? '-' : ''
  const abs = Math.abs(hours)
  const whole = Math.floor(abs)
  const mins = Math.round((abs - whole) * 60)
  return `${sign}${whole}h${String(mins).padStart(2, '0')}m`
}

export const utcTime = (iso: string | null | undefined) => (iso ? `${iso.slice(11, 16)}Z` : '—')
export const utcDate = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : '—')
export const utcStamp = (iso: string | null | undefined) =>
  iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)}Z` : '—'

/** Minutes since UTC midnight — the x-axis unit for every timeline. */
export const minutesOfDay = (iso: string) => {
  const h = Number(iso.slice(11, 13))
  const m = Number(iso.slice(14, 16))
  return h * 60 + m
}
