import clsx from 'clsx'
import { useMemo, useState } from 'react'
import { hm, inr, minutesOfDay, utcTime } from '../lib/api'
import type { CoverOption, RuleVerdict } from '../lib/api'
import { CATEGORICAL, INK, SOURCE_COLORS, STATUS, clamp, pctOfDay, ruleColor, ruleShort } from '../lib/viz'
import { Legend, Tip } from './ui'

/* ==========================================================================
   1. Duty budget bar
   The single most important image in the product. It answers "how much of the
   60-hour ceiling does this assignment eat, and by how much does it bust it?"
   in one glance, which is exactly the question RULE-DUTY-02 poses.
   ========================================================================== */

export function DutyBudgetBar({
  used,
  added,
  limit,
  label,
  unit = 'h',
  compact = false,
}: {
  used: number
  added?: number
  limit: number
  label?: string
  unit?: string
  compact?: boolean
}) {
  const addition = added ?? 0
  const total = Math.round((used + addition) * 100) / 100
  const overflow = Math.max(0, Math.round((total - limit) * 100) / 100)
  const scale = Math.max(limit, total) * 1.04

  const pct = (v: number) => (v / scale) * 100
  const usedPct = pct(Math.min(used, limit))
  const addedWithin = Math.max(0, Math.min(addition, limit - used))
  const addedPct = pct(addedWithin)
  const overflowPct = pct(overflow)

  return (
    <figure className="w-full">
      {label && (
        <figcaption className="flex items-baseline justify-between mb-1.5">
          <span className="label">{label}</span>
          <span className="num text-2xs text-mute-300">
            {total}
            {unit} of {limit}
            {unit}
            {overflow > 0 && <span className="text-breach font-semibold ml-1.5">+{hm(overflow)} over</span>}
            {overflow === 0 && (
              <span className="text-legal ml-1.5">{Math.round((limit - total) * 100) / 100}{unit} left</span>
            )}
          </span>
        </figcaption>
      )}

      <div className={clsx('relative w-full rounded-md bg-ink-800', compact ? 'h-2.5' : 'h-4')}>
        {/* Existing duty */}
        <div
          className="absolute inset-y-0 left-0 rounded-l-md"
          style={{ width: `${usedPct}%`, background: CATEGORICAL[0] }}
        />
        {/* Proposed addition — a 2px surface gap separates it from the fill before it */}
        {addedWithin > 0 && (
          <div
            className="absolute inset-y-0"
            style={{
              left: `calc(${usedPct}% + 2px)`,
              width: `calc(${addedPct}% - 2px)`,
              background: STATUS.caution,
            }}
          />
        )}
        {/* Overflow past the limit */}
        {overflow > 0 && (
          <div
            className="absolute inset-y-0 rounded-r-md"
            style={{
              left: `calc(${pct(limit)}% + 2px)`,
              width: `calc(${overflowPct}% - 2px)`,
              background: STATUS.breach,
            }}
          />
        )}
        {/* The limit itself */}
        <div
          className="absolute inset-y-[-3px] w-[2px] bg-mute-200"
          style={{ left: `${pct(limit)}%` }}
          aria-hidden
        />
      </div>

      <div className="flex items-center justify-between mt-1">
        <Legend
          items={[
            { color: CATEGORICAL[0], label: `Existing ${used}${unit}` },
            ...(addition ? [{ color: STATUS.caution, label: `Proposed +${addition}${unit}` }] : []),
            ...(overflow ? [{ color: STATUS.breach, label: `Over by ${hm(overflow)}` }] : []),
          ]}
        />
        <span className="num text-2xs text-mute-400">
          limit {limit}
          {unit}
        </span>
      </div>
    </figure>
  )
}

/* ==========================================================================
   2. Reserve on-call ribbon
   A 24-hour strip per reserve, with the required report time marked. This is
   the picture that explains why C-3305 (00:00–05:30Z) cannot take a 06:00Z
   report while C-3310 (06:00–18:00Z) can — a distinction that is invisible in
   a table of names.
   ========================================================================== */

