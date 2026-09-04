import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, utcTime } from '../lib/api'
import { ErrorBox, Panel, Skeleton } from './ui'

/** A pairing's full shape: days, legs, complement — the same read the Gantt links to. */
export function PairingProfileBody({ pairingId }: { pairingId: string }) {
  const detail = useQuery({ queryKey: ['pairing', pairingId], queryFn: () => api.pairing(pairingId) })

  if (detail.isLoading) return <Skeleton rows={6} />
  if (detail.error) return <ErrorBox error={detail.error} />
  const p = detail.data
  if (!p) return null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="chip-neutral">{p.aircraft}</span>
        <span className="chip-neutral">{p.aircraft_type}</span>
        <span className="chip-signal">{p.total_sectors} sectors</span>
        <span className="chip-neutral">{p.days?.length ?? 0}-day pairing</span>
      </div>

      <Panel title="Crew complement" bodyClassName="p-3">
        <div className="flex flex-wrap gap-2">
          {(p.crew ?? []).map((c: any) => (
            <Link
              key={c.crew_id}
              to={`/crew/${c.crew_id}`}
              className="chip-neutral hover:text-signal hover:border-signal/40 transition-colors"
              title={c.name}
            >
              {c.role} · {c.crew_id}
            </Link>
          ))}
        </div>
      </Panel>

      {(p.days ?? []).map((day: any) => (
        <Panel
          key={day.date}
          title={`Day ${day.day_index + 1} · ${day.date}`}
          subtitle={`${utcTime(day.report_utc)} → ${utcTime(day.release_utc)} · ${day.duty_hours}h duty · ${day.sectors} sectors · ${day.seats} seats`}
          bodyClassName="p-0"
        >
          <div className="xscroll">
            <table className="w-full min-w-[520px] border-collapse">
              <thead>
                <tr>
                  <th className="th w-24">Flight</th>
                  <th className="th">Route</th>
                  <th className="th w-24">Dep</th>
                  <th className="th w-24">Arr</th>
                  <th className="th w-20 text-right">Block</th>
                  <th className="th w-16 text-right">Seats</th>
                </tr>
              </thead>
              <tbody>
                {(day.flights ?? []).map((f: any) => (
                  <tr key={f.flight_id} className="tr">
                    <td className="cell num text-mute-200">{f.flight_no}</td>
                    <td className="cell num text-mute-300">
                      {f.dep_station}–{f.arr_station}
                    </td>
                    <td className="cell num text-mute-400">{utcTime(f.dep_utc)}</td>
                    <td className="cell num text-mute-400">{utcTime(f.arr_utc)}</td>
                    <td className="cell num text-right text-mute-300">{f.block_hours}h</td>
                    <td className="cell num text-right text-mute-400">{f.seats}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ))}
    </div>
  )
}

/** An aircraft's week: every pairing it flies, seats, and the seat class it is. */
export function AircraftProfileBody({ aircraft }: { aircraft: string }) {
  const flights = useQuery({
    queryKey: ['aircraft-flights', aircraft],
    queryFn: () => api.flights({ aircraft }),
  })
  const pairings = useQuery({
    queryKey: ['aircraft-pairings', aircraft],
    queryFn: () => api.pairings({ aircraft }),
  })

  if (flights.isLoading || pairings.isLoading) return <Skeleton rows={6} />
  if (flights.error) return <ErrorBox error={flights.error} />

  const sample = flights.data?.flights?.[0]
  const rows = pairings.data?.pairings ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        {sample && <span className="chip-neutral">{sample.aircraft_type}</span>}
        {sample && <span className="chip-signal">{sample.seats} seats</span>}
        <span className="chip-neutral">{flights.data?.count ?? 0} legs this week</span>
        <span className="chip-neutral">{rows.length} pairings</span>
      </div>

      <Panel title="Pairings this week" bodyClassName="p-0">
        <div className="xscroll">
          <table className="w-full min-w-[480px] border-collapse">
            <thead>
              <tr>
                <th className="th w-28">Start date</th>
                <th className="th w-24">Pairing</th>
                <th className="th w-16 text-right">Days</th>
                <th className="th w-20 text-right">Sectors</th>
                <th className="th w-16 text-right">Crew</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p: any) => (
                <tr key={p.pairing_id} className="tr">
                  <td className="cell num text-mute-300">{p.start_date}</td>
                  <td className="cell num text-mute-200">{p.pairing_id}</td>
                  <td className="cell num text-right text-mute-400">{p.days}</td>
                  <td className="cell num text-right text-mute-400">{p.total_sectors}</td>
                  <td className="cell num text-right text-mute-400">{p.crew_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="All legs this week" bodyClassName="p-0">
        <div className="xscroll max-h-72 overflow-y-auto">
          <table className="w-full min-w-[520px] border-collapse">
            <thead>
              <tr>
                <th className="th w-24">Date</th>
                <th className="th w-20">Flight</th>
                <th className="th">Route</th>
                <th className="th w-20">Dep</th>
              </tr>
            </thead>
            <tbody>
              {(flights.data?.flights ?? []).map((f: any) => (
                <tr key={f.flight_id} className="tr">
                  <td className="cell num text-mute-300">{f.date}</td>
                  <td className="cell num text-mute-200">{f.flight_no}</td>
                  <td className="cell num text-mute-400">
                    {f.dep_station}–{f.arr_station}
                  </td>
                  <td className="cell num text-mute-400">{utcTime(f.dep_utc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

/** A station's picture for the clock's current date: reserves and departures. */
export function StationProfileBody({ station }: { station: string }) {
  const snapshot = useQuery({ queryKey: ['snapshot'], queryFn: api.snapshot })
  const on = snapshot.data?.clock.date
  const reserves = useQuery({
    queryKey: ['station-reserves', station, on],
    queryFn: () => api.reserves({ on, base: station }),
    enabled: Boolean(on),
  })
  const departures = useQuery({
    queryKey: ['station-departures', station, on],
    queryFn: () => api.flights({ dep_station: station, date: on }),
    enabled: Boolean(on),
  })

  if (reserves.isLoading || departures.isLoading || !on) return <Skeleton rows={6} />
  if (reserves.error) return <ErrorBox error={reserves.error} />

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="chip-neutral">on {on}</span>
        <span className="chip-signal">{reserves.data?.count ?? 0} reserves on call</span>
        <span className="chip-neutral">{departures.data?.count ?? 0} departures</span>
      </div>

      <Panel title="Reserves on call" subtitle="Filtered to this station, today's simulated date" bodyClassName="p-0">
        <div className="xscroll">
          <table className="w-full min-w-[460px] border-collapse">
            <thead>
              <tr>
                <th className="th w-24">Crew</th>
                <th className="th w-32">Rank</th>
                <th className="th w-28">Window</th>
                <th className="th">Ratings</th>
              </tr>
            </thead>
            <tbody>
              {(reserves.data?.reserves ?? []).map((r: any) => (
                <tr key={r.crew_id} className="tr">
                  <td className="cell num text-mute-200">
                    <Link to={`/crew/${r.crew_id}`} className="hover:text-signal">
                      {r.crew_id}
                    </Link>
                  </td>
                  <td className="cell text-mute-300">{r.rank}</td>
                  <td className="cell num text-mute-400">
                    {r.window.start}–{r.window.end}Z
                  </td>
                  <td className="cell text-mute-400">{(r.ratings ?? []).join(', ')}</td>
                </tr>
              ))}
              {reserves.data?.count === 0 && (
                <tr>
                  <td colSpan={4} className="cell text-mute-400">
                    No reserves based here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Departures" bodyClassName="p-0">
        <div className="xscroll max-h-64 overflow-y-auto">
          <table className="w-full min-w-[460px] border-collapse">
            <thead>
              <tr>
                <th className="th w-20">Flight</th>
                <th className="th">To</th>
                <th className="th w-20">Dep</th>
                <th className="th w-20">Aircraft</th>
              </tr>
            </thead>
            <tbody>
              {(departures.data?.flights ?? []).map((f: any) => (
                <tr key={f.flight_id} className="tr">
                  <td className="cell num text-mute-200">{f.flight_no}</td>
                  <td className="cell num text-mute-400">{f.arr_station}</td>
                  <td className="cell num text-mute-400">{utcTime(f.dep_utc)}</td>
                  <td className="cell num text-mute-400">{f.aircraft}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
