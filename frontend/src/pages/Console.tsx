import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Bell, BellOff, Check, RefreshCw, ShieldCheck } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TailGantt } from '../components/Gantt'
import { EmptyState, ErrorBox, Panel, Skeleton, StatTile, Toggle } from '../components/ui'
import { CoverageRing } from '../components/viz'
import { api, type Alert } from '../lib/api'
import { severityColor } from '../lib/viz'

const SWEEP_INTERVAL_MS = 5 * 60 * 1000
const TTS_STORAGE_KEY   = 'console_tts_enabled'
const ANNOUNCED_IDS_KEY = 'console_announced_ids'
const TTS_ENDPOINT      = '/api/tts'

let _currentAudio: HTMLAudioElement | null = null

function stopCurrentAudio(): void {
  if (_currentAudio) { _currentAudio.pause(); _currentAudio.src = ''; _currentAudio = null }
}

async function speakViaSarvam(text: string): Promise<void> {
  try {
    const res = await fetch(TTS_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, speaker: 'ritu', pace: 1.0 }),
    })
    if (!res.ok) { console.warn(`[TTS] ${res.status} — skipping`); return }
    const url = URL.createObjectURL(await res.blob())
    await new Promise<void>((resolve) => {
      const audio = new Audio(url)
      _currentAudio = audio
      audio.onended = () => { URL.revokeObjectURL(url); _currentAudio = null; resolve() }
      audio.onerror = () => { URL.revokeObjectURL(url); _currentAudio = null; resolve() }
      audio.play().catch(() => resolve())
    })
  } catch (err) {
    console.warn('[TTS] fetch failed:', err)
  }
}

// Announce ONLY the single most critical novel alert — nothing else
async function announceTopAlert(alerts: Alert[]): Promise<void> {
  const rank: Record<string, number> = { critical: 0, warning: 1, info: 2 }
  const top = [...alerts].sort((a, b) => (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3))[0]
  if (!top) return
  const prefix =
    top.severity === 'critical' ? 'Critical alert.' :
    top.severity === 'warning'  ? 'Warning.' : 'Info.'
  await speakViaSarvam(`${prefix} ${top.title}`)
}

function loadAnnouncedIds(): Set<string> {
  try {
    const raw = localStorage.getItem(ANNOUNCED_IDS_KEY)
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set()
  } catch { return new Set() }
}

function saveAnnouncedIds(ids: Set<string>): void {
  try {
    localStorage.setItem(ANNOUNCED_IDS_KEY, JSON.stringify([...ids].slice(-500)))
  } catch { /* storage full */ }
}

