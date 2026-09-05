import { useMutation, useQuery } from '@tanstack/react-query'
import { FileSearch, GitBranch, Play, Send } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AnswerBody } from '../components/AnswerCard'
import { EntityPicker } from '../components/EntityPicker'
import { CandidateSetView } from '../components/Options'
import { EmptyState, ErrorBox, Panel, Spinner, StatTile } from '../components/ui'
import { api, inr, type CoverOption } from '../lib/api'

type EventKind = 'sick' | 'closure' | 'delay' | 'cert' | 'cancellation' | 'multi_sick'

const KINDS: { value: EventKind; label: string; hint: string }[] = [
  { value: 'sick', label: 'Sick call', hint: 'A crew member drops off a pairing' },
  { value: 'multi_sick', label: 'Two sick calls', hint: 'Competing openings, one scarce pool' },
  { value: 'closure', label: 'Station closure', hint: 'A station shuts for a window' },
  { value: 'delay', label: 'Aircraft delay', hint: 'A tech delay walks the rotation' },
  { value: 'cert', label: 'Certification lapse', hint: 'A certificate expires before a duty' },
  { value: 'cancellation', label: 'Cancellation', hint: 'Drop legs and price it' },
]

/**
 * The disruption workbench.
 *
 * Every run here forks the world — the snapshot is never mutated — so a second
 * event can be applied to the result of the first. That is what "chained
 * disruptions" means, and the lineage strip shows the chain.
 */
