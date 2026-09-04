import clsx from 'clsx'
import { useMemo } from 'react'
import type { GanttRow } from '../lib/api'
import { minutesOfDay, utcTime } from '../lib/api'
import { CATEGORICAL, STATUS, clamp, pctOfDay } from '../lib/viz'
import { Legend, Tip } from './ui'

/**
 * Tail lines × days.
 *
 * Identity lives on the row label, not in colour, so pairings use one hue and
 * colour is left free to mean *state*: a leg that a closure blocks, a duty
 * whose FDP margin is thin, an opening with no crew. That is the dark-cockpit
 * rule — if nothing is coloured, nothing needs you.
 */
export function TailGantt({
  rows,
  dates,
  highlightFlights,
  breachPairings,
  onSelectPairing,
  selectedPairing,
}: {
  rows: GanttRow[]
  dates: string[]
  highlightFlights?: Set<string>
  breachPairings?: Set<string>
  onSelectPairing?: (pairingId: string) => void
  selectedPairing?: string | null
}) {
  const dayList = useMemo(() => dates.slice(0, 7), [dates])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Legend
          items={[
            { color: CATEGORICAL[0], label: 'Rostered duty' },
            ...(highlightFlights?.size ? [{ color: STATUS.caution, label: 'Affected leg' }] : []),
            ...(breachPairings?.size ? [{ color: STATUS.breach, label: 'Rule breach' }] : []),
          ]}
        />
        <span className="text-2xs text-mute-400">each row spans 00:00–24:00Z per day</span>
      </div>

      <div className="xscroll">
        <div className="min-w-[860px]">
          {/* Date header */}
          <div className="flex gap-1 pl-[68px] mb-1">
            {dayList.map((d) => (
              <div key={d} className="flex-1 text-center">
                <span className="num text-2xs text-mute-400">{d.slice(5)}</span>
              </div>
            ))}
          </div>

          <div className="space-y-1">
            {rows.map((row) => (
              <div key={row.aircraft} className="flex items-center gap-1">
                <div className="w-[64px] shrink-0">
                  <div className="num text-2xs text-mute-200">{row.aircraft}</div>
                  <div className="text-2xs text-mute-400/70">{row.aircraft_type}</div>
                </div>
                {dayList.map((day) => {
                  const dayPairings = row.pairings.filter((p) => p.date === day)
                  return (
                    <div key={day} className="flex-1 relative h-9 rounded bg-ink-850 border border-ink-800">
                      {[6, 12, 18].map((h) => (
                        <div
                          key={h}
                          className="absolute inset-y-0 w-px bg-ink-800"
                          style={{ left: `${(h / 24) * 100}%` }}
                          aria-hidden
                        />
                      ))}
                      {dayPairings.map((p) => {
                        const start = pctOfDay(minutesOfDay(p.report_utc))
                        const end = pctOfDay(minutesOfDay(p.release_utc))
                        const width = Math.max(4, end - start)
                        const isBreach = breachPairings?.has(p.pairing_id)
                        const active = selectedPairing === p.pairing_id
                        return (
                          <Tip
                            key={`${p.pairing_id}-${p.day_index}`}
                            className="absolute top-1 bottom-1"
                            style={{ left: `${clamp(start)}%`, width: `${clamp(width, 2)}%` }}
                            text={`${p.pairing_id} · ${p.sectors} sectors · ${utcTime(p.report_utc)}–${utcTime(
                              p.release_utc,
                            )} · ${p.seats} seats`}
                          >
                            <button
                              onClick={() => onSelectPairing?.(p.pairing_id)}
                              className={clsx(
                                'w-full h-full rounded-[3px] flex items-stretch gap-[1px] px-[1px] overflow-hidden',
                                'transition-all hover:brightness-125',
                                active && 'ring-2 ring-signal',
                              )}
                              style={{ background: isBreach ? STATUS.breach : CATEGORICAL[0] }}
                              aria-label={`${p.pairing_id}, ${p.sectors} sectors`}
                            >
                              {p.legs.map((leg) => (
                                <span
                                  key={leg.flight_id}
                                  className="flex-1 rounded-[1px]"
                                  style={{
                                    background: highlightFlights?.has(leg.flight_id)
                                      ? STATUS.caution
                                      : 'rgba(255,255,255,0.16)',
                                  }}
                                />
                              ))}
                            </button>
                          </Tip>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Impact cascade — sick crew → pairing → legs → next-day legs.
 *
 * "Consequence blindness" is the stated pain point: the broken flight is
 * obvious, the ones that break next are not. This draws the second set as
 * prominently as the first.
 */
export function ImpactCascade({
  crewId,
  role,
  pairingId,
  day1,
  day2,
  seatsDay1,
  seatsTotal,
  flightsDetail,
}: {
  crewId: string
  role: string
  pairingId: string
  day1: string[]
  day2: string[]
  seatsDay1: number
  seatsTotal: number
  flightsDetail?: { flight_id: string; flight_no: string; seats: number; dep_station: string; arr_station: string }[]
}) {
  const byId = new Map((flightsDetail ?? []).map((f) => [f.flight_id, f]))
  const render = (ids: string[], tone: string) =>
    ids.map((id) => {
      const f = byId.get(id)
      return (
        <li
          key={id}
          className="flex items-center gap-2 pl-3 relative"
          style={{ borderLeft: `2px solid ${tone}` }}
        >
          <span className="num text-2xs text-mute-200">{f?.flight_no ?? id}</span>
          {f && (
            <>
              <span className="text-2xs text-mute-400">
                {f.dep_station}–{f.arr_station}
              </span>
              <span className="num text-2xs text-mute-400/70 ml-auto">{f.seats} seats</span>
            </>
          )}
        </li>
      )
    })

  return (
    <figure className="space-y-3">
      <div className="flex items-center gap-2 text-xs">
        <span className="chip-breach">{role} {crewId}</span>
        <span className="text-mute-400" aria-hidden>→</span>
        <span className="chip-neutral">{pairingId}</span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="label" style={{ color: STATUS.breach }}>
              Uncrewed now
            </span>
            <span className="num text-2xs text-mute-300">{seatsDay1} pax</span>
          </div>
          <ul className="space-y-1">{render(day1, STATUS.breach)}</ul>
        </div>

        {day2.length > 0 && (
          <div>
            <div className="flex items-baseline justify-between mb-1.5">
              <span className="label" style={{ color: STATUS.caution }}>
                At risk — pairing continues
              </span>
              <span className="num text-2xs text-mute-300">{seatsTotal - seatsDay1} pax</span>
            </div>
            <ul className="space-y-1">{render(day2, STATUS.caution)}</ul>
          </div>
        )}
      </div>

      <figcaption className="text-2xs text-mute-400 leading-relaxed border-t border-ink-800 pt-2">
        The aircraft overnights away from base, so the opening carries into the next duty day. Cover has
        to take the whole pairing, not just today's legs.
      </figcaption>
    </figure>
  )
}
