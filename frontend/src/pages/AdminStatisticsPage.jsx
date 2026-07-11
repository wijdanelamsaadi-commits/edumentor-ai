import { useEffect, useState } from 'react'
import { AnalyticsPanel, AdminLoading, AdminMessage, RankingList } from '../components/admin/AdminShared.jsx'
import {
  fetchAdminChatbotStats,
  fetchAdminCoursesStats,
  fetchAdminQuizzesStats,
  fetchAdminUsersStats,
} from '../services/api.js'

function AdminStatisticsPage() {
  const [analytics, setAnalytics] = useState({ users: null, courses: null, quizzes: null, chatbot: null })
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    async function loadAnalytics() {
      setLoading(true)
      setMessage('')
      try {
        const [usersStats, coursesStats, quizzesStats, chatbotStats] = await Promise.all([
          fetchAdminUsersStats(),
          fetchAdminCoursesStats(),
          fetchAdminQuizzesStats(),
          fetchAdminChatbotStats(),
        ])
        setAnalytics({ users: usersStats, courses: coursesStats, quizzes: quizzesStats, chatbot: chatbotStats })
      } catch {
        setMessage('Impossible de charger les statistiques.')
      } finally {
        setLoading(false)
      }
    }

    loadAnalytics()
  }, [])

  if (loading) return <AdminLoading text="Chargement des statistiques..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Analytics</h1>
        <p>Statistiques calculees depuis les donnees PostgreSQL.</p>
      </div>

      <AdminMessage message={message} />

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Analytics</h2>
            <p>Utilisateurs, cours, quiz, progression et chatbot.</p>
          </div>
        </div>
        <div className="admin-analytics-grid">
          <AnalyticsPanel
            title="Utilisateurs"
            rows={[
              ['Inscrits', analytics.users?.total_users || 0],
              ['Actifs', analytics.users?.active_users || 0],
              ['Nouveaux 7j', analytics.users?.new_users_7d || 0],
            ]}
          />
          <AnalyticsPanel
            title="Cours"
            rows={[
              ['Publies', analytics.courses?.published_courses || 0],
              ['Brouillons', analytics.courses?.draft_courses || 0],
              ['Progression moyenne', `${analytics.courses?.average_progress || 0}%`],
            ]}
          />
          <AnalyticsPanel
            title="Quiz"
            rows={[
              ['Realises', analytics.quizzes?.quiz_attempts || 0],
              ['Score moyen', `${analytics.quizzes?.average_score || 0}%`],
              ['Taux de reussite', `${analytics.quizzes?.success_rate || 0}%`],
            ]}
          />
          <AnalyticsPanel
            title="Chatbot"
            rows={[
              ['Conversations', analytics.chatbot?.conversations || 0],
              ['Questions RAG', analytics.chatbot?.rag_questions || 0],
              ['Questions Groq', analytics.chatbot?.groq_questions || 0],
              ['Hors sujet', analytics.chatbot?.out_of_scope_questions || 0],
            ]}
          />
        </div>
        <div className="dashboard-grid admin-analytics-lists">
          <RankingList title="Cours les plus consultes" items={analytics.courses?.most_viewed || []} metric="consultations" />
          <RankingList title="Quiz les plus difficiles" items={analytics.quizzes?.hardest_quizzes || []} metric="score moyen" />
        </div>
      </article>
    </section>
  )
}

export default AdminStatisticsPage
