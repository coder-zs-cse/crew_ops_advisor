import clsx from 'clsx'
import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { RunDetail, Span, Verification } from '../lib/api'
import { SPAN_COLORS, SPAN_TYPES, STATUS } from '../lib/viz'
import { Legend, Pass, Tip } from './ui'

/**
 * Span waterfall.
 *
 * The point of showing this to a controller is not debugging — it is that the
 * work is visible and finite: 24 candidates evaluated in 74ms, by name, with
 * the rule that rejected each. Colour encodes span type (validated categorical
 * palette); depth encodes nesting; width encodes time.
 */
export function TraceWaterfall({ spans }: { spans: Span[] }) {
  const [open, setOpen] = useState<string | null>(null)

  const total = useMemo(
    () => Math.max(1, ...spans.map((s) => (s.offset_ms ?? 0) + (s.duration_ms ?? 0))),
    [spans],
  )
  const typesPresent = useMemo(
    () => SPAN_TYPES.filter((t) => spans.some((s) => s.type === t)),
    [spans],
  )

  return (
    <div className="space-y-2">
      <Legend items={typesPresent.map((t) => ({ color: SPAN_COLORS[t], label: t }))} />

      <ul className="space-y-[3px]">
        {spans.map((span) => {
          const offset = ((span.offset_ms ?? 0) / total) * 100
          const width = Math.max(0.6, ((span.duration_ms ?? 0) / total) * 100)
          const isOpen = open === span.span_id
          const summary: string = String(
            span.attrs?.result_summary ??
              span.attrs?.router_intent ??
              (span.attrs?.passed !== undefined ? `passed=${span.attrs.passed}` : ''),
          )
          return (
            <li key={span.span_id}>
              <button
                onClick={() => setOpen(isOpen ? null : span.span_id)}
                className="w-full flex items-center gap-2 px-1 py-1 rounded hover:bg-ink-850 text-left"
              >
                <span
                  className="shrink-0 text-mute-400"
                  style={{ paddingLeft: `${(span.depth ?? 0) * 12}px` }}
                >
                  {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                </span>
                <span className="w-[190px] shrink-0 trace-line text-mute-200 truncate" title={span.name}>
                  {span.name}
                </span>
                <span className="flex-1 relative h-3 rounded bg-ink-850 min-w-[80px]">
                  <Tip
                    className="absolute inset-y-0"
                    style={{ left: `${offset}%`, width: `${width}%` }}
                    text={`${span.type} · ${span.duration_ms ?? 0}ms`}
                  >
                    <span
                      className="w-full h-full rounded-[3px]"
                      style={{
                        background:
                          span.status === 'error' ? STATUS.breach : SPAN_COLORS[span.type] ?? STATUS.neutral,
                      }}
                    />
                  </Tip>
                </span>
                <span className="w-[68px] shrink-0 trace-line text-right text-mute-300">
                  {(span.duration_ms ?? 0).toFixed(2)}ms
                </span>
                <span className="w-[210px] shrink-0 trace-line text-mute-400 truncate" title={String(summary)}>
                  {String(summary)}
                </span>
              </button>

              {isOpen && (
                <div className="ml-8 mb-1.5 grid gap-2 lg:grid-cols-2">
                  <SpanBlob title="Input" value={span.input} />
                  <SpanBlob title="Output" value={span.output} />
                  {Object.keys(span.attrs ?? {}).length > 0 && (
                    <SpanBlob title="Attributes" value={span.attrs} />
                  )}
                  {span.error && (
                    <div className="rounded-lg border border-breach/30 bg-breach/5 p-2">
                      <p className="text-2xs font-semibold text-breach">Error</p>
                      <p className="trace-line text-mute-300 mt-1">{span.error}</p>
                    </div>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function SpanBlob({ title, value }: { title: string; value: unknown }) {
  if (value === null || value === undefined) return null
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850 p-2 min-w-0">
      <p className="label mb-1">{title}</p>
      <pre className="trace-line text-mute-300 whitespace-pre-wrap break-words max-h-52 overflow-y-auto">
        {typeof value === 'string' ? value : JSON.stringify(value, null, 1)}
      </pre>
    </div>
  )
}

/** The fact ledger — what the verifier checks the narration against. */
export function FactLedger({ facts }: { facts: RunDetail['facts'] }) {
  const [query, setQuery] = useState('')
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const filtered = q
      ? facts.filter((f) => f.key.toLowerCase().includes(q) || String(f.value).toLowerCase().includes(q))
      : facts
    return filtered.slice(0, 400)
  }, [facts, query])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <input
          className="input flex-1 py-1 text-xs"
          placeholder="Filter facts — try a number from the answer"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="text-2xs text-mute-400 shrink-0">
          {rows.length} of {facts.length}
        </span>
      </div>
      <p className="text-2xs text-mute-400 leading-relaxed">
        Every scalar the tools produced. The narration verifier requires each number, crew id, flight id
        and rule id in the prose to appear here — anything else fails the answer.
      </p>
      <div className="xscroll max-h-[420px] overflow-y-auto">
        <table className="w-full min-w-[520px] border-collapse">
          <thead>
            <tr>
              <th className="th w-16">Fact</th>
              <th className="th">Key</th>
              <th className="th w-40">Value</th>
              <th className="th w-40">Tool</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={f.fact_id} className="tr">
                <td className="cell num text-mute-400">{f.fact_id}</td>
                <td className="cell trace-line text-mute-300 break-all">{f.key}</td>
                <td className="cell num text-mute-200 break-all">{String(f.value)}</td>
                <td className="cell trace-line text-mute-400">{f.source_tool ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** The rule-evaluation log — every verdict with its arithmetic. */
export function RuleEvaluationTable({ rows }: { rows: RunDetail['rule_evaluations'] }) {
  const [onlyBreaches, setOnlyBreaches] = useState(true)
  const filtered = onlyBreaches ? rows.filter((r) => r.verdict === 'breach') : rows

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-2xs text-mute-400 cursor-pointer">
        <input
          type="checkbox"
          checked={onlyBreaches}
          onChange={(e) => setOnlyBreaches(e.target.checked)}
          className="accent-signal"
        />
        Breaches only ({rows.filter((r) => r.verdict === 'breach').length} of {rows.length})
      </label>
      <div className="xscroll max-h-[420px] overflow-y-auto">
        <table className="w-full min-w-[680px] border-collapse">
          <thead>
            <tr>
              <th className="th w-28">Rule</th>
              <th className="th w-20">Crew</th>
              <th className="th w-24">Date</th>
              <th className="th w-20 text-right">Actual</th>
              <th className="th w-20 text-right">Limit</th>
              <th className="th w-20 text-right">Margin</th>
              <th className="th">Message</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={i} className="tr">
                <td className="cell">
                  <span className={r.verdict === 'breach' ? 'chip-breach' : r.verdict === 'advisory' ? 'chip-advisory' : 'chip-legal'}>
                    {r.rule_id}
                  </span>
                </td>
                <td className="cell num text-mute-300">{r.crew_id ?? '—'}</td>
                <td className="cell num text-mute-400">{r.date ?? '—'}</td>
                <td className="cell num text-right text-mute-200">{r.actual ?? '—'}</td>
                <td className="cell num text-right text-mute-400">{r.limit ?? '—'}</td>
                <td
                  className={clsx(
                    'cell num text-right',
                    (r.margin ?? 0) < 0 ? 'text-breach' : 'text-legal',
                  )}
                >
                  {r.margin ?? '—'}
                </td>
                <td className="cell text-mute-300 leading-snug">{r.message}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="cell text-mute-400">
                  No breaches in this run — every rule evaluated clean.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** The verification report: what was checked, and what (if anything) failed. */
export function VerificationPanel({ verification }: { verification: Verification }) {
  return (
    <div className="space-y-2">
      <div
        className={clsx(
          'rounded-lg border p-3',
          verification.passed ? 'border-legal/30 bg-legal/5' : 'border-caution/30 bg-caution/5',
        )}
      >
        <p className={clsx('text-xs font-semibold', verification.passed ? 'text-legal' : 'text-caution')}>
          {verification.passed
            ? 'Narration verified against the fact ledger'
            : 'Narration failed verification — the engine’s own figures were served instead'}
        </p>
        <p className="text-2xs text-mute-400 mt-1 leading-relaxed">
          {verification.summary}
          {verification.repair_attempts > 0 && ` · ${verification.repair_attempts} repair attempt(s)`}
        </p>
      </div>

      <ul className="space-y-1">
        {verification.checks.map((c) => (
          <li key={c.name} className="flex items-center gap-2 px-2 py-1 rounded bg-ink-850">
            <Pass ok={c.passed} />
            <span className="text-2xs text-mute-200 w-48 shrink-0">{c.name.replace(/_/g, ' ')}</span>
            <span className="text-2xs text-mute-400 truncate">{c.detail}</span>
          </li>
        ))}
      </ul>

      {verification.violations.length > 0 && (
        <div className="rounded-lg border border-breach/30 bg-breach/5 p-2.5">
          <p className="text-2xs font-semibold text-breach flex items-center gap-1.5">
            <AlertTriangle size={11} /> Ungrounded values
          </p>
          <ul className="mt-1.5 space-y-1">
            {verification.violations.map((v, i) => (
              <li key={i} className="text-2xs text-mute-300">
                <span className="num text-breach">{v.value}</span>
                <span className="text-mute-400"> — {v.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
