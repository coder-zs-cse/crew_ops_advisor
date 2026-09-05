import clsx from 'clsx'
import {
  Activity,
  BookOpen,
  CalendarClock,
  ClipboardCheck,
  LayoutDashboard,
  MessageSquare,
  Radar,
  Users,
  Wrench,
} from 'lucide-react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type ChatAnswer } from './lib/api'
import { ClockControl } from './components/ClockControl'
import AdvisorPage from './pages/Advisor'
import BriefingPage from './pages/Briefing'
import ConsolePage from './pages/Console'
import CrewPage from './pages/Crew'
import CrewDirectoryPage from './pages/CrewDirectory'
import EvalPage from './pages/Eval'
import RulesPage from './pages/Rules'
import RunDetailPage from './pages/RunDetail'
import RunsPage from './pages/Runs'
import WorkbenchPage from './pages/Workbench'

const NAV = [
  { to: '/', label: 'Console', icon: LayoutDashboard, end: true },
  { to: '/advisor', label: 'Advisor', icon: MessageSquare },
  { to: '/workbench', label: 'Workbench', icon: Wrench },
  { to: '/crew', label: 'Crew', icon: Users },
  // { to: '/briefing', label: 'Briefing', icon: CalendarClock },
  { to: '/runs', label: 'Traces', icon: Activity },
  // { to: '/eval', label: 'Scorecard', icon: ClipboardCheck },
  { to: '/rules', label: 'Rules', icon: BookOpen },
]

// Exported so Advisor.tsx can type its props correctly
export interface Turn {
  question: string
  answer?: ChatAnswer
  error?: unknown
  pending?: boolean
}

export default function App() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
  })

  // Advisor state lives here — survives tab switches because App never unmounts
  const [advisorTurns, setAdvisorTurns] = useState<Turn[]>([])
  const [advisorConversationId, setAdvisorConversationId] = useState<string | undefined>()

  const llmLive = health?.llm?.available
  const engine = health?.scheduler?.running

  return (
    <div className="min-h-screen flex flex-col">
      <header className="shrink-0 border-b border-ink-700/70 bg-ink-900/90 backdrop-blur sticky top-0 z-40">
        <div className="px-4 h-14 flex items-center gap-4">
          <div className="flex items-center gap-2.5 shrink-0">
            <Radar size={19} className="text-signal" aria-hidden />
            <div className="leading-none">
              <div className="text-sm font-semibold text-mute-200">Crew Ops Advisor</div>
              <div className="text-2xs text-mute-400 mt-0.5">dCortex Air · BLR</div>
            </div>
          </div>

          <nav className="flex items-center gap-0.5 overflow-x-auto" aria-label="Main">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors',
                    isActive
                      ? 'bg-signal/15 text-signal'
                      : 'text-mute-400 hover:text-mute-200 hover:bg-ink-800',
                  )
                }
              >
                <Icon size={13} aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 shrink-0">
            <ClockControl />
            <div
              className="flex items-center gap-1.5 text-2xs text-mute-400"
              title={
                llmLive
                  ? 'Language model reachable — used for intent and narration only.'
                  : 'Set OPENAI_API_KEY or ANTHROPIC_API_KEY in backend/.env and restart.'
              }
            >
              <span
                className={clsx(
                  'w-1.5 h-1.5 rounded-full animate-pulse-soft',
                  llmLive ? 'bg-legal' : 'bg-caution',
                )}
                aria-hidden
              />
              {llmLive ? 'LLM live' : 'Please enter your LLM API key'}
            </div>
            {engine === false && <span className="chip-caution">scheduler off</span>}
          </div>
        </div>
      </header>

      <main className="flex-1 min-h-0">
        <Routes>
          <Route path="/" element={<ConsolePage />} />
          <Route
            path="/advisor"
            element={
              <AdvisorPage
                turns={advisorTurns}
                setTurns={setAdvisorTurns}
                conversationId={advisorConversationId}
                setConversationId={setAdvisorConversationId}
              />
            }
          />
          <Route path="/workbench" element={<WorkbenchPage />} />
          <Route path="/briefing" element={<BriefingPage />} />
          <Route path="/crew" element={<CrewDirectoryPage />} />
          <Route path="/crew/:crewId" element={<CrewPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/eval" element={<EvalPage />} />
          <Route path="/rules" element={<RulesPage />} />
        </Routes>
      </main>
    </div>
  )
}