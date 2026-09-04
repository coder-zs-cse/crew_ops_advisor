import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, RefreshCcw } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { FactLedger, RuleEvaluationTable, TraceWaterfall, VerificationPanel } from '../components/Trace'
import { ErrorBox, Panel, Skeleton, StatTile, Toggle } from '../components/ui'
import { api } from '../lib/api'

/**
 * The run inspector — the "reasoning receipt" made browsable.
 *
 * Four views over one answer: what ran (waterfall), what it produced (fact
 * ledger), what the rulebook said (rule evaluations), and whether the prose
 * survived checking against all of it (verification).
 */
export default function RunDetailPage() {
  const { runId = '' } = useParams()
  const [tab, setTab] = useState('waterfall')

  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.run(runId) })
  const replay = useMutation({ mutationFn: () => api.replayRun(runId) })

  const spans = run.data?.waterfall ?? run.data?.spans ?? []
  const verification = (run.data as any)?.verification

  return (
    <div className="p-4 space-y-4 max-w-[1400px] mx-auto">
      <div className="flex items-center gap-3 flex-wrap">
        <Link to="/runs" className="btn-ghost">
          <ArrowLeft size={12} /> All traces
        </Link>
        <span className="num text-2xs text-mute-400">{runId}</span>
        <div className="ml-auto flex items-center gap-2">
          <button
            className="btn-ghost"
            onClick={() => replay.mutate()}
            disabled={replay.isPending}
            title="Re-execute the deterministic tool calls and compare output hashes"
          >
            <RefreshCcw size={11} className={replay.isPending ? 'animate-spin' : ''} /> Replay & diff
          </button>
          <a href={api.receiptUrl(runId)} className="btn-primary">
            <Download size={12} /> Receipt
          </a>
        </div>
      </div>

      {run.isLoading && <Skeleton rows={6} />}
      {run.error && <ErrorBox error={run.error} />}

      {run.data && (
        <>
          <Panel bodyClassName="p-4">
            <p className="text-sm text-mute-200">{run.data.question}</p>
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 mt-3">
              <StatTile label="Intent" value={run.data.intent ?? '—'} hint={`tier ${run.data.tier ?? '—'}`} />
              <StatTile
                label="Latency"
                value={run.data.latency_ms?.toFixed(1) ?? '—'}
                unit="ms"
                tone={(run.data.latency_ms ?? 0) < 1000 ? 'legal' : 'caution'}
              />
              <StatTile label="Spans" value={run.data.span_count} hint={`${run.data.tool_call_count} tool calls`} />
              <StatTile label="Facts" value={run.data.fact_count} hint="values the narration may cite" />
              <StatTile
                label="Rule evaluations"
                value={run.data.rule_evaluations?.length ?? 0}
                hint={`${(run.data.rule_evaluations ?? []).filter((r) => r.verdict === 'breach').length} breaches`}
              />
              <StatTile
                label="Verified"
                value={run.data.verified === null ? 'n/a' : run.data.verified ? 'Yes' : 'No'}
                tone={run.data.verified === null ? 'neutral' : run.data.verified ? 'legal' : 'breach'}
                hint={
                  run.data.verified === null
                    ? 'direct simulation — no narration'
                    : run.data.abstained
                      ? 'abstained'
                      : (run.data.plan_source ?? '')
                }
              />
            </div>
          </Panel>

          {replay.data && (
            <Panel
              title="Deterministic replay"
              subtitle="Nothing below the boundary depends on a model, so a replay must be byte-identical"
              bodyClassName="p-3"
            >
              <p
                className={
                  replay.data.deterministic
                    ? 'text-xs text-legal'
                    : 'text-xs text-breach'
                }
              >
                {replay.data.deterministic
                  ? `All ${replay.data.tool_calls_replayed} tool calls reproduced identically.`
                  : 'A tool produced different output on replay — that is a non-determinism bug.'}
              </p>
              <ul className="mt-2 space-y-0.5">
                {replay.data.comparisons.map((c: any, i: number) => (
                  <li key={i} className="flex items-center gap-2 trace-line">
                    <span className={c.identical ? 'text-legal' : 'text-breach'}>
                      {c.identical ? '✓' : '✗'}
                    </span>
                    <span className="text-mute-200 w-52 truncate">{c.tool}</span>
                    <span className="text-mute-400">
                      {c.original_hash} → {c.replay_hash}
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel
            actions={
              <Toggle
                value={tab}
                onChange={setTab}
                options={[
                  { value: 'waterfall', label: `Waterfall (${spans.length})` },
                  { value: 'rules', label: `Rules (${run.data.rule_evaluations?.length ?? 0})` },
                  { value: 'facts', label: `Facts (${run.data.facts?.length ?? 0})` },
                  { value: 'verify', label: 'Verification' },
                ]}
              />
            }
            title="Reasoning trace"
            bodyClassName="p-3"
          >
            {tab === 'waterfall' && <TraceWaterfall spans={spans} />}
            {tab === 'rules' && <RuleEvaluationTable rows={run.data.rule_evaluations ?? []} />}
            {tab === 'facts' && <FactLedger facts={run.data.facts ?? []} />}
            {tab === 'verify' &&
              (verification ? (
                <VerificationPanel verification={verification} />
              ) : (
                <p className="text-xs text-mute-400">
                  This run was a direct simulation call, not a chat answer, so there was no narration to
                  verify. Every figure came straight from the engine.
                </p>
              ))}
          </Panel>
        </>
      )}
    </div>
  )
}