export function ReserveRibbon({
  reserves,
  reportUtc,
  onSelect,
}: {
  reserves: {
    crew_id: string
    rank: string
    window: { start: string; end: string }
    ratings?: string[]
    covers_report_time?: boolean | null
    reachability_minutes?: number
  }[]
  reportUtc?: string
  onSelect?: (crewId: string) => void
}) {
  const reportPct = reportUtc ? pctOfDay(minutesOfDay(reportUtc)) : null
  const toPct = (hhmm: string) => {
    const [h, m] = hhmm.split(':').map(Number)
    return pctOfDay(h * 60 + m)
  }

  return (
    <figure className="space-y-1.5">
      <div className="flex items-center justify-between">
        <Legend
          items={[
            { color: CATEGORICAL[0], label: 'On-call window' },
            ...(reportUtc
              ? [
                  { color: STATUS.legal, label: 'Covers required report' },
                  { color: STATUS.breach, label: 'Outside window' },
                ]
              : []),
          ]}
        />
        {reportUtc && (
          <span className="num text-2xs text-mute-300">required report {utcTime(reportUtc)}</span>
        )}
      </div>

      {/* Hour axis */}
      <div className="relative h-3.5 ml-[104px]" aria-hidden>
        {[0, 6, 12, 18, 24].map((h) => (
          <span
            key={h}
            className="absolute num text-2xs text-mute-400 -translate-x-1/2"
            style={{ left: `${(h / 24) * 100}%` }}
          >
            {String(h % 24).padStart(2, '0')}
          </span>
        ))}
      </div>

      <ul className="space-y-1">
        {reserves.map((r) => {
          const start = toPct(r.window.start)
          const end = toPct(r.window.end === '00:00' ? '24:00' : r.window.end)
          const covers = r.covers_report_time
          const color = covers === true ? STATUS.legal : covers === false ? STATUS.breach : CATEGORICAL[0]
          return (
            <li key={r.crew_id} className="flex items-center gap-2">
              <button
                onClick={() => onSelect?.(r.crew_id)}
                className="w-[96px] shrink-0 text-left num text-2xs text-mute-300 hover:text-signal truncate"
                title={`${r.rank}${r.ratings?.length ? ` · ${r.ratings.join(', ')}` : ''}`}
              >
                {r.crew_id}
              </button>
              <div className="relative flex-1 h-3.5 rounded bg-ink-800">
                {[6, 12, 18].map((h) => (
                  <div
                    key={h}
                    className="absolute inset-y-0 w-px bg-ink-700"
                    style={{ left: `${(h / 24) * 100}%` }}
                    aria-hidden
                  />
                ))}
                <Tip
                  className="absolute inset-y-0"
                  style={{ left: `${clamp(start)}%`, width: `${clamp(end - start)}%` }}
                  text={`${r.crew_id} on call ${r.window.start}–${r.window.end}Z${
                    covers === true ? ' · covers the report' : covers === false ? ' · does not cover the report' : ''
                  }`}
                >
                  <div className="w-full h-full rounded-sm" style={{ background: color }} />
                </Tip>
                {reportPct !== null && (
                  <div
                    className="absolute inset-y-[-2px] w-[2px] bg-mute-200"
                    style={{ left: `${clamp(reportPct)}%` }}
                    aria-hidden
                  />
                )}
              </div>
              <span className="w-[74px] shrink-0 num text-2xs text-mute-400 text-right">
                {r.window.start}–{r.window.end}
              </span>
            </li>
          )
        })}
      </ul>
    </figure>
  )
}

/* ==========================================================================
   3. Exclusion breakdown
   The rejections are the product. This shows, at a glance, that the search was
   exhaustive and which rule did the most work.
   ========================================================================== */

