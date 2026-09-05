import { useMutation, useQuery } from '@tanstack/react-query'
import { CornerDownLeft, KeyRound, Sparkles, Terminal } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AnswerCard } from '../components/AnswerCard'
import { EmptyState, ErrorBox, Panel, Spinner, Toggle } from '../components/ui'
import { api, type ChatAnswer } from '../lib/api'
import { SPAN_COLORS } from '../lib/viz'

const SUGGESTIONS: { tier: number; text: string }[] = [
  { tier: 1, text: 'Who is on reserve at BLR on 2026-09-15, and what are their on-call windows?' },
  { tier: 1, text: 'List all certifications expiring within 30 days of 2026-09-15.' },
  { tier: 2, text: 'Captain C-1042 calls in sick at 05:00Z on 15 Sep for pairing P-2291. Which flights are immediately uncrewed?' },
  { tier: 2, text: 'If Captain C-2087 is assigned to cover P-2291 from 15 Sep, does any rule breach? Give the detail.' },
  { tier: 2, text: 'BLR is closed 08:00–14:00Z on 17 Sep. Which flights are affected?' },
  { tier: 2, text: 'VT-DXA is delayed 90 minutes before DX401 on 16 Sep. Does the rostered crew breach any limit?' },
  { tier: 3, text: 'Captain C-1042 is out for pairing P-2291. Produce ranked resolution options with costs and reasoning.' },
  { tier: 3, text: 'Both captains of VT-DXA and VT-DXB are sick at 00:30Z on 18 Sep. Give the optimal joint crewing plan.' },
  { tier: 3, text: 'Draft the callout notification to C-3310 for covering P-2291.' },
]

interface Turn {
  question: string
  answer?: ChatAnswer
  error?: unknown
  pending?: boolean
}

