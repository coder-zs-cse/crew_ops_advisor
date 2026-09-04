import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Clock, RotateCcw } from 'lucide-react'
import { api } from '../lib/api'
import { Tip } from './ui'

/**
 * Virtual clock control.
 *
 * The dataset is frozen at 2026-09-14T18:00Z. Reading wall-clock time would put
 * "today" two years past the schedule and every watcher would find nothing, so
 * the whole app runs on a movable clock instead of pretending. Advancing it
 * re-runs the watchers, which is how the alert board changes on stage.
 */
export function ClockControl() {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['clock'], queryFn: api.clock, refetchInterval: 60_000 })

  const move = useMutation({
    mutationFn: (body: Parameters<typeof api.setClock>[0]) => api.setClock(body),
    onSuccess: async () => {
      await api.sweepAlerts()
      qc.invalidateQueries()
    },
  })

  const busy = move.isPending

  return (
    <div className="flex items-center gap-1 rounded-lg border border-ink-600 bg-ink-850 px-1.5 py-1">
      <Tip text="Simulated operation time. Moving it re-runs the watchers.">
        <span className="flex items-center gap-1.5 num text-2xs text-mute-300 pr-1">
          <Clock size={11} className="text-mute-400" aria-hidden />
          {data?.now_utc?.slice(0, 16).replace('T', ' ') ?? '—'}Z
        </span>
      </Tip>
      <button
        className="p-1 rounded hover:bg-ink-750 text-mute-400 hover:text-mute-200 disabled:opacity-40"
        onClick={() => move.mutate({ advance_days: -1 })}
        disabled={busy}
        aria-label="Back one day"
      >
        <ChevronLeft size={12} />
      </button>
      <button
        className="p-1 rounded hover:bg-ink-750 text-mute-400 hover:text-mute-200 disabled:opacity-40"
        onClick={() => move.mutate({ advance_days: 1 })}
        disabled={busy}
        aria-label="Forward one day"
      >
        <ChevronRight size={12} />
      </button>
      <button
        className="p-1 rounded hover:bg-ink-750 text-mute-400 hover:text-mute-200 disabled:opacity-40"
        onClick={() => move.mutate({ reset: true })}
        disabled={busy}
        aria-label="Reset to the dataset snapshot"
      >
        <RotateCcw size={11} />
      </button>
    </div>
  )
}
