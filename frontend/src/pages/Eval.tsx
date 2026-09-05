import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronDown, ChevronRight, KeyRound, Play } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ErrorBox, Panel, Pass, Skeleton, StatTile, Toggle, Tip } from '../components/ui'
import { api, type EvalCase, type EvalReport } from '../lib/api'
import { STATUS } from '../lib/viz'

/**
 * The scorecard.
 *
 * Two genuinely different suites, and the difference is the point:
 *
 * "Engine" calls app.core directly -- no agent, no model, no network. It is
 * fast and identical on every run BY CONSTRUCTION, because it never leaves
 * Python. That is a real and useful guarantee, but on its own it can look
 * suspicious: a "correctness scorecard" that always finishes instantly and
 * always says 100% is hard to distinguish from a faked one.
 *
 * "Live Agent" sends each question's own English through the real agent --
 * the exact path /api/chat uses, model included. It takes real time, makes
 * real API calls, and can genuinely fail on routing or verification in ways
 * the engine suite structurally cannot. Requires a configured API key.
 */
export default function EvalPage() {
  const [mode, setMode] = useState<'engine' | 'live'>('engine')
  const [suite, setSuite] = useState('all')
  const [tier, setTier] = useState('all')
  const [onlyFailures, setOnlyFailures] = useState(false)

  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  const llmAvailable = Boolean(capabilities.data?.llm?.available)
  const activeSuite = mode === 'live' ? 'live' : suite

  const latest = useQuery({
    queryKey: ['eval', activeSuite],
    queryFn: () => api.evalLatest(activeSuite),
    retry: false,
  })

  const run = useMutation({
    mutationFn: () => api.evalRun(activeSuite, mode === 'live' ? { concurrency: 6 } : {}),
    onSuccess: (data) => latest.refetch().then(() => data),
  })

  const report: EvalReport | undefined = run.data ?? latest.data
  const elapsed = useElapsed(run.isPending)

  const cases = useMemo(() => {
    let rows = report?.cases ?? []
    if (tier !== 'all') rows = rows.filter((c) => String(c.tier ?? '-') === tier)
    if (onlyFailures) rows = rows.filter((c) => !c.passed)
    return rows
  }, [report, tier, onlyFailures])

  const byTier = report?.by_tier ?? {}
  const runError = run.error ?? (latest.error && mode === 'live' ? latest.error : null)

  return (
    <div className="p-4 space-y-4 max-w-[1400px] mx-auto">
      <Panel bodyClassName="p-4 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <Toggle
            value={mode}
            onChange={(v) => setMode(v as 'engine' | 'live')}
            options={[
              { value: 'engine', label: 'Engine', title: 'Calls the deterministic core directly — fast, no model' },
              { value: 'live', label: 'Live Agent', title: 'Sends real questions through the actual agent — model included' },
            ]}
          />
          {mode === 'live' && (
            <span
              className={llmAvailable ? 'chip-legal' : 'chip-caution'}
              title={llmAvailable ? `${capabilities.data?.llm?.provider} · ${capabilities.data?.llm?.model}` : undefined}
            >
              <KeyRound size={11} /> {llmAvailable ? 'API key configured' : 'Please enter your LLM API key'}
            </span>
          )}
        </div>
        <p className="text-xs text-mute-400 leading-relaxed max-w-[80ch]">
          {mode === 'engine'
            ? 'Calls app.core directly against the shipped answer keys — no agent, no model, no network. Fast and identical every run, by design: this proves the deterministic engine\'s math is right, nothing more.'
            : 'Sends each question\'s own English through the real agent — the same path /api/chat uses, model included. Takes real wall-clock time and can genuinely fail on routing or narration — that variance is the point, not a bug.'}
        </p>
      </Panel>

      <Panel
        title={mode === 'engine' ? 'Engine conformance' : 'Live agent conformance'}
        subtitle={
          mode === 'engine'
            ? "Graded against the dataset's own answer keys — no test fixtures of our own"
            : report?.provider
              ? `via ${report.provider} · ${report.model}`
              : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            {mode === 'engine' && (
              <Toggle
                value={suite}
                onChange={setSuite}
                options={[
                  { value: 'all', label: 'All' },
                  { value: 'questions', label: 'Questions' },
                  { value: 'scenarios', label: 'Scenarios' },
                  { value: 'holdout', label: 'Held out' },
                ]}
              />
            )}
            <button
              className="btn-primary"
              onClick={() => run.mutate()}
              disabled={run.isPending || (mode === 'live' && !llmAvailable)}
              title={mode === 'live' && !llmAvailable ? 'Please enter your LLM API key' : undefined}
            >
              <Play size={12} />
              {run.isPending
                ? mode === 'live'
                  ? `Running… ${(elapsed / 1000).toFixed(0)}s (real API calls, ~38 questions)`
                  : 'Running…'
                : 'Run now'}
            </button>
          </div>
        }
        bodyClassName="p-4 space-y-4"
      >
        {mode === 'live' && !llmAvailable && !report && (
          <div className="rounded-lg border border-caution/30 bg-caution/5 p-3 flex items-start gap-2">
            <AlertTriangle size={14} className="text-caution mt-0.5 shrink-0" />
            <p className="text-xs text-mute-300 leading-relaxed">
              Please enter your LLM API key — set <code className="mono">OPENAI_API_KEY</code> or{' '}
              <code className="mono">ANTHROPIC_API_KEY</code> in <code className="mono">backend/.env</code> and
              restart the server. The engine suite above does not need a model; this one does.
            </p>
          </div>
        )}

        {runError && <ErrorBox error={runError} />}
        {latest.isLoading && !runError && <Skeleton rows={3} />}

        {report && (
          <>
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-4 lg:grid-cols-6">
              <StatTile
                label="Overall"
                value={`${report.passed}/${report.total}`}
                tone={report.passed === report.total ? 'legal' : 'breach'}
                hint={
                  mode === 'live'
                    ? `${Math.round(report.pass_rate * 100)}% · ${((report.wall_ms ?? report.duration_ms ?? 0) / 1000).toFixed(1)}s wall time`
                    : `${Math.round(report.pass_rate * 100)}% · ${report.duration_ms?.toFixed(0) ?? '—'}ms`
                }
              />
              {Object.entries(byTier).map(([t, v]) => (
                <StatTile
                  key={t}
                  label={`Tier ${t}`}
                  value={`${v.passed}/${v.total}`}
                  tone={v.passed === v.total ? 'legal' : 'breach'}
                  hint={TIER_HINT[t]}
                />
              ))}
              {mode === 'live' && report.latency_ms && (
                <StatTile
                  label="Per-question latency"
                  value={`${(report.latency_ms.avg / 1000).toFixed(1)}s`}
                  hint={`avg · ${(report.latency_ms.min / 1000).toFixed(1)}–${(report.latency_ms.max / 1000).toFixed(1)}s range`}
                />
              )}
              {report.suites &&
                Object.entries(report.suites).map(([name, s]) => (
                  <StatTile
                    key={name}
                    label={name}
                    value={`${s.passed}/${s.total}`}
                    tone={s.passed === s.total ? 'legal' : 'breach'}
                  />
                ))}
            </div>

            {/* Pass/fail strip — one mark per case */}
            <div>
              <div className="label mb-1.5">Every graded case</div>
              <div className="flex flex-wrap gap-1">
                {(report.cases ?? []).map((c) => (
                  <Tip
                    key={c.case_id}
                    text={`${c.case_id}: ${c.title}${c.meta?.latency_ms ? ` · ${(c.meta.latency_ms / 1000).toFixed(1)}s` : ''}`}
                  >
                    <span
                      className="w-5 h-5 rounded flex items-center justify-center num text-[9px] font-semibold"
                      style={{
                        background: c.passed ? `${STATUS.legal}22` : `${STATUS.breach}22`,
                        color: c.passed ? STATUS.legal : STATUS.breach,
                        border: `1px solid ${c.passed ? STATUS.legal : STATUS.breach}55`,
                      }}
                    >
                      {c.case_id.replace(/^[QSH]/, '')}
                    </span>
                  </Tip>
                ))}
              </div>
            </div>
          </>
        )}
      </Panel>

      <Panel
        title="Cases"
        actions={
          <div className="flex items-center gap-2">
            <Toggle
              value={tier}
              onChange={setTier}
              options={[
                { value: 'all', label: 'All' },
                { value: '1', label: 'T1' },
                { value: '2', label: 'T2' },
                { value: '3', label: 'T3' },
                { value: '-', label: 'Scenarios' },
              ]}
            />
            <label className="flex items-center gap-1.5 text-2xs text-mute-400 cursor-pointer">
              <input
                type="checkbox"
                checked={onlyFailures}
                onChange={(e) => setOnlyFailures(e.target.checked)}
                className="accent-signal"
              />
              Failures only
            </label>
          </div>
        }
        bodyClassName="p-0"
      >
        <ul className="divide-y divide-ink-800">
          {cases.map((c) => (
            <CaseRow key={c.case_id} c={c} live={mode === 'live'} />
          ))}
          {cases.length === 0 && (
            <li className="p-6 text-center text-xs text-mute-400">
              {report ? 'Nothing matches this filter.' : 'Run the suite above to see cases.'}
            </li>
          )}
        </ul>
      </Panel>
    </div>
  )
}

