import { useEffect, useState } from 'react'
import { BarChart3, BookOpen, Bot, CheckCircle2, ClipboardList, Users } from 'lucide-react'
import { AdminLoading, AdminMessage, AdminMetric } from '../components/admin/AdminShared.jsx'
import { fetchAdminOverview } from '../services/api.js'
import { formatDate, formatTime, getBarWidth } from '../utils/adminFormat.js'

function AdminDashboardPage() {
  const [overview, setOverview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    async function loadOverview() {
      setLoading(true)
      setMessage('')
      try {
        setOverview(await fetchAdminOverview())
      } catch {
        setMessage("Impossible de charger le tableau de bord administrateur.")
      } finally {
        setLoading(false)
      }
    }

    loadOverview()
  }, [])

  if (loading) return <AdminLoading />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Tableau de bord admin</h1>
        <p>Pilotez les utilisateurs, les statistiques et les activites EduMentor AI.</p>
      </div>

      <AdminMessage message={message} />

      <div className="dashboard-stats">
        <AdminMetric
          icon={Users}
          label="Utilisateurs"
          text={`${overview?.total_admins || 0} admins - ${overview?.total_professors || 0} professors - ${overview?.total_students || 0} students`}
          value={overview?.total_users || 0}
        />
        <AdminMetric icon={BookOpen} label="Cours" value={overview?.total_courses || 0} text={`${overview?.completed_courses || 0} cours termines`} />
        <AdminMetric icon={ClipboardList} label="Quiz" value={overview?.total_quizzes || 0} text={`Score moyen : ${overview?.average_quiz_score || 0}%`} />
        <AdminMetric icon={Bot} label="Chatbot" value={overview?.total_chat_conversations || 0} text={`${overview?.total_notifications || 0} notifications`} />
      </div>

      <div className="dashboard-grid">
        <article className="panel-card">
          <div className="panel-title">
            <h2>Repartition des niveaux</h2>
          </div>
          <div className="admin-bars">
            {Object.entries(overview?.level_distribution || {}).map(([level, count]) => (
              <div className="admin-bar-row" key={level}>
                <span>{level}</span>
                <div className="progress-track"><span style={{ width: `${getBarWidth(count, overview?.total_diagnostics)}%` }} /></div>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
        </article>

        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Activite recente</h2>
          </div>
          {(overview?.recent_activity || []).length > 0 ? overview.recent_activity.map((activity) => (
            <div className="history-item" key={`${activity.type}-${activity.user_id}-${activity.date}`}>
              <span><BarChart3 size={22} /></span>
              <div>
                <strong>{activity.label}</strong>
                <p>Utilisateur #{activity.user_id}</p>
              </div>
              <time>{formatDate(activity.date)}<br />{formatTime(activity.date)}</time>
            </div>
          )) : (
            <div className="history-item">
              <span><CheckCircle2 size={22} /></span>
              <div>
                <strong>Aucune activite recente</strong>
                <p>Les evenements utilisateurs apparaitront ici.</p>
              </div>
              <time>--<br />--</time>
            </div>
          )}
        </article>
      </div>
    </section>
  )
}

export default AdminDashboardPage
