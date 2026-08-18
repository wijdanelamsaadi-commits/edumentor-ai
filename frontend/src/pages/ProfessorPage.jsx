import { useEffect, useState } from 'react'
import { BookOpen, GraduationCap, Users } from 'lucide-react'
import { fetchProfessorDashboard } from '../services/api.js'

function ProfessorPage() {
  const [dashboard, setDashboard] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let ignore = false

    async function loadDashboard() {
      try {
        const data = await fetchProfessorDashboard()
        if (!ignore) {
          setDashboard(data)
        }
      } catch {
        if (!ignore) {
          setMessage("Impossible de charger l'espace professeur.")
        }
      }
    }

    loadDashboard()

    return () => {
      ignore = true
    }
  }, [])

  const user = dashboard?.user
  const counters = dashboard?.counters || {}

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Espace professeur</h1>
        <p>{dashboard?.message || "Les fonctionnalites pedagogiques seront ajoutees a l'etape suivante."}</p>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <article className="stat-card">
          <span><GraduationCap size={24} /></span>
          <div>
            <small>Profil</small>
            <strong>{user?.full_name || 'Professeur'}</strong>
            <p>{user?.email || '--'}</p>
          </div>
        </article>
        <article className="stat-card">
          <span><BookOpen size={24} /></span>
          <div>
            <small>Role</small>
            <strong>{dashboard?.role || 'professor'}</strong>
            <p>Autorisation PostgreSQL</p>
          </div>
        </article>
        <article className="stat-card">
          <span><Users size={24} /></span>
          <div>
            <small>Compteurs</small>
            <strong>{counters.courses || 0} cours</strong>
            <p>{counters.students || 0} etudiants suivis</p>
          </div>
        </article>
      </div>
    </section>
  )
}

export default ProfessorPage
