import clsx from 'clsx'
import { Download, FileSearch, Info, Lightbulb } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ChatAnswer, StructuredAnswer } from '../lib/api'
import { api, inr, utcStamp, utcTime } from '../lib/api'
import { STATUS } from '../lib/viz'
import { ImpactCascade } from './Gantt'
import { OptionsTable, ExcludedTable } from './Options'
import { LegalityBadge, Legend, Panel, RuleChip, VerificationBadge } from './ui'
import { DutyBudgetBar, ReserveRibbon } from './viz'
import { RuleProof } from './viz'

/**
 * Renders a structured answer by its schema.
 *
 * The model wrote the prose above this; everything below is the object the
 * engine produced. Keeping them visually distinct is the point — a controller
 * can read the sentence or audit the table, and they are the same answer.
 */
export function AnswerBody({ structured }: { structured: StructuredAnswer }) {
  switch (structured.schema) {
    case 'recommendation':
      return <RecommendationBody a={structured} />
    case 'joint_recommendation':
      return <JointBody a={structured} />
    case 'legality':
      return <LegalityBody a={structured} />
    case 'impact':
      return <ImpactBody a={structured} />
    case 'duty_clock':
      return <DutyClockBody a={structured} />
    case 'reserve_list':
      return <ReserveBody a={structured} />
    case 'closure':
      return <ClosureBody a={structured} />
    case 'delay':
      return <DelayBody a={structured} />
    case 'notification':
      return <NotificationBody a={structured} />
    case 'briefing':
      return <BriefingBody a={structured} />
    case 'abstention':
    case 'clarification':
      return <AbstentionBody a={structured} />
    default:
      return <GenericBody a={structured} />
  }
}

function RecommendationBody({ a }: { a: StructuredAnswer }) {
  return (
    <div className="space-y-4">
      {a.impact?.uncovered_flights_day1?.length ? (
        <ImpactCascade
          crewId={a.impact.crew_id}
          role={a.impact.role}
          pairingId={a.impact.pairing_id}
          day1={a.impact.uncovered_flights_day1}
          day2={a.impact.uncovered_flights_day2}
          seatsDay1={a.impact.passengers_at_risk_day1}
          seatsTotal={a.impact.passengers_at_risk_total}
          flightsDetail={a.impact.flights_detail}
        />
      ) : null}

      <OptionsTable options={a.options ?? []} />

      {a.excluded_candidates?.length ? (
        <details className="group">
          <summary className="cursor-pointer text-xs text-mute-300 hover:text-signal select-none">
            Why the other {a.excluded_count} candidates were rejected
          </summary>
          <div className="mt-3">
            <ExcludedTable
              excluded={a.excluded_candidates}
              summary={a.exclusion_summary ?? {}}
              evaluated={a.evaluated_count ?? 0}
              eligible={a.legal_option_count ?? 0}
            />
          </div>
        </details>
      ) : null}
    </div>
  )
}