function useElapsed(active: boolean): number {
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef<number>(0)
  useEffect(() => {
    if (!active) {
      setElapsed(0)
      return
    }
    startRef.current = Date.now()
    const id = setInterval(() => setElapsed(Date.now() - startRef.current), 500)
    return () => clearInterval(id)
  }, [active])
  return elapsed
}

const TIER_HINT: Record<string, string> = {
  '1': 'lookup & retrieval',
  '2': 'consequence & simulation',
  '3': 'ranked recommendation',
}

function CaseRow({ c, live }: { c: EvalCase; live: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-start gap-3 px-4 py-2.5 hover:bg-ink-850 text-left transition-colors"
      >
        <span className="mt-0.5">{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
        <Pass ok={c.passed} />
        <span className="num text-2xs text-mute-400 w-10 shrink-0">{c.case_id}</span>
        {c.tier && <span className="chip-neutral shrink-0">T{c.tier}</span>}
        <span className="text-xs text-mute-300 leading-snug">{c.title}</span>
        <span className="ml-auto flex items-center gap-2 shrink-0">
          {live && c.meta?.intent && <span className="chip-neutral">{c.meta.intent}</span>}
          {live && c.meta?.latency_ms !== undefined && (
            <span className="num text-2xs text-mute-400">{(c.meta.latency_ms / 1000).toFixed(1)}s</span>
          )}
          <span className="text-2xs text-mute-400">
            {c.checks.filter((x) => x.passed).length}/{c.checks.length} checks
          </span>
        </span>
      </button>

      {open && (
        <div className="px-4 pb-3 pl-16 space-y-1.5">
          {c.error && (
            <p className="text-2xs text-breach">
              {c.error}
            </p>
          )}
          {c.checks.map((check, i) => (
            <div key={i} className="flex items-start gap-2 text-2xs">
              <Pass ok={check.passed} />
              <span className="text-mute-300 w-52 shrink-0">{check.name}</span>
              {!check.passed && (
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="text-mute-400">
                    expected <span className="num text-mute-300">{stringify(check.expected)}</span>
                  </div>
                  <div className="text-mute-400">
                    got <span className="num text-breach">{stringify(check.actual)}</span>
                  </div>
                  {check.detail && <div className="text-mute-400/70">{check.detail}</div>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </li>
  )
}

const stringify = (v: unknown) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s && s.length > 220 ? `${s.slice(0, 220)}…` : (s ?? '—')
}
