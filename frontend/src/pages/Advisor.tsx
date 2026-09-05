import { useMutation, useQuery } from '@tanstack/react-query'
import { CornerDownLeft, KeyRound, Mic, MicOff, PanelLeftClose, PanelLeftOpen, Plus, Sparkles, Terminal, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AnswerCard } from '../components/AnswerCard'
import { EmptyState, ErrorBox, Panel, Spinner, Toggle } from '../components/ui'
import { api, type ChatAnswer } from '../lib/api'
import { SPAN_COLORS } from '../lib/viz'
import type { Turn } from '../App'

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

const CANNOT = [
  'Passenger rebooking or compensation — no booking data exists',
  'Hotel allocation and crew payroll',
  'Predicting who will call in sick — the risk score is a provided input',
  'Regulations beyond the seven rules in the ruleset',
  'Anything outside the 14–20 September schedule window',
]

function clsx(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}

// ── Advisor TTS ───────────────────────────────────────────────────────────────
const ADVISOR_TTS_STORAGE_KEY = 'advisor_tts_enabled'
let _advisorAudio: HTMLAudioElement | null = null

function stopAdvisorAudio(): void {
  if (_advisorAudio) { _advisorAudio.pause(); _advisorAudio = null }
}

async function speakAdvisorAnswer(text: string): Promise<void> {
  stopAdvisorAudio()
  try {
    const res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 3500), speaker: 'ritu', pace: 1.0 }),
    })
    if (!res.ok) return
    const url = URL.createObjectURL(await res.blob())
    const audio = new Audio(url)
    _advisorAudio = audio
    audio.onended = () => { URL.revokeObjectURL(url); _advisorAudio = null }
    audio.onerror = () => { URL.revokeObjectURL(url); _advisorAudio = null }
    audio.play().catch(() => {})
  } catch { /* non-blocking */ }
}

// ── Voice recording state machine ─────────────────────────────────────────────
type VoiceState = 'idle' | 'listening' | 'processing' | 'error'

function useVoiceRecorder(onTranscript: (text: string) => void) {
  const [voiceState, setVoiceState] = useState<VoiceState>('idle')
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const startRecording = async () => {
    setVoiceError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        setVoiceState('processing')
        try {
          const { transcript } = await api.transcribe(blob)
          onTranscript(transcript)
          setVoiceState('idle')
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : 'Transcription failed'
          setVoiceError(msg)
          setVoiceState('error')
        }
      }

      mediaRecorderRef.current = recorder
      recorder.start()
      setVoiceState('listening')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Microphone access denied'
      setVoiceError(msg)
      setVoiceState('error')
    }
  }

  const stopRecording = () => {
    mediaRecorderRef.current?.stop()
    mediaRecorderRef.current = null
  }

  const toggleRecording = () => {
    if (voiceState === 'listening') stopRecording()
    else if (voiceState === 'idle' || voiceState === 'error') startRecording()
  }

  const dismiss = () => {
    setVoiceState('idle')
    setVoiceError(null)
  }

  return { voiceState, voiceError, toggleRecording, dismiss }
}

