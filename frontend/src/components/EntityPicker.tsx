import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { AircraftProfileBody, PairingProfileBody, StationProfileBody } from './EntityProfiles'
import { CrewProfileBody } from './CrewProfile'
import { Modal } from './Modal'
import { Tip } from './ui'

export type EntityKind = 'crew' | 'pairing' | 'aircraft' | 'station'

const LABEL: Record<EntityKind, string> = {
  crew: 'crew member',
  pairing: 'pairing',
  aircraft: 'aircraft',
  station: 'station',
}

function useOptions(
  kind: EntityKind,
  crewId?: string,
): { options: { value: string; label: string }[]; isLoading: boolean } {
  const crew = useQuery({
    queryKey: ['picker-crew'],
    queryFn: () => api.crew(),
    enabled: kind === 'crew',
  })
  const pairings = useQuery({
    queryKey: ['picker-pairings', crewId ?? null],
    queryFn: () => api.pairings(crewId ? { crew_id: crewId } : {}),
    enabled: kind === 'pairing' && crewId !== '',
  })
  const snapshot = useQuery({
    queryKey: ['snapshot'],
    queryFn: api.snapshot,
    enabled: kind === 'aircraft' || kind === 'station',
  })

  const options = useMemo(() => {
    if (kind === 'crew') {
      return (crew.data?.crew ?? [])
        .slice()
        .sort((a: any, b: any) => a.crew_id.localeCompare(b.crew_id))
        .map((c: any) => ({
          value: c.crew_id,
          label: `${c.crew_id} — ${c.name} (${c.rank}, ${c.base}${c.status !== 'active' ? `, ${c.status}` : ''})`,
        }))
    }
    if (kind === 'pairing') {
      return (pairings.data?.pairings ?? [])
        .slice()
        .sort((a: any, b: any) => a.pairing_id.localeCompare(b.pairing_id))
        .map((p: any) => ({
          value: p.pairing_id,
          label: `${p.pairing_id} — ${p.aircraft}, starts ${p.start_date} (${p.total_sectors} sectors)`,
        }))
    }
    if (kind === 'aircraft') {
      return (snapshot.data?.aircraft ?? []).map((a: string) => ({ value: a, label: a }))
    }
    if (kind === 'station') {
      return (snapshot.data?.stations ?? []).map((s: string) => ({ value: s, label: s }))
    }
    return []
  }, [kind, crew.data, pairings.data, snapshot.data])

  const isLoading =
    kind === 'crew'
      ? crew.isLoading
      : kind === 'pairing'
        ? pairings.isLoading
        : snapshot.isLoading

  return { options, isLoading }
}

/**
 * A dropdown for picking a crew/pairing/aircraft/station id, with an "open
 * profile" icon next to it. Selecting from real data means the value is
 * always a real id — no more guessing whether "C-1042" is spelled right —
 * and the icon opens that exact entity's profile in a modal, schedule
 * included, without leaving the form.
 */
export function EntityPicker({
  kind,
  value,
  onChange,
  label,
  placeholder = 'Select…',
  crewId,
}: {
  kind: EntityKind
  value: string
  onChange: (value: string) => void
  label: string
  placeholder?: string
  /** When set on a pairing picker, only that crew member's pairings are listed. */
  crewId?: string
}) {
  const { options, isLoading } = useOptions(kind, crewId)
  const [open, setOpen] = useState(false)
  const hasValue = Boolean(value && options.some((o) => o.value === value))
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  useEffect(() => {
    if (kind !== 'pairing' || crewId === undefined) return
    if (isLoading) return
    if (options.some((o) => o.value === value)) return
    const next = options[0]?.value ?? ''
    if (next !== value) onChangeRef.current(next)
  }, [kind, crewId, isLoading, options, value])

  return (
    <label className="block">
      <span className="label">{label}</span>
      <div className="flex items-stretch gap-1.5 mt-1">
        <select
          className="input flex-1 py-1.5 text-xs num min-w-0"
          value={hasValue ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="" disabled>
            {kind === 'pairing' && crewId && !isLoading && options.length === 0
              ? 'No pairings for this crew'
              : placeholder}
          </option>
          {/* If the current value isn't in the loaded list yet (still fetching,
              or a value seeded from elsewhere), keep it selectable rather than
              silently discarding it. */}
          {value && !hasValue && (
            <option value={value}>{value}</option>
          )}
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <Tip text={value ? `Open ${LABEL[kind]} profile` : `Select a ${LABEL[kind]} first`}>
          <button
            type="button"
            className="btn-ghost px-2 shrink-0"
            disabled={!value}
            onClick={() => setOpen(true)}
            aria-label={`Open ${LABEL[kind]} profile`}
          >
            <ExternalLink size={13} />
          </button>
        </Tip>
      </div>

      {open && value && (
        <Modal
          title={`${kind === 'aircraft' ? 'Aircraft' : kind === 'station' ? 'Station' : kind === 'pairing' ? 'Pairing' : 'Crew'} · ${value}`}
          subtitle={options.find((o) => o.value === value)?.label}
          onClose={() => setOpen(false)}
          width={kind === 'pairing' ? 880 : 760}
        >
          {kind === 'crew' && <CrewProfileBody crewId={value} />}
          {kind === 'pairing' && <PairingProfileBody pairingId={value} />}
          {kind === 'aircraft' && <AircraftProfileBody aircraft={value} />}
          {kind === 'station' && <StationProfileBody station={value} />}
        </Modal>
      )}
    </label>
  )
}