export default function ConsolePage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [severity, setSeverity]               = useState<string>('all')
  const [selectedPairing, setSelectedPairing] = useState<string | null>(null)

  const [ttsEnabled, setTtsEnabled] = useState<boolean>(
    () => localStorage.getItem(TTS_STORAGE_KEY) === 'true',
  )
  const ttsEnabledRef = useRef(ttsEnabled)

  // Seeded from localStorage — survives tab switches, never re-announces known IDs
  const announcedIds = useRef<Set<string>>(loadAnnouncedIds())

  const alerts   = useQuery({ queryKey: ['alerts'],   queryFn: () => api.alerts('open'), refetchInterval: SWEEP_INTERVAL_MS })
  const snapshot = useQuery({ queryKey: ['snapshot'], queryFn: api.snapshot })
  const gantt    = useQuery({ queryKey: ['gantt'],    queryFn: () => api.gantt() })
  const clock    = useQuery({ queryKey: ['clock'],    queryFn: api.clock })
  const reserves = useQuery({
    queryKey: ['reserves', clock.data?.date],
    queryFn:  () => api.reserves({ on: clock.data?.date }),
    enabled:  Boolean(clock.data?.date),
  })
  const risk = useQuery({ queryKey: ['risk'], queryFn: () => api.risk(5) })

  // Only speak genuinely NEW alerts after TTS is armed — one alert at a time, top severity first
  useEffect(() => {
    const incoming = alerts.data?.alerts ?? []
    if (!ttsEnabledRef.current || incoming.length === 0) return
    const novel = incoming.filter((a) => !announcedIds.current.has(a.id))
    if (novel.length === 0) return
    novel.forEach((a) => announcedIds.current.add(a.id))
    saveAnnouncedIds(announcedIds.current)
    announceTopAlert(novel)
  }, [alerts.data])

  const toggleTts = useCallback(() => {
    setTtsEnabled((prev) => {
      const next = !prev
      ttsEnabledRef.current = next
      localStorage.setItem(TTS_STORAGE_KEY, String(next))
      stopCurrentAudio()

      if (next) {
        // Arm silently — mark everything currently open as already announced
        // No voice message — just start watching for new alerts from this point
        const current = alerts.data?.alerts ?? []
        current.forEach((a) => announcedIds.current.add(a.id))
        saveAnnouncedIds(announcedIds.current)
      }

      return next
    })
  }, [alerts.data])

  const sweep = useMutation({
    mutationFn: api.sweepAlerts,
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const ack = useMutation({
    mutationFn: (id: string) => api.ackAlert(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const filtered = useMemo(() => {
    const rows = alerts.data?.alerts ?? []
    return severity === 'all' ? rows : rows.filter((a) => a.severity === severity)
  }, [alerts.data, severity])

  const counts = alerts.data?.open_by_severity ?? { critical: 0, warning: 0, info: 0 }

  const coverage = useMemo(() => {
    const rows  = gantt.data?.rows ?? []
    const today = clock.data?.date
    if (!today) return { pct: 100, total: 0 }
    const dayPairings = rows.flatMap((r) => r.pairings.filter((p) => p.date === today))
    if (dayPairings.length === 0) return { pct: 100, total: 0 }
    const crewed = dayPairings.filter((p) => p.crew.length >= 6).length
    return { pct: (crewed / dayPairings.length) * 100, total: dayPairings.length }
  }, [gantt.data, clock.data])

  const breachPairings = useMemo(
    () =>
      new Set(
        (alerts.data?.alerts ?? [])
          .filter((a) => a.severity === 'critical' && a.payload?.pairing_id)
          .map((a) => String(a.payload.pairing_id)),
      ),
    [alerts.data],
  )

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
          <div className="flex items-center gap-1.5">
            <button
              className={`btn-ghost ${ttsEnabled ? 'text-signal' : ''}`}
              onClick={toggleTts}
              title={ttsEnabled ? 'Announcements on — click to mute' : 'Announcements off — click to enable'}
            >
              {ttsEnabled
                ? <Bell size={11} className="text-signal" />
                : <BellOff size={11} />}
              {ttsEnabled ? 'Mute' : 'Announce'}
            </button>
            <button
              className="btn-ghost"
              onClick={() => sweep.mutate()}
              disabled={sweep.isPending}
              title="Re-run every watcher against the current simulated time"
            >
              <RefreshCw size={11} className={sweep.isPending ? 'animate-spin' : ''} /> Sweep
            </button>
          </div>
        }
        bodyClassName="p-3 space-y-2 overflow-y-auto max-h-[calc(100vh-9rem)]"
      >
        <Toggle
          value={severity}
          onChange={setSeverity}
          options={[
            { value: 'all',      label: 'All' },
            { value: 'critical', label: `Critical ${counts.critical}` },
            { value: 'warning',  label: `Warning ${counts.warning}` },
            { value: 'info',     label: `Info ${counts.info}` },
          ]}
        />

        {alerts.isLoading && <Skeleton rows={4} />}
        {alerts.error    && <ErrorBox error={alerts.error} />}
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
              navigate('/advisor', {
                state: { question: a.suggested_question ?? a.title, newConversation: true },
              })
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
          <StatTile
            label="Active crew"
            value={snapshot.data?.counts.crew ?? '—'}
            hint="rank, base, ratings on file"
          />
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
          title="Aircraft lines"
          subtitle="Report to release, per tail, per day. Click a duty to open its pairing."
          bodyClassName="p-3"
        >
          {gantt.isLoading && <Skeleton rows={6} />}
          {gantt.data && (
            <TailGantt
              rows={gantt.data.rows}
              dates={gantt.data.dates}
              breachPairings={breachPairings}
              selectedPairing={selectedPairing}
              onSelectPairing={(id) => {
                setSelectedPairing(id)
                navigate('/workbench', { state: { pairingId: id } })
              }}
            />
          )}
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

        <Panel
          title="Highest disruption risk"
          subtitle="Provided signal — not modelled here"
          bodyClassName="p-3"
        >
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