function JointBody({ a }: { a: StructuredAnswer }) {
  const plan = a.primary ?? {}
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-2">
        {Object.entries(plan.assignments ?? {}).map(([pairingId, assignment]: [string, any]) => (
          <div key={pairingId} className="panel p-3">
            <div className="flex items-center justify-between">
              <span className="num text-xs text-mute-200">{pairingId}</span>
              <span className="num text-xs font-semibold text-mute-200">{inr(assignment.cost_inr)}</span>
            </div>
            <p className="text-2xs text-mute-400 mt-1">{assignment.action}</p>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-mute-300">Total</span>
        <span className="num font-semibold text-mute-200">{inr(plan.total_cost_inr)}</span>
      </div>
      {plan.tie_count > 1 && (
        <p className="text-2xs text-mute-400 leading-relaxed border-t border-ink-800 pt-2">
          {plan.tie_count} plans tie at this cost. Swapping which opening each candidate covers is
          equally correct — the dataset says so explicitly, so we do not pretend the tie-break is
          meaningful.
        </p>
      )}
      {(a.openings ?? []).map((opening: any) => (
        <details key={opening.pairing_id}>
          <summary className="cursor-pointer text-xs text-mute-300 hover:text-signal">
            {opening.pairing_id}: {opening.eligible_count} legal of {opening.evaluated_count} evaluated
          </summary>
          <div className="mt-2">
            <ExcludedTable
              excluded={opening.excluded_candidates ?? []}
              summary={opening.exclusion_summary ?? {}}
              evaluated={opening.evaluated_count ?? 0}
              eligible={opening.eligible_count ?? 0}
            />
          </div>
        </details>
      ))}
    </div>
  )
}

function LegalityBody({ a }: { a: StructuredAnswer }) {
  const verdicts = (a.primary?.verdicts ?? []).filter((v: any) => v.verdict !== 'not_applicable')
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <LegalityBadge legal={Boolean(a.legal)} size="md" />
        <span className="text-2xs text-mute-400">
          {a.primary?.pairing_id} · {(a.primary?.cover_dates ?? []).join(', ')}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {verdicts.map((v: any, i: number) => (
          <RuleProof key={i} verdict={v} />
        ))}
      </div>
    </div>
  )
}

function ImpactBody({ a }: { a: StructuredAnswer }) {
  const i = a.primary
  if (!i) return null
  return (
    <ImpactCascade
      crewId={i.crew_id}
      role={i.role}
      pairingId={i.pairing_id}
      day1={i.uncovered_flights_day1}
      day2={i.uncovered_flights_day2}
      seatsDay1={i.passengers_at_risk_day1}
      seatsTotal={i.passengers_at_risk_total}
      flightsDetail={i.flights_detail}
    />
  )
}

function DutyClockBody({ a }: { a: StructuredAnswer }) {
  const d = a.primary
  if (!d) return null
  return (
    <div className="space-y-4">
      <DutyBudgetBar
        used={d.duty_hours_7d}
        limit={d.duty_limit_7d}
        label={`RULE-DUTY-02 · 7 days to ${d.as_of}`}
      />
      <DutyBudgetBar
        used={d.flight_hours_28d}
        limit={d.flight_limit_28d}
        label={`RULE-FLT-03 · 28 days to ${d.as_of}`}
      />
      {d.last_rest_ended && (
        <p className="text-2xs text-mute-400">Last rest ended {utcStamp(d.last_rest_ended)}.</p>
      )}
    </div>
  )
}

function ReserveBody({ a }: { a: StructuredAnswer }) {
  const r = a.primary
  if (!r?.reserves) return null
  return <ReserveRibbon reserves={r.reserves} reportUtc={r.covering_report_utc ?? undefined} />
}

function ClosureBody({ a }: { a: StructuredAnswer }) {
  const c = a.primary
  if (!c) return null
  const rows = c.per_flight_assessment ?? []
  return (
    <div className="space-y-3">
      <Legend
        items={[
          { color: STATUS.legal, label: 'Delay absorbed — crew stays legal' },
          { color: STATUS.breach, label: 'Delay busts FDP — re-crew or cancel' },
        ]}
      />
      <div className="xscroll max-h-80 overflow-y-auto">
        <table className="w-full min-w-[560px] border-collapse">
          <thead>
            <tr>
              <th className="th">Flight</th>
              <th className="th w-24">Pairing</th>
              <th className="th w-24 text-right">Min delay</th>
              <th className="th w-32 text-right">FDP after</th>
              <th className="th w-24 text-right">Limit</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: any) => {
              const bust = !row.feasible
              return (
                <tr key={row.flight_id} className="tr">
                  <td className="cell num text-mute-200">{row.flight_id}</td>
                  <td className="cell num text-mute-400">{row.pairing_id}</td>
                  <td className="cell num text-right text-caution">{row.min_delay_hours}h</td>
                  <td
                    className={clsx('cell num text-right', bust ? 'text-breach font-semibold' : 'text-legal')}
                  >
                    {row.crew_fdp_after_delay}h
                  </td>
                  <td className="cell num text-right text-mute-400">{row.fdp_limit}h</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {c.recovery_plan?.length ? (
        <div className="space-y-1.5">
          <p className="label">Recovery plan</p>
          {c.recovery_plan.map((r: any) => (
            <div key={r.trigger_flight} className="panel p-2.5">
              <div className="flex items-center justify-between">
                <span className="num text-xs text-mute-200">{r.pairing_id}</span>
                <span className="num text-2xs text-mute-400">
                  {r.tail_legs_needing_recrew.length} legs · {r.seats_at_risk} pax
                </span>
              </div>
              <p className="text-2xs text-mute-400 mt-1 leading-snug">{r.recommended}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function DelayBody({ a }: { a: StructuredAnswer }) {
  const d = a.primary
  if (!d) return null
  return (
    <div className="space-y-3">
      <DutyBudgetBar
        used={d.fdp_scheduled}
        added={d.delay_hours}
        limit={d.fdp_limit}
        label={`RULE-FDP-01 · ${d.sectors} sectors on ${d.aircraft}`}
      />
      <p className={clsx('text-xs leading-snug', d.breach ? 'text-breach' : 'text-legal')}>
        {d.breach_detail}
      </p>
      {d.legs_needing_recrew?.length ? (
        <p className="text-2xs text-mute-400">
          The rostered crew can legally operate {d.max_legal_sectors} of {d.sectors} sectors. Handover
          after {d.handover_after_flight}; {d.legs_needing_recrew.join(', ')} needs a fresh complement.
        </p>
      ) : null}
      {(d.options ?? []).map((o: any) => (
        <div key={o.rank} className="panel p-2.5">
          <div className="flex items-start justify-between gap-3">
            <span className="text-xs text-mute-200">{o.action}</span>
            <span className="num text-xs font-semibold text-mute-200 shrink-0">{inr(o.cost_inr)}</span>
          </div>
          <p className="text-2xs text-mute-400 mt-1 leading-snug">{o.reasoning}</p>
        </div>
      ))}
    </div>
  )
}

function NotificationBody({ a }: { a: StructuredAnswer }) {
  const slots = a.slots ?? {}
  return (
    <div className="space-y-3">
      <pre className="panel p-3 text-xs text-mute-200 whitespace-pre-wrap font-mono leading-relaxed">
        {a.fallback_text}
      </pre>
      <details>
        <summary className="cursor-pointer text-2xs text-mute-400 hover:text-signal">
          Deterministic slots — the model may reword these, it cannot change them
        </summary>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 mt-2">
          {Object.entries(slots)
            .filter(([, v]) => typeof v !== 'object')
            .map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2 text-2xs">
                <dt className="text-mute-400">{k.replace(/_/g, ' ')}</dt>
                <dd className="num text-mute-300">{String(v)}</dd>
              </div>
            ))}
        </dl>
      </details>
    </div>
  )
}

function BriefingBody({ a }: { a: StructuredAnswer }) {
  const b = a.primary
  if (!b?.lines) return null
  return (
    <div className="space-y-2">
      {b.lines.map((line: any) => {
        const tight = line.duty_headroom.tightest_crew ?? {}
        const gaps = line.reserve_depth.uncovered_roles ?? []
        return (
          <div key={`${line.aircraft}-${line.pairing_id}`} className="panel p-3">
            <div className="flex items-center justify-between">
              <span className="num text-xs text-mute-200">
                {line.aircraft} <span className="text-mute-400">{line.pairing_id}</span>
              </span>
              <span className="num text-2xs text-mute-400">
                {utcTime(line.report_utc)}–{utcTime(line.release_utc)} · {line.sectors} sectors
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-3 mt-2">
              <Metric
                label="FDP margin"
                value={`${line.duty_headroom.fdp_margin_hours}h`}
                tone={line.duty_headroom.fragile ? 'breach' : 'legal'}
                note={`duty ${line.duty_headroom.fdp_hours}h of ${line.duty_headroom.fdp_limit}h`}
              />
              <Metric
                label="Tightest duty headroom"
                value={`${tight.headroom_hours ?? '—'}h`}
                tone={(tight.headroom_hours ?? 60) < 10 ? 'caution' : 'legal'}
                note={`${tight.crew_id ?? '—'} (${tight.role ?? '—'})`}
              />
              <Metric
                label="Reserve depth"
                value={gaps.length ? `gap: ${gaps.join(', ')}` : 'covered'}
                tone={gaps.length ? 'breach' : 'legal'}
                note={
                  Object.entries(line.reserve_depth.by_rank ?? {})
                    .map(([k, v]) => `${k} ${v}`)
                    .join(' · ') || 'none on call for this report'
                }
              />
            </div>
            {line.risk.highest && (
              <p className="text-2xs text-mute-400 mt-2">
                Highest risk: {line.risk.highest.crew_id} ({line.risk.highest.role}) at{' '}
                {line.risk.highest.score} — {line.risk.highest.drivers?.[0]}
              </p>
            )}
          </div>
        )
      })}
      <p className="text-2xs text-mute-400 leading-relaxed border-t border-ink-800 pt-2">
        {(b.rationale ?? []).join(' · ')}
      </p>
    </div>
  )
}

function Metric({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note?: string
  tone: 'legal' | 'caution' | 'breach'
}) {
  const color = { legal: 'text-legal', caution: 'text-caution', breach: 'text-breach' }[tone]
  return (
    <div>
      <div className="label">{label}</div>
      <div className={clsx('num text-sm font-semibold mt-0.5', color)}>{value}</div>
      {note && <div className="text-2xs text-mute-400 mt-0.5 leading-snug">{note}</div>}
    </div>
  )
}

function AbstentionBody({ a }: { a: StructuredAnswer }) {
  return (
    <div className="rounded-lg border border-advisory/30 bg-advisory/5 p-3 space-y-2">
      <p className="text-xs text-advisory font-semibold flex items-center gap-1.5">
        <Info size={12} /> {a.schema === 'clarification' ? 'Needs one more detail' : 'Outside what I can compute'}
      </p>
      <p className="text-xs text-mute-300 leading-relaxed">{a.reason}</p>
      {(a.suggestions ?? []).length > 0 && (
        <ul className="space-y-1">
          {a.suggestions.map((s: string, i: number) => (
            <li key={i} className="text-2xs text-mute-400 flex gap-1.5">
              <Lightbulb size={10} className="mt-0.5 shrink-0 text-advisory" />
              {s}
            </li>
          ))}
        </ul>
      )}
      {a.capabilities?.cannot_answer && (
        <details>
          <summary className="cursor-pointer text-2xs text-mute-400 hover:text-signal">
            What this advisor deliberately does not answer
          </summary>
          <ul className="mt-1.5 space-y-0.5">
            {a.capabilities.cannot_answer.map((c: string, i: number) => (
              <li key={i} className="text-2xs text-mute-400">
                — {c}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function GenericBody({ a }: { a: StructuredAnswer }) {
  const primary = a.primary
  if (!primary) return null

  const rows: any[] =
    primary.crew ?? primary.flights ?? primary.certifications ?? primary.reserves ?? primary.rules ?? []

  if (Array.isArray(rows) && rows.length > 0 && typeof rows[0] === 'object') {
    const cols = Object.keys(rows[0]).filter((k) => typeof rows[0][k] !== 'object').slice(0, 7)
    return (
      <div className="xscroll max-h-80 overflow-y-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c} className="th">
                  {c.replace(/_/g, ' ')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 60).map((row, i) => (
              <tr key={i} className="tr">
                {cols.map((c) => (
                  <td key={c} className="cell num text-mute-300">
                    {String(row[c] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
      {Object.entries(primary)
        .filter(([, v]) => typeof v !== 'object')
        .map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 text-xs border-b border-ink-800/70 py-1">
            <dt className="text-mute-400">{k.replace(/_/g, ' ')}</dt>
            <dd className="num text-mute-200">{String(v)}</dd>
          </div>
        ))}
    </dl>
  )
}

/** The full chat answer: prose, structured body, citations, and the audit link. */
export function AnswerCard({ answer }: { answer: ChatAnswer }) {
  return (
    <Panel
      title={answer.structured?.headline ?? 'Answer'}
      subtitle={
        answer.intent
          ? `${answer.intent.name} · tier ${answer.tier} · ${answer.plan_source} plan · ${answer.latency_ms?.toFixed(0)}ms`
          : undefined
      }
      actions={
        <div className="flex items-center gap-2">
          <VerificationBadge verification={answer.verification} />
          <Link to={`/runs/${answer.run_id}`} className="btn-ghost" title="Open the full reasoning trace">
            <FileSearch size={12} /> Trace
          </Link>
          <a
            href={api.receiptUrl(answer.run_id)}
            className="btn-ghost"
            title="Download the complete derivation of this answer"
          >
            <Download size={12} /> Receipt
          </a>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-mute-200 whitespace-pre-wrap leading-relaxed">{answer.answer}</p>

        {answer.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {answer.citations.map((c) => (
              <RuleChip key={c} ruleId={c} />
            ))}
          </div>
        )}

        {answer.structured && (
          <div className="border-t border-ink-800 pt-4">
            <AnswerBody structured={answer.structured} />
          </div>
        )}
      </div>
    </Panel>
  )
}