export function ExclusionBreakdown({
  summary,
  evaluated,
  eligible,
  onSelectRule,
  activeRule,
}: {
  summary: Record<string, number>
  evaluated: number
  eligible: number
  onSelectRule?: (rule: string | null) => void
  activeRule?: string | null
}) {
  const rows = Object.entries(summary).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...rows.map(([, n]) => n))

  return (
    <figure className="space-y-2">
      <figcaption className="text-xs text-mute-300">
        <span className="num font-semibold text-mute-200">{evaluated}</span> candidates evaluated ·{' '}
        <span className="num font-semibold text-legal">{eligible}</span> legal ·{' '}
        <span className="num font-semibold text-breach">{evaluated - eligible}</span> excluded
      </figcaption>
      <ul className="space-y-1">
        {rows.map(([rule, count]) => {
          const active = activeRule === rule
          return (
            <li key={rule}>
              <button
                onClick={() => onSelectRule?.(active ? null : rule)}
                className={clsx(
                  'w-full flex items-center gap-2 px-1.5 py-1 rounded-md transition-colors text-left',
                  active ? 'bg-ink-750' : 'hover:bg-ink-850',
                )}
              >
                <span className="w-[92px] shrink-0 num text-2xs text-mute-300">{ruleShort(rule)}</span>
                <span className="flex-1 h-2.5 rounded bg-ink-800 relative">
                  <span
                    className="absolute inset-y-0 left-0 rounded"
                    style={{ width: `${(count / max) * 100}%`, background: ruleColor(rule) }}
                  />
                </span>
                <span className="w-6 shrink-0 num text-2xs text-mute-200 text-right">{count}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </figure>
  )
}

/* ==========================================================================
   4. Candidate scatter — cost against delay
   Makes the trade-off spatial: cheap-and-immediate sits bottom-left.
   ========================================================================== */

export function CandidateScatter({
  options,
  onSelect,
  selected,
}: {
  options: CoverOption[]
  onSelect?: (crewId: string | null) => void
  selected?: string | null
}) {
  const points = options.filter((o) => o.source !== 'cancellation')
  if (points.length === 0) return null

  // Options routinely share a cost tier (every day-off pilot callout is the
  // same rate), so marks land exactly on top of each other. Jittering would
  // misrepresent the values; instead one mark carries the group and its count.
  const groups = useMemo(() => {
    const map = new Map<string, CoverOption[]>()
    for (const o of points) {
      const key = `${o.cost_inr}|${o.delay_hours}`
      map.set(key, [...(map.get(key) ?? []), o])
    }
    return [...map.values()]
  }, [points])

  const maxCost = Math.max(...points.map((o) => o.cost_inr)) * 1.12
  const maxDelay = Math.max(1, ...points.map((o) => o.delay_hours)) * 1.25
  const W = 100
  const H = 100

  return (
    <figure>
      <div className="relative h-44 rounded-lg bg-ink-850 border border-ink-700/60">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
          {[25, 50, 75].map((g) => (
            <g key={g}>
              <line x1={g} y1={0} x2={g} y2={H} stroke="#1e293b" strokeWidth={0.4} />
              <line x1={0} y1={g} x2={W} y2={g} stroke="#1e293b" strokeWidth={0.4} />
            </g>
          ))}
        </svg>
        {groups.map((group) => {
          const o = group[0]
          const x = (o.cost_inr / maxCost) * 100
          const y = 100 - (o.delay_hours / maxDelay) * 100
          const active = group.some((g) => g.crew_id === selected)
          const size = Math.max(10, 17 - (o.reachability_minutes ?? 60) / 12)
          const names = group.map((g) => g.crew_id).join(', ')
          return (
            <Tip
              key={`${o.cost_inr}-${o.delay_hours}`}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${clamp(x, 4, 96)}%`, top: `${clamp(y, 8, 92)}%` }}
              text={`${names} · ${inr(o.cost_inr)} · ${o.delay_hours}h delay${
                group.length === 1 ? ` · reachable in ${o.reachability_minutes ?? '?'} min` : ''
              }`}
            >
              <button
                onClick={() => onSelect?.(active ? null : o.crew_id)}
                className="rounded-full transition-transform hover:scale-125 flex items-center justify-center num text-[9px] font-bold text-ink-950"
                style={{
                  width: size,
                  height: size,
                  background: SOURCE_COLORS[o.source ?? 'day-off'] ?? CATEGORICAL[0],
                  // 2px surface ring keeps overlapping marks readable
                  boxShadow: active ? `0 0 0 2px ${STATUS.legal}` : `0 0 0 2px ${'#0a0e17'}`,
                }}
                aria-label={`${names}, ${inr(o.cost_inr)}, ${o.delay_hours} hour delay`}
              >
                {group.length > 1 ? group.length : ''}
              </button>
            </Tip>
          )
        })}
        {/* Direct-label the cheapest option only */}
        {points[0]?.crew_id && (
          <span
            className="absolute num text-2xs text-mute-300 pointer-events-none"
            style={{
              left: `${clamp((points[0].cost_inr / maxCost) * 100, 4, 78)}%`,
              top: `${clamp(100 - (points[0].delay_hours / maxDelay) * 100, 8, 92)}%`,
              transform: 'translate(12px, -50%)',
            }}
          >
            {points[0].crew_id}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <Legend
          items={[
            { color: SOURCE_COLORS.reserve, label: 'Reserve callout' },
            { color: SOURCE_COLORS['day-off'], label: 'Day-off callout' },
          ]}
        />
        <span className="text-2xs text-mute-400">x: cost → · y: delay ↑ · size: reachability</span>
      </div>
    </figure>
  )
}

/* ==========================================================================
   5. Rule proof card — the arithmetic, laid out as a receipt
   ========================================================================== */

export function RuleProof({ verdict }: { verdict: RuleVerdict }) {
  const breach = verdict.verdict === 'breach'
  const advisory = verdict.verdict === 'advisory'
  return (
    <div
      className={clsx(
        'rounded-lg border p-2.5',
        breach ? 'border-breach/30 bg-breach/5' : advisory ? 'border-advisory/30 bg-advisory/5' : 'border-ink-700 bg-ink-850',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className={breach ? 'chip-breach' : advisory ? 'chip-advisory' : 'chip-legal'}>
          {verdict.rule_id}
        </span>
        {verdict.date && <span className="num text-2xs text-mute-400">{verdict.date}</span>}
      </div>
      <p className={clsx('text-xs mt-1.5 leading-snug', breach ? 'text-breach' : 'text-mute-300')}>
        {verdict.message}
      </p>

      {verdict.arithmetic.length > 0 && (
        <dl className="mt-2 space-y-0.5 border-t border-ink-700/70 pt-2">
          {verdict.arithmetic.map((step, i) => (
            <div key={i} className="flex items-baseline justify-between gap-3">
              <dt className="text-2xs text-mute-400 truncate">{step.label}</dt>
              <dd className="num text-2xs text-mute-200 shrink-0">
                {step.value}
                {step.unit}
              </dd>
              <dd className="text-2xs text-mute-400/70 font-mono truncate max-w-[52%] text-right">
                {step.expression}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {verdict.actual !== null && verdict.limit !== null && verdict.limit > 0 && (
        <div className="mt-2">
          <DutyBudgetBar used={verdict.actual} limit={verdict.limit} compact />
        </div>
      )}
    </div>
  )
}

/* ==========================================================================
   6. 28-day duty / block chart with the limit line
   ========================================================================== */

export function DutyHistoryChart({
  days,
  limit,
  windowDays = 7,
  unit = 'h',
  title,
}: {
  days: { date: string; history_hours: number; rostered_hours: number; total_hours: number; pairing_id?: string | null }[]
  limit: number
  windowDays?: number
  unit?: string
  title?: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const max = Math.max(1, ...days.map((d) => d.total_hours))
  const rollingTotal = useMemo(() => {
    const tail = days.slice(-windowDays)
    return Math.round(tail.reduce((s, d) => s + d.total_hours, 0) * 100) / 100
  }, [days, windowDays])

  return (
    <figure>
      {title && (
        <figcaption className="flex items-baseline justify-between mb-2">
          <span className="label">{title}</span>
          <span className="num text-2xs text-mute-300">
            last {windowDays}d: {rollingTotal}
            {unit} of {limit}
            {unit}
          </span>
        </figcaption>
      )}
      <div className="relative h-28 flex items-end gap-[2px]">
        {days.map((d, i) => {
          const inWindow = i >= days.length - windowDays
          const h = (d.total_hours / max) * 100
          const rosteredShare = d.total_hours ? (d.rostered_hours / d.total_hours) * 100 : 0
          return (
            <Tip
              key={d.date}
              className="relative flex-1 min-w-[3px]"
              text={`${d.date} · ${d.total_hours}${unit}${d.pairing_id ? ` · ${d.pairing_id}` : ''}`}
            >
              <button
                className="relative w-full h-28 flex items-end"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                aria-label={`${d.date}: ${d.total_hours} hours`}
              >
                <span
                  className={clsx('w-full rounded-t-[3px] transition-opacity', !inWindow && 'opacity-45')}
                  style={{
                    height: `${Math.max(h, d.total_hours > 0 ? 3 : 0)}%`,
                    background: CATEGORICAL[0],
                    outline: hover === i ? `1px solid ${INK.secondary}` : undefined,
                  }}
                >
                  {rosteredShare > 0 && (
                    <span
                      className="block w-full rounded-t-[3px]"
                      style={{ height: `${rosteredShare}%`, background: STATUS.caution }}
                    />
                  )}
                </span>
              </button>
            </Tip>
          )
        })}
        {/* Rolling-window shading */}
        <div
          className="absolute inset-y-0 right-0 border-l border-dashed border-mute-400/40 bg-signal/5 pointer-events-none"
          style={{ width: `${(windowDays / days.length) * 100}%` }}
          aria-hidden
        />
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <Legend
          items={[
            { color: CATEGORICAL[0], label: 'Recorded history' },
            { color: STATUS.caution, label: 'Published roster' },
          ]}
        />
        <span className="num text-2xs text-mute-400">
          {days[0]?.date} → {days[days.length - 1]?.date}
        </span>
      </div>
    </figure>
  )
}

/* ==========================================================================
   7. Coverage ring — one ambient number
   ========================================================================== */

export function CoverageRing({
  value,
  label,
  sublabel,
  tone = STATUS.legal,
}: {
  value: number
  label: string
  sublabel?: string
  tone?: string
}) {
  const r = 34
  const circumference = 2 * Math.PI * r
  const dash = (clamp(value) / 100) * circumference
  return (
    <figure className="flex items-center gap-3">
      <svg width={82} height={82} viewBox="0 0 82 82" role="img" aria-label={`${label}: ${value}%`}>
        <circle cx={41} cy={41} r={r} fill="none" stroke="#1e293b" strokeWidth={7} />
        <circle
          cx={41}
          cy={41}
          r={r}
          fill="none"
          stroke={tone}
          strokeWidth={7}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform="rotate(-90 41 41)"
        />
        <text
          x={41}
          y={45}
          textAnchor="middle"
          className="num"
          fontSize={17}
          fontWeight={600}
          fill={INK.primary}
        >
          {Math.round(value)}%
        </text>
      </svg>
      <div>
        <div className="text-xs font-medium text-mute-200">{label}</div>
        {sublabel && <div className="text-2xs text-mute-400 mt-0.5 leading-snug">{sublabel}</div>}
      </div>
    </figure>
  )
}
