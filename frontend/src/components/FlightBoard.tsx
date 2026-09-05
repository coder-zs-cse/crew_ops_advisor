import { useQuery } from '@tanstack/react-query'
import { Plane, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api, utcTime } from '../lib/api'
import { FlightProfileBody } from './EntityProfiles'
import { Modal } from './Modal'
import { EmptyState, ErrorBox, Skeleton } from './ui'

type FlightRow = {
  flight_id: string
  flight_no: string
  date: string
  dep_station: string
  arr_station: string
  dep_utc: string
  arr_utc: string
  block_hours: number
  aircraft: string
  aircraft_type: string
  seats: number
  pairing_id?: string | null
}

/**
 * Published schedule as a searchable table. Click a row to open the same
 * style of profile modal used for crew — times, pairing, complement — and
 * from there a crew chip starts a workbench disruption already filled in.
 */
export function FlightBoard() {
  const flights = useQuery({ queryKey: ['flights'], queryFn: () => api.flights() })
  const [search, setSearch] = useState('')
  const [date, setDate] = useState('all')
  const [aircraft, setAircraft] = useState('all')
  const [from, setFrom] = useState('all')
  const [to, setTo] = useState('all')
  const [selected, setSelected] = useState<FlightRow | null>(null)

  const rows: FlightRow[] = flights.data?.flights ?? []

  const options = useMemo(() => {
    const dates = new Set<string>()
    const tails = new Set<string>()
    const deps = new Set<string>()
    const arrs = new Set<string>()
    for (const f of rows) {
      dates.add(f.date)
      tails.add(f.aircraft)
      deps.add(f.dep_station)
      arrs.add(f.arr_station)
    }
    const sort = (a: string, b: string) => a.localeCompare(b)
    return {
      dates: [...dates].sort(),
      aircraft: [...tails].sort(sort),
      from: [...deps].sort(sort),
      to: [...arrs].sort(sort),
    }
  }, [rows])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((f) => {
      if (date !== 'all' && f.date !== date) return false
      if (aircraft !== 'all' && f.aircraft !== aircraft) return false
      if (from !== 'all' && f.dep_station !== from) return false
      if (to !== 'all' && f.arr_station !== to) return false
      if (!q) return true
      const hay = [
        f.flight_no,
        f.flight_id,
        f.aircraft,
        f.dep_station,
        f.arr_station,
        `${f.dep_station}-${f.arr_station}`,
        f.pairing_id ?? '',
      ]
        .join(' ')
        .toLowerCase()
      return hay.includes(q)
    })
  }, [rows, search, date, aircraft, from, to])

  if (flights.isLoading) return <Skeleton rows={8} />
  if (flights.error) return <ErrorBox error={flights.error} />

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <label className="relative flex-1 min-w-[160px]">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-mute-400" aria-hidden />
          <input
            className="input w-full py-1.5 pl-7 text-xs"
            placeholder="Search flight, tail, route, pairing…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <FilterSelect label="Date" allLabel="All dates" value={date} onChange={setDate} options={options.dates} />
        <FilterSelect
          label="Aircraft"
          allLabel="All aircraft"
          value={aircraft}
          onChange={setAircraft}
          options={options.aircraft}
        />
        <FilterSelect label="From" allLabel="All origins" value={from} onChange={setFrom} options={options.from} />
        <FilterSelect label="To" allLabel="All destinations" value={to} onChange={setTo} options={options.to} />
      </div>

      <p className="text-2xs text-mute-400">
        {visible.length} of {rows.length} flights
      </p>

      {visible.length === 0 ? (
        <EmptyState
          icon={Plane}
          title="No flights match"
          body="Clear the search or reset a filter. The list is the published week, not a forecast."
        />
      ) : (
        <div className="xscroll max-h-[calc(100vh-22rem)] overflow-y-auto rounded-lg border border-ink-800">
          <table className="w-full min-w-[640px] border-collapse">
            <thead>
              <tr>
                <th className="th w-24">Date</th>
                <th className="th w-20">Flight</th>
                <th className="th">Route</th>
                <th className="th w-16">Dep</th>
                <th className="th w-16">Arr</th>
                <th className="th w-20">Aircraft</th>
                <th className="th w-20">Pairing</th>
                <th className="th w-14 text-right">Seats</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((f) => (
                <tr
                  key={f.flight_id}
                  className="tr cursor-pointer"
                  onClick={() => setSelected(f)}
                >
                  <td className="cell num text-mute-300">{f.date.slice(5)}</td>
                  <td className="cell num text-mute-200">{f.flight_no}</td>
                  <td className="cell num text-mute-300">
                    {f.dep_station}–{f.arr_station}
                  </td>
                  <td className="cell num text-mute-400">{utcTime(f.dep_utc)}</td>
                  <td className="cell num text-mute-400">{utcTime(f.arr_utc)}</td>
                  <td className="cell num text-mute-300">{f.aircraft}</td>
                  <td className="cell num text-mute-400">{f.pairing_id ?? '—'}</td>
                  <td className="cell num text-right text-mute-400">{f.seats}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <Modal
          title={`Flight · ${selected.flight_no}`}
          subtitle={`${selected.flight_id} · ${selected.dep_station}–${selected.arr_station} · ${selected.date}`}
          onClose={() => setSelected(null)}
          width={760}
        >
          <FlightProfileBody flightId={selected.flight_id} />
        </Modal>
      )}
    </div>
  )
}

function FilterSelect({
  label,
  allLabel,
  value,
  onChange,
  options,
}: {
  label: string
  allLabel: string
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  return (
    <label className="shrink-0">
      <span className="sr-only">{label}</span>
      <select
        className="input py-1.5 text-xs num"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
      >
        <option value="all">{allLabel}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  )
}
