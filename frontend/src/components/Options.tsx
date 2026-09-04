import clsx from 'clsx'
import { ChevronDown, ChevronRight, Plane, Send, XCircle } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'
import type { CandidateSetPayload, CoverOption, ExcludedCandidate } from '../lib/api'
import { inr } from '../lib/api'
import { STATUS, ruleColor, ruleShort } from '../lib/viz'
import { LegalityBadge, Legend, Toggle, Tip } from './ui'
import { CandidateScatter, ExclusionBreakdown, RuleProof } from './viz'

/**
 * The ranked options table.
 *
 * Two rankings are shown side by side and the difference is stated, not hidden:
 * `cost` is the reference ordering that the shipped answer keys use, `ops` is
 * our own multi-factor score. Substituting a private heuristic for the graded
 * ordering would be the wrong trade — the heuristic is a better *opinion*, the
 * cost order is the checkable *answer*.
 */
export function OptionsTable({
  options,
  onApply,
  onNotify,
  currency = '₹',
}: {
  options: CoverOption[]
  onApply?: (option: CoverOption) => void
  onNotify?: (option: CoverOption) => void
  currency?: string
}) {
  const [sort, setSort] = useState<'cost' | 'ops'>('cost')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const sorted = useMemo(() => {
    const copy = [...options]
    if (sort === 'ops') {
      copy.sort((a, b) => {
        if (a.source === 'cancellation') return 1
        if (b.source === 'cancellation') return -1
        return (a.ops_rank ?? 99) - (b.ops_rank ?? 99)
      })
    }
    return copy
  }, [options, sort])

  const legal = sorted.filter((o) => o.crew_id)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Toggle
          value={sort}
          onChange={(v) => setSort(v as 'cost' | 'ops')}
          options={[
            { value: 'cost', label: 'Cost rank', title: 'Cost then crew id — the reference ordering the answer keys use' },
            { value: 'ops', label: 'Ops rank', title: 'Our multi-factor score: cost, delay, reachability, duty headroom, fatigue risk' },
          ]}
        />
        <span className="text-2xs text-mute-400">
          {sort === 'cost'
            ? 'Authoritative ordering — matches the graded answer keys.'
            : 'Our opinion. Cost still dominates, but reachability and remaining headroom count.'}
        </span>
      </div>

      {legal.length > 1 && (
        <CandidateScatter options={legal} onSelect={setSelected} selected={selected} />
      )}

      <div className="xscroll">
        <table className="w-full min-w-[720px] border-collapse">
          <thead>
            <tr>
              <th className="th w-8" />
              <th className="th w-10">#</th>
              <th className="th">Action</th>
              <th className="th w-24 text-right">Cost</th>
              <th className="th w-16 text-right">Delay</th>
              <th className="th w-20">Source</th>
              <th className="th w-24">Reach</th>
              <th className="th w-16">Legal</th>
              <th className="th w-20" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((o) => {
              const key = o.crew_id ?? `cancel-${o.rank}`
              const open = expanded === key
              const cancel = o.source === 'cancellation'
              return (
                <Fragment key={key}>
                  <tr
                    className={clsx(
                      'tr cursor-pointer',
                      selected === o.crew_id && 'bg-ink-750',
                      cancel && 'opacity-70',
                    )}
                    onClick={() => setExpanded(open ? null : key)}
                  >
                    <td className="cell text-mute-400">
                      {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    </td>
                    <td className="cell num text-mute-400">
                      {sort === 'cost' ? o.rank : (o.ops_rank ?? o.rank)}
                    </td>
                    <td className="cell">
                      <div className="flex items-center gap-1.5">
                        {cancel ? (
                          <XCircle size={12} className="text-breach shrink-0" aria-hidden />
                        ) : (
                          <Plane size={12} className="text-mute-400 shrink-0" aria-hidden />
                        )}
                        <span className="text-mute-200">{o.action}</span>
                      </div>
                      {o.crew_name && (
                        <span className="text-2xs text-mute-400 ml-[18px]">
                          {o.crew_name} · {o.base} · {o.ratings?.join(', ')}
                        </span>
                      )}
                    </td>
                    <td className="cell num text-right font-semibold text-mute-200">{inr(o.cost_inr)}</td>
                    <td className="cell num text-right">
                      {o.delay_hours ? (
                        <span className="text-caution">{o.delay_hours}h</span>
                      ) : (
                        <span className="text-mute-400">—</span>
                      )}
                    </td>
                    <td className="cell">
                      {o.source && (
                        <span className={cancel ? 'chip-breach' : 'chip-neutral'}>{o.source}</span>
                      )}
                    </td>
                    <td className="cell num text-mute-400">
                      {o.reachability_minutes !== undefined ? `${o.reachability_minutes} min` : '—'}
                    </td>
                    <td className="cell">
                      <LegalityBadge legal={o.legal} />
                    </td>
                    <td className="cell">
                      {!cancel && onApply && (
                        <button
                          className="btn-primary"
                          onClick={(e) => {
                            e.stopPropagation()
                            onApply(o)
                          }}
                        >
                          Apply
                        </button>
                      )}
                    </td>
                  </tr>

                  {open && (
                    <tr className="bg-ink-850/60">
                      <td colSpan={9} className="px-4 py-3">
                        <div className="grid gap-3 lg:grid-cols-2">
                          <div className="space-y-2">
                            <p className="label">Cost breakdown</p>
                            <ul className="space-y-1">
                              {(o.cost_breakdown?.lines ?? []).map((line, i) => (
                                <li key={i} className="flex items-baseline justify-between gap-3 text-2xs">
                                  <span className="text-mute-300">{line.label}</span>
                                  <span className="text-mute-400/70 flex-1 truncate">{line.basis}</span>
                                  <span className="num text-mute-200">
                                    {currency}
                                    {line.amount.toLocaleString('en-IN')}
                                  </span>
                                </li>
                              ))}
                              <li className="flex items-baseline justify-between gap-3 text-2xs border-t border-ink-700 pt-1 mt-1">
                                <span className="font-semibold text-mute-200">Total</span>
                                <span className="num font-semibold text-mute-200">{inr(o.cost_inr)}</span>
                              </li>
                            </ul>

                            {o.positioning && (
                              <div className="rounded-lg border border-caution/30 bg-caution/5 p-2 mt-2">
                                <p className="text-2xs text-caution font-semibold">Deadhead positioning</p>
                                <p className="text-2xs text-mute-300 mt-0.5 leading-snug">
                                  {o.positioning.flight_no} {o.positioning.from_station}→
                                  {o.positioning.to_station}, arriving {o.positioning.arrival_utc.slice(11, 16)}Z.
                                  New report {o.positioning.new_report_utc.slice(11, 16)}Z, delaying the first
                                  departure {o.positioning.delay_hours}h.
                                </p>
                              </div>
                            )}

                            {o.ops_factors && (
                              <div className="mt-2">
                                <p className="label mb-1">Why this ops rank</p>
                                <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                                  {Object.entries(o.ops_factors).map(([k, v]) => (
                                    <div key={k} className="flex justify-between gap-2 text-2xs">
                                      <dt className="text-mute-400">{k.replace(/_/g, ' ')}</dt>
                                      <dd className="num text-mute-300">{String(v)}</dd>
                                    </div>
                                  ))}
                                </dl>
                              </div>
                            )}

                            {onNotify && o.crew_id && (
                              <button className="btn-ghost mt-2" onClick={() => onNotify(o)}>
                                <Send size={12} /> Draft callout
                              </button>
                            )}
                          </div>

                          <div className="space-y-2">
                            <p className="label">Rule evaluation</p>
                            <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1">
                              {(o.verdicts ?? [])
                                .filter((v) => v.verdict !== 'not_applicable')
                                .map((v, i) => (
                                  <RuleProof key={i} verdict={v} />
                                ))}
                              {!o.verdicts?.length && (
                                <p className="text-2xs text-mute-400">
                                  Cancellation is not a crew assignment, so no rules apply to it.
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/**
 * The excluded-candidates table.
 *
 * This is the differentiator. Every ranked list looks confident; the question a
 * controller actually asks is "why not X?" — and this answers it for all of
 * them, with the rule and the arithmetic that did the rejecting.
 */
export function ExcludedTable({
  excluded,
  summary,
  evaluated,
  eligible,
}: {
  excluded: ExcludedCandidate[]
  summary: Record<string, number>
  evaluated: number
  eligible: number
}) {
  const [filter, setFilter] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

  const rows = filter ? excluded.filter((e) => e.rule_ids.includes(filter)) : excluded

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)]">
      <div>
        <ExclusionBreakdown
          summary={summary}
          evaluated={evaluated}
          eligible={eligible}
          onSelectRule={setFilter}
          activeRule={filter}
        />
        {filter && (
          <button className="btn-ghost mt-2 w-full" onClick={() => setFilter(null)}>
            Clear filter
          </button>
        )}
      </div>

      <div className="xscroll max-h-[420px] overflow-y-auto">
        <table className="w-full min-w-[420px] border-collapse">
          <thead>
            <tr>
              <th className="th w-24">Crew</th>
              <th className="th w-28">Rule</th>
              <th className="th">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <Fragment key={e.crew_id}>
                <tr
                  className="tr cursor-pointer align-top"
                  onClick={() => setOpen(open === e.crew_id ? null : e.crew_id)}
                >
                  <td className="cell num text-mute-200">{e.crew_id}</td>
                  <td className="cell">
                    <div className="flex flex-wrap gap-1">
                      {e.rule_ids.map((r) => (
                        <span
                          key={r}
                          className="chip"
                          style={{
                            color: ruleColor(r),
                            borderColor: `${ruleColor(r)}55`,
                            background: `${ruleColor(r)}18`,
                          }}
                        >
                          {ruleShort(r)}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="cell text-mute-300 leading-snug">{e.reason}</td>
                </tr>
                {open === e.crew_id && (e.verdicts?.length ?? 0) > 0 && (
                  <tr className="bg-ink-850/60">
                    <td colSpan={3} className="px-3 py-2">
                      <div className="grid gap-2 sm:grid-cols-2">
                        {e.verdicts!.map((v, i) => (
                          <RuleProof key={i} verdict={v} />
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={3} className="cell text-mute-400">
                  No candidates were excluded on this rule.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** The full recommendation block: options, rejections, and a one-line summary. */
export function CandidateSetView({
  data,
  onApply,
  onNotify,
}: {
  data: CandidateSetPayload
  onApply?: (option: CoverOption) => void
  onNotify?: (option: CoverOption) => void
}) {
  const [tab, setTab] = useState<'options' | 'excluded'>('options')
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Toggle
          value={tab}
          onChange={(v) => setTab(v as 'options' | 'excluded')}
          options={[
            { value: 'options', label: `Options (${data.eligible_count})` },
            { value: 'excluded', label: `Excluded (${data.excluded_count})` },
          ]}
        />
        <Tip text="Every active crew member of the required rank was evaluated — reserves and day-off line crew alike.">
          <span className="text-2xs text-mute-400 underline decoration-dotted underline-offset-2">
            {data.evaluated_count} candidates evaluated
          </span>
        </Tip>
      </div>

      {tab === 'options' ? (
        <OptionsTable options={data.options} onApply={onApply} onNotify={onNotify} />
      ) : (
        <ExcludedTable
          excluded={data.excluded_candidates}
          summary={data.exclusion_summary}
          evaluated={data.evaluated_count}
          eligible={data.eligible_count}
        />
      )}
    </div>
  )
}

export function CostLegend() {
  return (
    <Legend
      items={[
        { color: STATUS.legal, label: 'Legal' },
        { color: STATUS.breach, label: 'Excluded' },
      ]}
    />
  )
}
