import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBox, Panel, Skeleton, Toggle } from '../components/ui'
import { api } from '../lib/api'

const RANKS = ['Captain', 'First Officer', 'Senior Cabin Crew', 'Cabin Crew']

/**
 * Every crew member on file, searchable and filterable. This is the "who do
 * we have" surface — the Advisor and Workbench answer questions about one
 * crew member at a time; this is where you find which one.
 */
export default function CrewDirectoryPage() {
  const [query, setQuery] = useState('')
  const [rank, setRank] = useState('all')
  const [base, setBase] = useState('all')
  const [status, setStatus] = useState('active')

  const crew = useQuery({ queryKey: ['crew-all'], queryFn: () => api.crew() })
  const snapshot = useQuery({ queryKey: ['snapshot'], queryFn: api.snapshot })

  const rows = useMemo(() => {
    let list = crew.data?.crew ?? []
    if (rank !== 'all') list = list.filter((c: any) => c.rank === rank)
    if (base !== 'all') list = list.filter((c: any) => c.base === base)
    if (status !== 'all') list = list.filter((c: any) => c.status === status)
    const q = query.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (c: any) => c.crew_id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q),
      )
    }
    return list.slice().sort((a: any, b: any) => a.crew_id.localeCompare(b.crew_id))
  }, [crew.data, rank, base, status, query])

  return (
    <div className="p-4 space-y-4 max-w-[1200px] mx-auto">
      <Panel
        title="Crew directory"
        subtitle={`${crew.data?.count ?? 0} on file — click a row to open the full profile`}
        actions={
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-mute-400" />
            <input
              className="input pl-7 py-1.5 text-xs w-56"
              placeholder="Search id or name…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        }
        bodyClassName="p-4 space-y-3"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Toggle
            value={rank}
            onChange={setRank}
            options={[{ value: 'all', label: 'All ranks' }, ...RANKS.map((r) => ({ value: r, label: r }))]}
          />
          <Toggle
            value={status}
            onChange={setStatus}
            options={[
              { value: 'all', label: 'Any status' },
              { value: 'active', label: 'Active' },
              { value: 'leave', label: 'Leave' },
              { value: 'training', label: 'Training' },
            ]}
          />
          <select className="input py-1.5 text-xs num" value={base} onChange={(e) => setBase(e.target.value)}>
            <option value="all">All bases</option>
            {(snapshot.data?.stations ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {crew.isLoading && <Skeleton rows={6} />}
        {crew.error && <ErrorBox error={crew.error} />}
        {!crew.isLoading && rows.length === 0 && (
          <EmptyState title="No crew match this filter" body="Try clearing the search or the rank/base filters." />
        )}

        {rows.length > 0 && (
          <div className="xscroll">
            <table className="w-full min-w-[720px] border-collapse">
              <thead>
                <tr>
                  <th className="th w-20">ID</th>
                  <th className="th">Name</th>
                  <th className="th w-36">Rank</th>
                  <th className="th w-16">Base</th>
                  <th className="th">Ratings</th>
                  <th className="th w-16 text-right">Seniority</th>
                  <th className="th w-20 text-right">Reach</th>
                  <th className="th w-20">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c: any) => (
                  <tr key={c.crew_id} className="tr">
                    <td className="cell">
                      <Link to={`/crew/${c.crew_id}`} className="num text-signal hover:underline">
                        {c.crew_id}
                      </Link>
                    </td>
                    <td className="cell text-mute-200">{c.name}</td>
                    <td className="cell text-mute-300">{c.rank}</td>
                    <td className="cell num text-mute-300">{c.base}</td>
                    <td className="cell text-mute-400">{(c.ratings ?? []).join(', ')}</td>
                    <td className="cell num text-right text-mute-400">{c.seniority}</td>
                    <td className="cell num text-right text-mute-400">{c.reachability_minutes}min</td>
                    <td className="cell">
                      <span className={c.status === 'active' ? 'chip-legal' : 'chip-caution'}>{c.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
