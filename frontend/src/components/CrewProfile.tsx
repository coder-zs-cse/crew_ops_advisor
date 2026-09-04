import { useQuery } from '@tanstack/react-query'
import { ErrorBox, Panel, Skeleton, StatTile } from './ui'
import { DutyBudgetBar, DutyHistoryChart } from './viz'
import { api, utcStamp, utcTime } from '../lib/api'

/**
 * A crew member's full profile: identity, duty budget, certifications, 28-day
 * history and published roster. Used both as the standalone /crew/:id page
 * and inside the picker's "open profile" modal — one body, two shells, so the
 * two views can never drift apart.
 */
export function CrewProfileBody({ crewId }: { crewId: string }) {
  const detail = useQuery({ queryKey: ['crew', crewId], queryFn: () => api.crewDetail(crewId) })
  const timeline = useQuery({ queryKey: ['crew-timeline', crewId], queryFn: () => api.crewTimeline(crewId) })
  const clock = timeline.data?.clock

  if (detail.isLoading || timeline.isLoading) return <Skeleton rows={6} />
  if (detail.error) return <ErrorBox error={detail.error} />
  if (!detail.data) return null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="chip-neutral">{detail.data.rank}</span>
        <span className="chip-neutral">{detail.data.base}</span>
        {detail.data.is_reserve && <span className="chip-signal">reserve</span>}
        <span className={detail.data.status === 'active' ? 'chip-legal' : 'chip-caution'}>
          {detail.data.status}
        </span>
      </div>

      <div className="grid gap-3 grid-cols-2 sm:grid-cols-4 lg:grid-cols-6">
        <StatTile label="Name" value={detail.data.name} />
        <StatTile label="Ratings" value={detail.data.ratings.join(', ')} hint="RULE-QUAL-05" />
        <StatTile label="Seniority" value={detail.data.seniority} unit="yrs" />
        <StatTile
          label="Reachability"
          value={detail.data.reachability_minutes}
          unit="min"
          hint="time to the airport from callout"
        />
        <StatTile
          label="7-day duty"
          value={clock?.duty_hours_7d ?? '—'}
          unit="h"
          tone={(clock?.headroom_hours ?? 60) < 10 ? 'caution' : 'legal'}
          hint={`${clock?.headroom_hours ?? '—'}h headroom`}
        />
        <StatTile
          label="Risk score"
          value={detail.data.disruption_risk_score ?? '—'}
          tone={(detail.data.disruption_risk_score ?? 0) > 0.6 ? 'caution' : 'neutral'}
          hint="provided signal"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Duty budget" subtitle="Against both rolling limits">
          <div className="space-y-4">
            {clock && (
              <>
                <DutyBudgetBar
                  used={clock.duty_hours_7d}
                  limit={clock.duty_limit_7d}
                  label={`RULE-DUTY-02 · 7 days to ${clock.as_of}`}
                />
                <DutyBudgetBar
                  used={clock.flight_hours_28d}
                  limit={clock.flight_limit_28d}
                  label={`RULE-FLT-03 · 28 days to ${clock.as_of}`}
                />
                {clock.last_rest_ended && (
                  <p className="text-2xs text-mute-400">
                    Last rest ended {utcStamp(clock.last_rest_ended)} · RULE-REST-04 requires 12h
                    before the next report.
                  </p>
                )}
              </>
            )}
          </div>
        </Panel>

        <Panel title="Certifications" subtitle="RULE-CERT-06 — all must be valid on the duty date">
          <ul className="space-y-1.5">
            {detail.data.certifications.map((c: any) => {
              const expired = c.valid_to < (clock?.as_of ?? '')
              return (
                <li key={c.cert_type} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-mute-300">{c.cert_type.replace(/_/g, ' ')}</span>
                  <span className={expired ? 'chip-breach' : 'chip-legal'}>to {c.valid_to}</span>
                </li>
              )
            })}
          </ul>
          {detail.data.risk_drivers?.length > 0 && (
            <div className="mt-3 border-t border-ink-800 pt-3">
              <p className="label mb-1">Risk drivers</p>
              <ul className="space-y-0.5">
                {detail.data.risk_drivers.map((d: string, i: number) => (
                  <li key={i} className="text-2xs text-mute-400">
                    — {d}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      </div>

      {timeline.data && (
        <Panel title="28-day duty history" subtitle="Recorded history plus the published roster">
          <DutyHistoryChart
            days={timeline.data.duty_28d}
            limit={timeline.data.limits.duty_7d}
            windowDays={7}
            title="Duty hours · rolling 7-day window shaded"
          />
        </Panel>
      )}

      {timeline.data?.roster?.length > 0 && (
        <Panel title="Published roster" bodyClassName="p-0">
          <div className="xscroll">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr>
                  <th className="th w-28">Date</th>
                  <th className="th w-24">Pairing</th>
                  <th className="th w-24">Report</th>
                  <th className="th w-24">Release</th>
                  <th className="th w-24 text-right">Duty</th>
                  <th className="th w-24 text-right">Block</th>
                </tr>
              </thead>
              <tbody>
                {timeline.data.roster.map((d: any) => (
                  <tr key={`${d.date}-${d.pairing_id}`} className="tr">
                    <td className="cell num text-mute-300">{d.date}</td>
                    <td className="cell num text-mute-200">{d.pairing_id}</td>
                    <td className="cell num text-mute-400">{utcTime(d.report_utc)}</td>
                    <td className="cell num text-mute-400">{utcTime(d.release_utc)}</td>
                    <td className="cell num text-right text-mute-300">{d.duty_hours}h</td>
                    <td className="cell num text-right text-mute-400">{d.flight_hours}h</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}
