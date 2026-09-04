import { useQuery } from '@tanstack/react-query'
import { AnswerBody } from '../components/AnswerCard'
import { ErrorBox, Panel, Skeleton, StatTile } from '../components/ui'
import { api } from '../lib/api'

/**
 * The standing morning briefing.
 *
 * Three data points per aircraft line, each answering a different question a
 * controller asks at 06:00: can today's crew absorb a slip, who could take an
 * opening, and who is most likely to create one.
 */
export default function BriefingPage() {
  const clock = useQuery({ queryKey: ['clock'], queryFn: api.clock })
  const briefing = useQuery({
    queryKey: ['briefing', clock.data?.date],
    queryFn: () => api.briefing(clock.data?.date),
    enabled: Boolean(clock.data?.date),
  })

  const head = briefing.data?.headline

  return (
    <div className="p-4 space-y-4 max-w-[1100px] mx-auto">
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
        <StatTile label="Date" value={briefing.data?.date ?? '—'} hint="simulated operation day" />
        <StatTile label="Aircraft lines" value={briefing.data?.line_count ?? '—'} />
        <StatTile
          label="Thin FDP margin"
          value={head?.fragile_fdp_lines?.length ?? 0}
          tone={head?.fragile_fdp_lines?.length ? 'caution' : 'legal'}
          hint={head?.fragile_fdp_lines?.join(', ') || 'every line has slack'}
        />
        <StatTile
          label="Reserve gaps"
          value={head?.thin_reserve_lines?.length ?? 0}
          tone={head?.thin_reserve_lines?.length ? 'breach' : 'legal'}
          hint={head?.thin_reserve_lines?.join(', ') || 'all roles coverable'}
        />
      </div>

      <Panel title="Morning briefing" subtitle="Duty headroom · reserve depth · disruption risk, per line">
        {briefing.isLoading && <Skeleton rows={6} />}
        {briefing.error && <ErrorBox error={briefing.error} />}
        {briefing.data && (
          <AnswerBody structured={{ schema: 'briefing', headline: '', primary: briefing.data }} />
        )}
      </Panel>
    </div>
  )
}
