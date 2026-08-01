import { BarChart3, BookOpen, ClipboardCheck, TrendingUp, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getProfessorAnalytics } from '../services/api.js'

function ProfessorAnalyticsPage() {
  const [analytics, setAnalytics] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getProfessorAnalytics()
      .then(setAnalytics)
      .catch((err) => setMessage(err.message || 'Impossible de charger les statistiques.'))
  }, [])

  return (
    <section className="page-section admin-page">
      <div className="page-heading">
        <h1>Statistiques professeur</h1>
        <p>Analyse agrégée de vos cours et résultats étudiants.</p>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <Stat icon={<BookOpen size={22} />} label="Cours publiés" value={analytics?.published_courses || 0} />
        <Stat icon={<Users size={22} />} label="Étudiants actifs" value={analytics?.active_students || 0} />
        <Stat icon={<TrendingUp size={22} />} label="Progression moyenne" value={`${analytics?.average_progress || 0}%`} />
      </div>

      <div className="dashboard-stats">
        <Stat icon={<ClipboardCheck size={22} />} label="Quiz réalisés" value={analytics?.quiz_attempts || 0} />
        <Stat icon={<BarChart3 size={22} />} label="Score moyen" value={`${analytics?.average_score || 0}%`} />
        <Stat icon={<TrendingUp size={22} />} label="Taux de complétion" value={`${analytics?.completion_rate || 0}%`} />
      </div>

      <div className="admin-analytics-grid">
        <article className="panel-card admin-analytics-card">
          <h3>Distribution des scores</h3>
          {Object.entries(analytics?.score_distribution || {}).map(([label, count]) => (
            <div className="admin-progress-line" key={label}>
              <span>{label}</span>
              <div className="progress-track"><span style={{ width: `${Math.min(Number(count) * 10, 100)}%` }} /></div>
              <strong>{count}</strong>
            </div>
          ))}
        </article>
        <article className="panel-card admin-analytics-card">
          <h3>Chapitres les moins complétés</h3>
          {(analytics?.least_completed_chapters || []).length ? analytics.least_completed_chapters.map((chapter) => (
            <div className="admin-progress-line" key={chapter.title}>
              <span>{chapter.title}</span>
              <div className="progress-track"><span style={{ width: `${chapter.completion_rate}%` }} /></div>
              <strong>{chapter.completion_rate}%</strong>
            </div>
          )) : <p className="admin-empty">Aucune donnée de chapitre.</p>}
        </article>
      </div>
    </section>
  )
}

function Stat({ icon, label, value }) {
  return (
    <article className="stat-card">
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>Données PostgreSQL</p>
      </div>
    </article>
  )
}

export default ProfessorAnalyticsPage
