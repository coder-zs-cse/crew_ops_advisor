import { useQuery } from '@tanstack/react-query'
import { Activity } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBox, Panel, Pass, Skeleton, StatTile } from '../components/ui'
import { api } from '../lib/api'

/** Recent runs plus the aggregate metrics an operator would watch. */
export default function RunsPage() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => api.runs(60), refetchInterval: 15_000 })
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: () => api.metrics(24) })

  const m = metrics.data

  return (
    <div className="p-4 space-y-4 max-w-[1400px] mx-auto">
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile label="Runs (24h)" value={m?.run_count ?? '—'} />
        <StatTile label="p50 latency" value={m?.latency_ms?.p50 ?? '—'} unit="ms" tone="legal" />
        <StatTile
          label="p95 latency"
          value={m?.latency_ms?.p95 ?? '—'}
          unit="ms"
          tone={(m?.latency_ms?.p95 ?? 0) > 5000 ? 'breach' : 'legal'}
        />
        <StatTile
          label="Verification pass"
          value={m?.verification_pass_rate != null ? `${Math.round(m.verification_pass_rate * 100)}%` : '—'}
          tone="legal"
          hint="narration matched the fact ledger"
        />
        <StatTile
          label="Compiled plans"
          value={m ? `${Math.round(m.compiled_plan_rate * 100)}%` : '—'}
          hint="fixed tool path, no LLM planning"
        />
        <StatTile
          label="Abstained"
          value={m ? `${Math.round(m.abstention_rate * 100)}%` : '—'}
          tone="caution"
          hint="declined rather than guessed"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Panel title="Recent runs" bodyClassName="p-0">
          {runs.isLoading && <div className="p-4"><Skeleton rows={6} /></div>}
          {runs.error && <div className="p-4"><ErrorBox error={runs.error} /></div>}
          {runs.data?.runs.length === 0 && (
            <EmptyState icon={Activity} title="No runs yet" body="Ask the advisor a question and its trace appears here." />
          )}
          <div className="xscroll">
            <table className="w-full min-w-[720px] border-collapse">
              <thead>
                <tr>
                  <th className="th w-8" />
                  <th className="th">Question</th>
                  <th className="th w-44">Intent</th>
                  <th className="th w-14">Tier</th>
                  <th className="th w-20 text-right">Latency</th>
                  <th className="th w-16 text-right">Tools</th>
                  <th className="th w-16 text-right">Facts</th>
                </tr>
              </thead>
              <tbody>
                {(runs.data?.runs ?? []).map((r) => (
                  <tr key={r.run_id} className="tr">
                    <td className="cell"><Pass ok={r.verified !== false && !r.abstained} /></td>
                    <td className="cell">
                      <Link to={`/runs/${r.run_id}`} className="text-mute-200 hover:text-signal">
                        {r.question || r.run_id}
                      </Link>
                    </td>
                    <td className="cell text-mute-400">{r.intent ?? '—'}</td>
                    <td className="cell num text-mute-400">{r.tier ?? '—'}</td>
                    <td className="cell num text-right text-mute-300">{r.latency_ms?.toFixed(0) ?? '—'}ms</td>
                    <td className="cell num text-right text-mute-400">{r.tool_call_count}</td>
                    <td className="cell num text-right text-mute-400">{r.fact_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <div className="space-y-4">
          <Panel title="Tool usage" bodyClassName="p-3">
            <ul className="space-y-1">
              {(m?.tool_usage ?? []).slice(0, 12).map((t: any) => (
                <li key={t.tool} className="flex items-center justify-between text-2xs">
                  <span className="text-mute-300 truncate">{t.tool}</span>
                  <span className="num text-mute-400">{t.calls}</span>
                </li>
              ))}
              {!m?.tool_usage?.length && <li className="text-2xs text-mute-400">No tool spans recorded yet.</li>}
            </ul>
          </Panel>

          <Panel title="Node latency" bodyClassName="p-3">
            <ul className="space-y-1">
              {(m?.node_latency_ms ?? []).map((n: any) => (
                <li key={n.node} className="flex items-center justify-between text-2xs">
                  <span className="text-mute-300">{n.node}</span>
                  <span className="num text-mute-400">{n.avg_ms}ms · {n.count}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  )
}