export default function AdvisorPage() {
  const location = useLocation() as { state?: { question?: string } }
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [tier, setTier] = useState('all')
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  const llmAvailable = Boolean(capabilities.data?.llm?.available)
  const needsKey = capabilities.data != null && !llmAvailable

  const ask = useMutation({
    mutationFn: (question: string) => api.chat(question, conversationId),
    onMutate: (question) => {
      setTurns((t) => [...t, { question, pending: true }])
    },
    onSuccess: (answer) => {
      setConversationId(answer.conversation_id)
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer, pending: false } : turn)))
    },
    onError: (error) => {
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error, pending: false } : turn)))
    },
  })

  const submit = (question: string) => {
    const q = question.trim()
    if (!q || ask.isPending || needsKey) return
    setInput('')
    ask.mutate(q)
  }

  // An alert can hand a question straight to the advisor.
  useEffect(() => {
    const seeded = location.state?.question
    if (seeded) submit(seeded)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state?.question])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const suggestions = useMemo(
    () => (tier === 'all' ? SUGGESTIONS : SUGGESTIONS.filter((s) => String(s.tier) === tier)),
    [tier],
  )

  return (
    <div className="h-[calc(100vh-3.5rem)] grid lg:grid-cols-[minmax(0,1fr)_320px]">
      {/* ---- Conversation ---- */}
      <div className="flex flex-col min-h-0">
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {turns.length === 0 && (
            <EmptyState
              icon={needsKey ? KeyRound : Sparkles}
              title={needsKey ? 'Please enter your LLM API key' : 'Ask in plain language'}
              body={
                needsKey
                  ? 'Set OPENAI_API_KEY or ANTHROPIC_API_KEY in backend/.env and restart the server.'
                  : 'Lookups, consequence questions, and ranked recommendations. When a question is outside what can be computed from this dataset, the advisor says so rather than guessing.'
              }
            />
          )}

          {turns.map((turn, i) => (
            <div key={i} className="space-y-3 animate-fade-in">
              <div className="flex justify-end">
                <p className="max-w-2xl rounded-xl rounded-br-sm bg-signal/10 border border-signal/25 px-3 py-2 text-sm text-mute-200">
                  {turn.question}
                </p>
              </div>
              {turn.pending && (
                <div className="panel p-4">
                  <Spinner label="Classifying, resolving entities, running the rules engine…" />
                </div>
              )}
              {turn.error ? <ErrorBox error={turn.error} /> : null}
              {turn.answer && <AnswerCard answer={turn.answer} />}
              {turn.answer && <TracePreview answer={turn.answer} />}
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="shrink-0 border-t border-ink-700/70 bg-ink-900/80 p-3">
          <div className="flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit(input)
                }
              }}
              rows={2}
              placeholder={
                needsKey
                  ? 'Please enter your LLM API key'
                  : 'A captain just called in sick — what should I do?   (⌘J to focus, Enter to send)'
              }
              disabled={needsKey}
              className="input flex-1 resize-none"
            />
            <button
              className="btn-primary h-9"
              onClick={() => submit(input)}
              disabled={ask.isPending || needsKey}
            >
              <CornerDownLeft size={13} /> Ask
            </button>
          </div>
        </div>
      </div>

      {/* ---- Side rail ---- */}
      <aside className="border-l border-ink-700/70 overflow-y-auto p-3 space-y-3 hidden lg:block">
        <Panel title="Try one of these" bodyClassName="p-2 space-y-2">
          <Toggle
            value={tier}
            onChange={setTier}
            options={[
              { value: 'all', label: 'All' },
              { value: '1', label: 'Tier 1' },
              { value: '2', label: 'Tier 2' },
              { value: '3', label: 'Tier 3' },
            ]}
          />
          <ul className="space-y-1">
            {suggestions.map((s) => (
              <li key={s.text}>
                <button
                  onClick={() => submit(s.text)}
                  disabled={needsKey}
                  className="w-full text-left text-2xs text-mute-300 hover:text-signal px-2 py-1.5 rounded-lg hover:bg-ink-850 leading-snug transition-colors disabled:opacity-40 disabled:hover:text-mute-300 disabled:hover:bg-transparent"
                >
                  <span className="chip-neutral mr-1.5">T{s.tier}</span>
                  {s.text}
                </button>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title="What it will not answer"
          subtitle={needsKey ? 'Please enter your LLM API key' : undefined}
          bodyClassName="p-3"
        >
          <ul className="space-y-1">
            {CANNOT.map((c) => (
              <li key={c} className="text-2xs text-mute-400 leading-snug">
                — {c}
              </li>
            ))}
          </ul>
          <p className="text-2xs text-mute-400/70 mt-2 leading-relaxed border-t border-ink-800 pt-2">
            Answering ten questions correctly and declining the eleventh is worth more than answering
            all eleven with three wrong.
          </p>
        </Panel>
      </aside>
    </div>
  )
}

const CANNOT = [
  'Passenger rebooking or compensation — no booking data exists',
  'Hotel allocation and crew payroll',
  'Predicting who will call in sick — the risk score is a provided input',
  'Regulations beyond the seven rules in the ruleset',
  'Anything outside the 14–20 September schedule window',
]

/** A compact view of what the run actually did, inline under the answer. */
function TracePreview({ answer }: { answer: ChatAnswer }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="panel">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full panel-hd hover:bg-ink-850 transition-colors"
      >
        <span className="flex items-center gap-2 text-2xs text-mute-400">
          <Terminal size={11} aria-hidden />
          {open ? 'Hide' : 'Show'} reasoning — {answer.tool_calls.length} tool calls,{' '}
          {answer.plan_source} plan, {answer.latency_ms?.toFixed(0)}ms
        </span>
      </button>
      {open && (
        <div className="p-3 space-y-1">
          {answer.intent && (
            <TraceRow
              type="node"
              name="classify_intent"
              detail={`${answer.intent.name} · confidence ${answer.intent.confidence} · via ${answer.intent.source}`}
            />
          )}
          <TraceRow
            type="node"
            name="resolve_entities"
            detail={Object.entries(answer.entities)
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join('  ')
              .slice(0, 160)}
          />
          {answer.tool_calls.map((call, i) => (
            <TraceRow
              key={i}
              type="tool"
              name={call.tool}
              detail={`${call.duration_ms?.toFixed(2)}ms · ${Object.keys(call.args).join(', ') || 'no args'}`}
            />
          ))}
          <TraceRow
            type="verify"
            name="verify"
            detail={answer.verification?.summary ?? 'not run'}
          />
        </div>
      )}
    </div>
  )
}

function TraceRow({ type, name, detail }: { type: string; name: string; detail: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0 mt-1.5"
        style={{ background: SPAN_COLORS[type] }}
        aria-hidden
      />
      <span className="trace-line text-mute-200 w-44 shrink-0 truncate">{name}</span>
      <span className="trace-line text-mute-400 truncate">{detail}</span>
    </div>
  )
}
