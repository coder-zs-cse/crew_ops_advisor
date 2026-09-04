import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Panel, Skeleton } from '../components/ui'
import { DutyBudgetBar } from '../components/viz'
import { api, hm } from '../lib/api'

/**
 * The rulebook, with live calculators.
 *
 * Doubles as the source for every citation popover elsewhere: a rule chip in an
 * answer means the same seven-rule set that is printed here.
 */
export default function RulesPage() {
  const rules = useQuery({ queryKey: ['rules'], queryFn: api.rules })
  const costs = useQuery({ queryKey: ['costs'], queryFn: api.costs })

  const [sectors, setSectors] = useState(4)
  const [used, setUsed] = useState(51.83)
  const [added, setAdded] = useState(9.5)
  const [release, setRelease] = useState('2026-09-16T15:30')

  const fdpLimit = 13 - 0.5 * Math.max(0, sectors - 2)
  const total = Math.round((used + added) * 100) / 100
  const earliest = new Date(new Date(`${release}:00Z`).getTime() + 12 * 3600_000)

  return (
    <div className="p-4 space-y-4 max-w-[1100px] mx-auto">
      <Panel title="Legality ruleset" subtitle="The full scope — seven rules, machine-readable">
        {rules.isLoading && <Skeleton rows={7} />}
        <ul className="space-y-2">
          {(rules.data?.rules ?? []).map((r) => (
            <li key={r.rule_id} className="panel p-3">
              <div className="flex items-start justify-between gap-3">
                <span className="chip-signal shrink-0">{r.rule_id}</span>
                <p className="text-xs text-mute-300 flex-1 leading-snug">{r.text}</p>
              </div>
              {Object.keys(r.params ?? {}).length > 0 && (
                <dl className="flex flex-wrap gap-x-4 gap-y-0.5 mt-2 pl-1">
                  {Object.entries(r.params).map(([k, v]) => (
                    <div key={k} className="flex gap-1.5 text-2xs">
                      <dt className="text-mute-400">{k.replace(/_/g, ' ')}</dt>
                      <dd className="num text-mute-200">{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ul>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="RULE-FDP-01" subtitle="Sectors reduce the limit">
          <label className="label">Sectors flown</label>
          <input
            type="range"
            min={1}
            max={8}
            value={sectors}
            onChange={(e) => setSectors(Number(e.target.value))}
            className="w-full accent-signal mt-1"
          />
          <p className="num text-2xl font-semibold text-mute-200 mt-2">{fdpLimit}h</p>
          <p className="text-2xs text-mute-400 font-mono mt-1">
            13.0 − 0.5 × max(0, {sectors} − 2) = {fdpLimit}
          </p>
        </Panel>

        <Panel title="RULE-DUTY-02" subtitle="60h in any 7 calendar days">
          <div className="space-y-2">
            <label className="label">Existing duty in the window</label>
            <input
              className="input w-full py-1 text-xs num"
              value={used}
              onChange={(e) => setUsed(Number(e.target.value) || 0)}
            />
            <label className="label">Proposed additional duty</label>
            <input
              className="input w-full py-1 text-xs num"
              value={added}
              onChange={(e) => setAdded(Number(e.target.value) || 0)}
            />
            <DutyBudgetBar used={used} added={added} limit={60} label="7-day duty" />
            <p className={total > 60 ? 'text-2xs text-breach' : 'text-2xs text-legal'}>
              {total > 60
                ? `Breach — over by ${hm(total - 60)} (total ${total}h)`
                : `Legal — ${Math.round((60 - total) * 100) / 100}h remaining`}
            </p>
          </div>
        </Panel>

        <Panel title="RULE-REST-04" subtitle="12h between release and next report">
          <label className="label">Release (UTC)</label>
          <input
            type="datetime-local"
            className="input w-full py-1 text-xs num mt-1"
            value={release}
            onChange={(e) => setRelease(e.target.value)}
          />
          <p className="num text-lg font-semibold text-mute-200 mt-3">
            {earliest.toISOString().slice(0, 16).replace('T', ' ')}Z
          </p>
          <p className="text-2xs text-mute-400 mt-1">Earliest legal next report.</p>
        </Panel>
      </div>

      <Panel title="Cost rate card" subtitle={costs.data?.currency}>
        <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(costs.data ?? {})
            .filter(([k]) => k !== 'currency')
            .map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2 text-xs border-b border-ink-800/70 py-1">
                <dt className="text-mute-400">{k.replace(/_/g, ' ')}</dt>
                <dd className="num text-mute-200">₹{Number(v).toLocaleString('en-IN')}</dd>
              </div>
            ))}
        </dl>
      </Panel>
    </div>
  )
}
