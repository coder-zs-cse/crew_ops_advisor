import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Check, RefreshCw, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FlightBoard } from '../components/FlightBoard'
import { EmptyState, ErrorBox, Panel, Skeleton, StatTile, Toggle } from '../components/ui'
import { CoverageRing } from '../components/viz'
import { api, type Alert } from '../lib/api'
import { severityColor } from '../lib/viz'

/**
 * The console.
 *
 * Dark cockpit: the default state is quiet. If nothing is coloured, nothing
 * needs a human. What surfaces here are exceptions the watchers found in the
 * *forward* schedule — conditions that are already true and will otherwise
 * become somebody's 05:00 emergency.
 */
export default function ConsolePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [severity, setSeverity] = useState<string>('all')

  const alerts = useQuery({ queryKey: ['alerts'], queryFn: () => api.alerts('open') })
  const snapshot = useQuery({ queryKey: ['snapshot'], queryFn: api.snapshot })
  const gantt = useQuery({ queryKey: ['gantt'], queryFn: () => api.gantt() })
  const clock = useQuery({ queryKey: ['clock'], queryFn: api.clock })
  const reserves = useQuery({
    queryKey: ['reserves', clock.data?.date],
    queryFn: () => api.reserves({ on: clock.data?.date }),
    enabled: Boolean(clock.data?.date),
  })
  const risk = useQuery({ queryKey: ['risk'], queryFn: () => api.risk(5) })

  const sweep = useMutation({
    mutationFn: api.sweepAlerts,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })
  const ack = useMutation({
    mutationFn: (id: string) => api.ackAlert(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const filtered = useMemo(() => {
    const rows = alerts.data?.alerts ?? []
    return severity === 'all' ? rows : rows.filter((a) => a.severity === severity)
  }, [alerts.data, severity])

  const counts = alerts.data?.open_by_severity ?? { critical: 0, warning: 0, info: 0 }

  // Coverage = duty days on the selected date with a full complement rostered.
  const coverage = useMemo(() => {
    const rows = gantt.data?.rows ?? []
    const today = clock.data?.date
    if (!today) return { pct: 100, total: 0 }
    const dayPairings = rows.flatMap((r) => r.pairings.filter((p) => p.date === today))
    if (dayPairings.length === 0) return { pct: 100, total: 0 }
    const crewed = dayPairings.filter((p) => p.crew.length >= 6).length
    return { pct: (crewed / dayPairings.length) * 100, total: dayPairings.length }
  }, [gantt.data, clock.data])

  return (
    <div className="p-4 grid gap-4 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)_minmax(0,260px)]">
      {/* ---- Alert stack ---- */}
      <Panel
        title="Items needing attention"
        subtitle={
          counts.critical + counts.warning + counts.info === 0
            ? 'All clear'
            : `${counts.critical} critical · ${counts.warning} warning · ${counts.info} info`
        }
        actions={
          <button
            className="btn-ghost"
            onClick={() => sweep.mutate()}
            disabled={sweep.isPending}
            title="Re-run every watcher against the current simulated time"
          >
            <RefreshCw size={11} className={sweep.isPending ? 'animate-spin' : ''} /> Sweep
          </button>
        }
        bodyClassName="p-3 space-y-2 overflow-y-auto max-h-[calc(100vh-9rem)]"
      >
        <Toggle
          value={severity}
          onChange={setSeverity}
          options={[
            { value: 'all', label: 'All' },
            { value: 'critical', label: `Critical ${counts.critical}` },
            { value: 'warning', label: `Warning ${counts.warning}` },
            { value: 'info', label: `Info ${counts.info}` },
          ]}
        />

        {alerts.isLoading && <Skeleton rows={4} />}
        {alerts.error && <ErrorBox error={alerts.error} />}
        {!alerts.isLoading && filtered.length === 0 && (
          <EmptyState
            icon={ShieldCheck}
            title="Nothing needs you"
            body="The watchers found no forward-schedule condition that requires a controller. Advance the clock to look further ahead."
          />
        )}

        {filtered.map((a) => (
          <AlertCard
            key={a.id}
            alert={a}
            onAsk={() =>
              navigate('/advisor', { state: { question: a.suggested_question ?? a.title } })
            }
            onAck={() => ack.mutate(a.id)}
          />
        ))}
      </Panel>

      {/* ---- Operational picture ---- */}
      <div className="space-y-4 min-w-0">
        <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
          <StatTile
            label="Flights"
            value={snapshot.data?.counts.flights ?? '—'}
            hint={`${snapshot.data?.schedule.start ?? ''} → ${snapshot.data?.schedule.end ?? ''}`}
          />
          <StatTile label="Active crew" value={snapshot.data?.counts.crew ?? '—'} hint="rank, base, ratings on file" />
          <StatTile
            label="Reserves on call"
            value={reserves.data?.count ?? '—'}
            hint={`across ${snapshot.data?.stations.length ?? 0} stations`}
          />
          <StatTile
            label="Critical exceptions"
            value={counts.critical}
            tone={counts.critical > 0 ? 'breach' : 'legal'}
            hint={counts.critical ? 'grounded illegalities in the published roster' : 'roster is clean'}
          />
        </div>

        <Panel
          title="Flights"
          subtitle="Published schedule. Open a row for the complement; click a crew member to start a disruption."
          bodyClassName="p-3"
        >
          <FlightBoard />
        </Panel>
      </div>

      {/* ---- KPI rail ---- */}
      <div className="space-y-4">
        <Panel title="Coverage" bodyClassName="p-4">
          <CoverageRing
            value={coverage.pct}
            label={`${coverage.total} duties today`}
            sublabel="Full complement rostered. A gap here is an uncrewed departure."
          />
        </Panel>

        <Panel title="Highest disruption risk" subtitle="Provided signal — not modelled here" bodyClassName="p-3">
          {risk.isLoading && <Skeleton rows={3} />}
          <ul className="space-y-1.5">
            {(risk.data?.crew ?? []).map((c: any) => (
              <li key={c.crew_id}>
                <button
                  onClick={() => navigate(`/crew/${c.crew_id}`)}
                  className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-ink-850 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="num text-2xs text-mute-200">{c.crew_id}</span>
                    <span className="num text-2xs text-caution">{c.score}</span>
                  </div>
                  <div className="text-2xs text-mute-400 truncate mt-0.5">{c.drivers?.[0]}</div>
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="The boundary" bodyClassName="p-3">
          <p className="text-2xs text-mute-400 leading-relaxed">
            The language model classifies the question and writes the explanation. Every number,
            legality verdict, cost and ranking on this screen was computed by code — and the
            explanation is checked against those computations before you see it.
          </p>
          <button className="btn-ghost mt-2 w-full" onClick={() => navigate('/eval')}>
            See the live scorecard <ArrowRight size={11} />
          </button>
        </Panel>
      </div>
    </div>
  )
}

function AlertCard({
  alert,
  onAsk,
  onAck,
}: {
  alert: Alert
  onAsk: () => void
  onAck: () => void
}) {
  const color = severityColor(alert.severity)
  return (
    <article
      className="rounded-lg border bg-ink-850 p-2.5 animate-slide-up"
      style={{ borderColor: `${color}44` }}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={13} style={{ color }} className="mt-0.5 shrink-0" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="chip" style={{ color, borderColor: `${color}55`, background: `${color}18` }}>
              {alert.type.replace(/_/g, ' ').toLowerCase()}
            </span>
          </div>
          <h3 className="text-xs font-medium text-mute-200 mt-1.5 leading-snug">{alert.title}</h3>
          <p className="text-2xs text-mute-400 mt-1 leading-relaxed">{alert.detail}</p>

          <div className="flex items-center gap-1.5 mt-2">
            {alert.suggested_question && (
              <button className="btn-primary" onClick={onAsk}>
                Ask the advisor
              </button>
            )}
            <button className="btn-ghost" onClick={onAck}>
              <Check size={11} /> Acknowledge
            </button>
          </div>
        </div>
      </div>
    </article>
  )
}