export default function WorkbenchPage() {
  const location = useLocation() as {
    state?: { pairingId?: string; crewId?: string; flightId?: string; aircraft?: string; date?: string }
  }
  const incoming = location.state
  const [kind, setKind] = useState<EventKind>('sick')
  const [form, setForm] = useState<Record<string, string>>({
    crew_id: incoming?.crewId ?? 'C-1042',
    pairing_id: incoming?.pairingId ?? 'P-2291',
    reported_utc: '2026-09-15T05:00:00Z',
    station: 'BLR',
    start_utc: '2026-09-17T08:00:00Z',
    end_utc: '2026-09-17T14:00:00Z',
    aircraft: incoming?.aircraft ?? 'VT-DXA',
    date: incoming?.date ?? '2026-09-16',
    delay_hours: '1.5',
    flight_ids: incoming?.flightId ?? 'DX404-2026-09-16',
    crew_id_2: 'C-1938',
    pairing_id_2: 'P-2212',
  })
  const [result, setResult] = useState<any>(null)
  const [applied, setApplied] = useState<string | null>(null)
  const [notification, setNotification] = useState<string | null>(null)

  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: () => api.scenarios(true) })

  useEffect(() => {
    const { pairingId, crewId, flightId, aircraft, date } = location.state ?? {}
    if (!pairingId && !crewId && !flightId) return
    setKind('sick')
    setForm((f) => ({
      ...f,
      ...(crewId ? { crew_id: crewId } : {}),
      ...(pairingId ? { pairing_id: pairingId } : {}),
      ...(flightId ? { flight_ids: flightId } : {}),
      ...(aircraft ? { aircraft } : {}),
      ...(date ? { date } : {}),
    }))
  }, [location.state?.pairingId, location.state?.crewId, location.state?.flightId, location.state?.aircraft, location.state?.date])

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))
  const setValue = (k: string) => (v: string) => setForm((f) => ({ ...f, [k]: v }))

  const run = useMutation({
    mutationFn: async () => {
      switch (kind) {
        case 'sick':
          return api.simulateSick({
            crew_id: form.crew_id,
            pairing_id: form.pairing_id || undefined,
            reported_utc: form.reported_utc || undefined,
          })
        case 'multi_sick':
          return api.simulateMultiSick({
            events: [
              { crew_id: form.crew_id, pairing_id: form.pairing_id, reported_utc: form.reported_utc },
              { crew_id: form.crew_id_2, pairing_id: form.pairing_id_2, reported_utc: form.reported_utc },
            ],
          })
        case 'closure':
          return api.simulateClosure({
            station: form.station,
            start_utc: form.start_utc,
            end_utc: form.end_utc,
          })
        case 'delay':
          return api.simulateDelay({
            aircraft: form.aircraft,
            date: form.date,
            delay_hours: Number(form.delay_hours),
          })
        case 'cert':
          return api.simulateCert({
            crew_id: form.crew_id,
            pairing_id: form.pairing_id,
            reported_utc: form.reported_utc || undefined,
          })
        case 'cancellation':
          return api.simulateCancellation({
            flight_ids: form.flight_ids.split(',').map((s) => s.trim()).filter(Boolean),
          })
      }
    },
    onSuccess: (data) => {
      setResult(data)
      setApplied(null)
      setNotification(null)
    },
  })

  const replay = useMutation({
    mutationFn: (id: string) => api.replayScenario(id),
    onSuccess: (data) => {
      setResult(data.result)
      setApplied(null)
    },
  })

  const apply = useMutation({
    mutationFn: (option: CoverOption) =>
      api.createDecision({
        run_id: result?.run_id,
        kind: 'assignment',
        pairing_id: result?.pairing_id ?? form.pairing_id,
        crew_id: option.crew_id,
        option,
      }),
    onSuccess: (_, option) => setApplied(option.crew_id),
  })

  const draft = useMutation({
    mutationFn: (option: CoverOption) =>
      api.draftNotification({
        crew_id: option.crew_id!,
        pairing_id: result?.pairing_id ?? form.pairing_id,
        cost_inr: option.cost_inr,
      }),
    onSuccess: (data) => setNotification(data.body),
  })

  const candidateSet = result?.options
    ? {
        role: result.role ?? '',
        pairing_id: result.pairing_id ?? form.pairing_id,
        cover_dates: result.cover_dates ?? [],
        evaluated_count: result.evaluated_count ?? 0,
        eligible_count: result.eligible_count ?? 0,
        excluded_count: result.excluded_count ?? 0,
        exclusion_summary: result.exclusion_summary ?? {},
        options: result.options ?? [],
        excluded_candidates: result.excluded_candidates ?? [],
      }
    : null

  return (
    <div className="p-4 grid gap-4 xl:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
      {/* ---- Event builder ---- */}
      <div className="space-y-4">
        <Panel title="Disruption" subtitle="Every run forks the world; the snapshot is never edited" bodyClassName="p-3 space-y-3">
          <div className="grid grid-cols-2 gap-1.5">
            {KINDS.map((k) => (
              <button
                key={k.value}
                onClick={() => setKind(k.value)}
                title={k.hint}
                className={
                  kind === k.value
                    ? 'btn-primary justify-start'
                    : 'btn-ghost justify-start'
                }
              >
                {k.label}
              </button>
            ))}
          </div>

          <div className="space-y-2">
            {(kind === 'sick' || kind === 'cert' || kind === 'multi_sick') && (
              <>
                <EntityPicker kind="crew" label="Crew" value={form.crew_id} onChange={setValue('crew_id')} />
                <EntityPicker
                  kind="pairing"
                  label="Pairing"
                  value={form.pairing_id}
                  onChange={setValue('pairing_id')}
                  crewId={form.crew_id}
                />
                {kind === 'multi_sick' && (
                  <>
                    <EntityPicker
                      kind="crew"
                      label="Second crew"
                      value={form.crew_id_2}
                      onChange={setValue('crew_id_2')}
                    />
                    <EntityPicker
                      kind="pairing"
                      label="Second pairing"
                      value={form.pairing_id_2}
                      onChange={setValue('pairing_id_2')}
                      crewId={form.crew_id_2}
                    />
                  </>
                )}
                <Field label="Reported (UTC)" value={form.reported_utc} onChange={set('reported_utc')} />
              </>
            )}
            {kind === 'closure' && (
              <>
                <EntityPicker kind="station" label="Station" value={form.station} onChange={setValue('station')} />
                <Field label="Closes (UTC)" value={form.start_utc} onChange={set('start_utc')} />
                <Field label="Reopens (UTC)" value={form.end_utc} onChange={set('end_utc')} />
              </>
            )}
            {kind === 'delay' && (
              <>
                <EntityPicker
                  kind="aircraft"
                  label="Aircraft"
                  value={form.aircraft}
                  onChange={setValue('aircraft')}
                />
                <Field label="Date" value={form.date} onChange={set('date')} />
                <Field label="Delay (hours)" value={form.delay_hours} onChange={set('delay_hours')} />
              </>
            )}
            {kind === 'cancellation' && (
              <Field label="Flight ids (comma separated)" value={form.flight_ids} onChange={set('flight_ids')} />
            )}
          </div>

          <button className="btn-primary w-full" onClick={() => run.mutate()} disabled={run.isPending}>
            <Play size={12} /> Run simulation
          </button>
          {run.isPending && <Spinner />}
          {run.error && <ErrorBox error={run.error} />}
        </Panel>

        <Panel title="Worked scenarios" subtitle="The six shipped cases, plus the held-out pair" bodyClassName="p-2">
          <ul className="space-y-1">
            {(scenarios.data?.scenarios ?? []).map((s: any) => (
              <li key={s.scenario_id}>
                <button
                  onClick={() => replay.mutate(s.scenario_id)}
                  className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-ink-850 transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="chip-neutral">{s.scenario_id}</span>
                    <span className="text-2xs text-mute-200 truncate">{s.title}</span>
                  </div>
                  {s.narrative && (
                    <p className="text-2xs text-mute-400 mt-1 leading-snug line-clamp-2">{s.narrative}</p>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      {/* ---- Result ---- */}
      <div className="space-y-4 min-w-0">
        {!result && (
          <Panel bodyClassName="p-0">
            <EmptyState
              icon={GitBranch}
              title="No simulation yet"
              body="Pick a disruption and run it, or replay one of the worked scenarios. The impact, the ranked options and every rejected candidate appear here."
            />
          </Panel>
        )}

        {result && (
          <>
            {result.lineage?.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap text-2xs text-mute-400">
                <GitBranch size={11} aria-hidden />
                {result.lineage.map((e: any, i: number) => (
                  <span key={i} className="chip-neutral">
                    {e.type}
                    {e.crew_id ? ` · ${e.crew_id}` : ''}
                    {e.station ? ` · ${e.station}` : ''}
                  </span>
                ))}
                {result.run_id && (
                  <Link to={`/runs/${result.run_id}`} className="btn-ghost ml-auto">
                    <FileSearch size={11} /> Trace
                  </Link>
                )}
              </div>
            )}

            {result.impact && (
              <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
                <StatTile label="Uncrewed legs" value={result.impact.uncovered_flights_day1?.length ?? 0} tone="breach" />
                <StatTile label="At risk next day" value={result.impact.uncovered_flights_day2?.length ?? 0} tone="caution" />
                <StatTile label="Passengers (day 1)" value={result.impact.passengers_at_risk_day1 ?? 0} />
                <StatTile
                  label="Cheapest legal cover"
                  value={result.options?.find((o: any) => o.crew_id) ? inr(result.options.find((o: any) => o.crew_id).cost_inr) : '—'}
                  tone="legal"
                />
              </div>
            )}

            {result.impact && (
              <Panel title="Impact" subtitle="What breaks now, and what breaks next">
                <AnswerBody structured={{ schema: 'impact', headline: '', primary: result.impact }} />
              </Panel>
            )}

            {candidateSet && (
              <Panel
                title="Resolution options"
                subtitle={`${candidateSet.evaluated_count} candidates evaluated · ${candidateSet.eligible_count} legal · ${candidateSet.excluded_count} excluded`}
                actions={applied ? <span className="chip-legal">Applied · {applied}</span> : undefined}
              >
                <CandidateSetView
                  data={candidateSet}
                  onApply={(o) => apply.mutate(o)}
                  onNotify={(o) => draft.mutate(o)}
                />
              </Panel>
            )}

            {result.optimal_joint_plan && (
              <Panel title="Optimal joint plan" subtitle="Minimum total cost, no crew member assigned twice">
                <AnswerBody
                  structured={{
                    schema: 'joint_recommendation',
                    headline: '',
                    primary: result.optimal_joint_plan,
                    openings: result.openings,
                  }}
                />
              </Panel>
            )}

            {result.per_flight_assessment && (
              <Panel title="Station closure impact">
                <AnswerBody structured={{ schema: 'closure', headline: '', primary: result }} />
              </Panel>
            )}

            {result.fdp_after_delay !== undefined && (
              <Panel title="Delay impact">
                <AnswerBody structured={{ schema: 'delay', headline: '', primary: result }} />
              </Panel>
            )}

            {result.passengers_affected !== undefined && !result.impact && (
              <Panel title="Cancellation impact">
                <div className="grid gap-3 grid-cols-2 sm:grid-cols-3">
                  <StatTile label="Passengers" value={result.passengers_affected} tone="breach" />
                  <StatTile label="Direct cost" value={inr(result.direct_cost_inr)} />
                  <StatTile label="Rotation breaks" value={result.rotation_breaks?.length ?? 0} tone="caution" />
                </div>
              </Panel>
            )}

            {notification && (
              <Panel title="Callout draft" actions={<span className="chip-neutral"><Send size={10} /> draft</span>}>
                <pre className="text-xs text-mute-200 whitespace-pre-wrap font-mono leading-relaxed">
                  {notification}
                </pre>
              </Panel>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <input className="input w-full mt-1 py-1.5 text-xs num" value={value} onChange={onChange} />
    </label>
  )
}
