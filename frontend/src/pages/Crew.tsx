import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { CrewProfileBody } from '../components/CrewProfile'

export default function CrewPage() {
  const { crewId = '' } = useParams()
  return (
    <div className="p-4 space-y-4 max-w-[1200px] mx-auto">
      <div className="flex items-center gap-3">
        <Link to="/crew" className="btn-ghost">
          <ArrowLeft size={12} /> Crew directory
        </Link>
        <span className="num text-sm text-mute-200">{crewId}</span>
      </div>
      <CrewProfileBody crewId={crewId} />
    </div>
  )
}