// ── Listening popup ───────────────────────────────────────────────────────────
function ListeningPopup({
  state,
  error,
  onStop,
  onDismiss,
}: {
  state: VoiceState
  error: string | null
  onStop: () => void
  onDismiss: () => void
}) {
  if (state === 'idle') return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center pb-32 pointer-events-none">
      <div className="pointer-events-auto bg-ink-900 border border-ink-700 rounded-2xl shadow-2xl px-6 py-4 flex flex-col items-center gap-3 min-w-[220px]">
        {state === 'listening' && (
          <>
            <div className="relative flex items-center justify-center w-14 h-14">
              <span className="absolute inline-flex w-full h-full rounded-full bg-signal/20 animate-ping" />
              <span className="absolute inline-flex w-10 h-10 rounded-full bg-signal/30 animate-ping [animation-delay:0.2s]" />
              <Mic size={22} className="text-signal relative z-10" />
            </div>
            <p className="text-sm text-mute-200 font-medium">Listening…</p>
            <p className="text-2xs text-mute-400">Speak your question, then click Stop</p>
            <button onClick={onStop} className="btn-primary text-xs px-4 py-1.5 mt-1">
              <MicOff size={12} /> Stop
            </button>
          </>
        )}
        {state === 'processing' && (
          <>
            <Spinner label="" />
            <p className="text-sm text-mute-200 font-medium">Transcribing…</p>
            <p className="text-2xs text-mute-400">Sending to Sarvam STT</p>
          </>
        )}
        {state === 'error' && (
          <>
            <MicOff size={22} className="text-caution" />
            <p className="text-sm text-caution font-medium">Recording failed</p>
            <p className="text-2xs text-mute-400 text-center max-w-[180px]">{error}</p>
            <button onClick={onDismiss} className="btn-ghost text-xs px-4 py-1.5 mt-1">
              Dismiss
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
interface Props {
  turns: Turn[]
  setTurns: React.Dispatch<React.SetStateAction<Turn[]>>
  conversationId: string | undefined
  setConversationId: React.Dispatch<React.SetStateAction<string | undefined>>
}

export default function AdvisorPage({ turns, setTurns, conversationId, setConversationId }: Props) {
  const location = useLocation() as { state?: { question?: string; newConversation?: boolean } }
  const [input, setInput] = useState('')
  const [tier, setTier] = useState('all')
  const [loadingConvId, setLoadingConvId] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(true)
  const [advisorTts, setAdvisorTts] = useState<boolean>(
    () => localStorage.getItem(ADVISOR_TTS_STORAGE_KEY) === 'true',
  )
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const seededRef = useRef<string | null>(null)

  const { voiceState, voiceError, toggleRecording, dismiss } = useVoiceRecorder((transcript) => {
    setInput((prev) => (prev.trim() ? `${prev} ${transcript}` : transcript))
    setTimeout(() => inputRef.current?.focus(), 50)
  })

  const capabilities = useQuery({ queryKey: ['capabilities'], queryFn: api.capabilities })
  const llmAvailable = Boolean(capabilities.data?.llm?.available)
  const needsKey = capabilities.data != null && !llmAvailable

  // History list — always visible in sidebar, refreshes every 15s
  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api.conversations(25),
    staleTime: 15_000,
    refetchInterval: 15_000,
  })

  const ask = useMutation({
    mutationFn: (question: string) => api.chat(question, conversationId),
    onMutate: (question) => {
      stopAdvisorAudio()
      setTurns((t) => [...t, { question, pending: true }])
    },
    onSuccess: (answer) => {
      setConversationId(answer.conversation_id)
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer, pending: false } : turn))
      )
      conversations.refetch()
      if (advisorTts && answer.answer) {
        speakAdvisorAnswer(answer.answer)
      }
    },
    onError: (error) => {
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, error, pending: false } : turn))
      )
    },
  })

  const submit = (question: string) => {
    const q = question.trim()
    if (!q || ask.isPending || needsKey) return
    setInput('')
    ask.mutate(q)
  }

  const newConversation = () => {
    stopAdvisorAudio()
    setTurns([])
    setConversationId(undefined)
  }

  const loadConversation = async (id: string) => {
    if (id === conversationId) return
    stopAdvisorAudio()
    setLoadingConvId(id)
    try {
      const data = await api.conversation(id)
      const rebuilt: Turn[] = []
      const msgs = data.messages
      for (let i = 0; i < msgs.length; i++) {
        if (msgs[i].role === 'user') {
          const next = msgs[i + 1]
          const hasAssistant = next?.role === 'assistant'
          rebuilt.push({
            question: msgs[i].content,
            answer: hasAssistant
              ? {
                  run_id: next.run_id ?? '',
                  conversation_id: id,
                  question: msgs[i].content,
                  answer: next.content,
                  structured: next.structured ?? null,
                  intent: null,
                  entities: {},
                  tier: null,
                  citations: [],
                  verification: null,
                  abstained: false,
                  plan: [],
                  plan_source: 'history',
                  tool_calls: [],
                  latency_ms: null,
                  trace_summary: {},
                }
              : undefined,
          })
          if (hasAssistant) i++
        }
      }
      setTurns(rebuilt)
      setConversationId(id)
    } finally {
      setLoadingConvId(null)
    }
  }

  useEffect(() => {
    const seeded = location.state?.question
    if (!seeded || seededRef.current === seeded) return
    seededRef.current = seeded
    if (location.state?.newConversation) {
      setTurns([])
      setConversationId(undefined)
    }
    submit(seeded)
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

  // Stop audio on unmount
  useEffect(() => () => stopAdvisorAudio(), [])

  const suggestions = useMemo(
    () => (tier === 'all' ? SUGGESTIONS : SUGGESTIONS.filter((s) => String(s.tier) === tier)),
    [tier],
  )

  return (
    <>
      <ListeningPopup
        state={voiceState}
        error={voiceError}
        onStop={toggleRecording}
        onDismiss={dismiss}
      />

      <div className={clsx(
        'h-[calc(100vh-3.5rem)] grid',
        historyOpen
          ? 'lg:grid-cols-[200px_minmax(0,1fr)_320px]'
          : 'lg:grid-cols-[32px_minmax(0,1fr)_320px]',
      )}>

        {/* ---- History sidebar ---- */}
        <aside className="border-r border-ink-700/70 flex-col min-h-0 hidden lg:flex overflow-hidden">
          <div className="shrink-0 p-2 border-b border-ink-700/70 flex items-center justify-between gap-1">
            <button
              onClick={() => setHistoryOpen((o) => !o)}
              className="flex items-center justify-center w-6 h-6 rounded text-mute-400 hover:text-signal hover:bg-ink-800 transition-colors shrink-0"
              title={historyOpen ? 'Collapse history' : 'Expand history'}
            >
              {historyOpen
                ? <PanelLeftClose size={13} aria-hidden />
                : <PanelLeftOpen size={13} aria-hidden />}
            </button>
            {historyOpen && (
              <>
                <span className="text-2xs font-medium text-mute-300 uppercase tracking-wide flex-1 truncate">
                  History
                </span>
                <button
                  onClick={newConversation}
                  className="flex items-center gap-1 text-2xs text-mute-400 hover:text-signal px-1.5 py-1 rounded hover:bg-ink-800 transition-colors shrink-0"
                  title="New conversation"
                >
                  <Plus size={11} /> New
                </button>
              </>
            )}
          </div>

          {historyOpen && (
            <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
              {turns.length > 0 && !conversations.data?.conversations.find((c) => c.id === conversationId) && (
                <div className="px-2 py-1.5 rounded-lg bg-signal/10 border border-signal/20">
                  <p className="text-2xs text-signal truncate font-medium">
                    {turns[0]?.question ?? 'Current chat'}
                  </p>
                  <p className="text-2xs text-mute-400 mt-0.5">
                    {turns.length} turn{turns.length !== 1 ? 's' : ''}
                  </p>
                </div>
              )}

              {conversations.isLoading && (
                <p className="text-2xs text-mute-400 px-2 py-2">Loading…</p>
              )}

              {conversations.data?.conversations.map((c) => (
                <button
                  key={c.id}
                  onClick={() => loadConversation(c.id)}
                  disabled={loadingConvId === c.id}
                  className={clsx(
                    'w-full text-left px-2 py-1.5 rounded-lg transition-colors group',
                    c.id === conversationId
                      ? 'bg-signal/10 border border-signal/20'
                      : 'hover:bg-ink-800',
                  )}
                >
                  <p className={clsx(
                    'text-2xs truncate',
                    c.id === conversationId
                      ? 'text-signal'
                      : 'text-mute-200 group-hover:text-mute-100',
                  )}>
                    {loadingConvId === c.id ? 'Loading…' : c.title}
                  </p>
                  <p className="text-2xs text-mute-500 mt-0.5">
                    {c.message_count} msg · {new Date(c.created_at).toLocaleDateString()}
                  </p>
                </button>
              ))}

              {conversations.data?.conversations.length === 0 && (
                <p className="text-2xs text-mute-500 px-2 py-2">No past conversations</p>
              )}
            </div>
          )}
        </aside>

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
                {turn.answer && <AnswerCard answer={turn.answer} from="/advisor" />}
                {turn.answer && turn.answer.plan_source !== 'history' && (
                  <TracePreview answer={turn.answer} />
                )}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          {/* ── Input bar ── */}
          <div className="shrink-0 border-t border-ink-700/70 bg-ink-900/80 p-3">
            <div className="flex gap-2 items-center">
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
                rows={1}
                placeholder={
                  needsKey
                    ? 'Please enter your LLM API key'
                    : 'A captain just called in sick — what should I do?   (⌘J to focus, Enter to send)'
                }
                disabled={needsKey}
                className="input flex-1 resize-none h-9 py-2 leading-5"
              />

              {/* Mic button */}
              <button
                onClick={toggleRecording}
                disabled={needsKey || voiceState === 'processing'}
                title={
                  voiceState === 'listening'
                    ? 'Stop recording'
                    : voiceState === 'processing'
                      ? 'Transcribing…'
                      : 'Record voice input (Sarvam STT)'
                }
                className={clsx(
                  'h-9 w-9 flex items-center justify-center rounded-lg border transition-colors shrink-0',
                  voiceState === 'listening'
                    ? 'bg-signal/20 border-signal text-signal animate-pulse'
                    : voiceState === 'processing'
                      ? 'bg-ink-800 border-ink-600 text-mute-400 cursor-wait'
                      : needsKey
                        ? 'bg-ink-800 border-ink-600 text-mute-600 cursor-not-allowed'
                        : 'bg-ink-800 border-ink-600 text-mute-400 hover:text-signal hover:border-signal',
                )}
              >
                {voiceState === 'listening' ? <MicOff size={15} /> : <Mic size={15} />}
              </button>

              {/* Advisor TTS toggle */}
              <button
                onClick={() => {
                  setAdvisorTts((prev) => {
                    const next = !prev
                    localStorage.setItem(ADVISOR_TTS_STORAGE_KEY, String(next))
                    if (!next) stopAdvisorAudio()
                    return next
                  })
                }}
                title={advisorTts ? 'Advisor voice on — click to mute' : 'Advisor voice off — click to enable'}
                className={clsx(
                  'h-9 w-9 flex items-center justify-center rounded-lg border transition-colors shrink-0',
                  advisorTts
                    ? 'bg-signal/20 border-signal text-signal'
                    : 'bg-ink-800 border-ink-600 text-mute-400 hover:text-signal hover:border-signal',
                )}
              >
                {advisorTts ? <Volume2 size={15} /> : <VolumeX size={15} />}
              </button>

              <button
                className="btn-primary h-9"
                onClick={() => submit(input)}
                disabled={ask.isPending || needsKey}
              >
                <CornerDownLeft size={13} /> Ask
              </button>
            </div>

            {voiceState === 'idle' && input && (
              <p className="text-2xs text-mute-500 mt-1.5 pl-1">
                Voice transcript ready — review and click Ask to send.
              </p>
            )}
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
                  – {c}
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
    </>
  )
}

/** Compact view of what the run actually did, inline under the answer. */
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