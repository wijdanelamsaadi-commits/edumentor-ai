import { useEffect, useMemo, useState } from 'react'
import {
  getParentDashboard,
  getParentNotifications,
  getParentStudent,
} from '../services/api.js'

const SECTION_TITLES = {
  dashboard: 'Tableau de bord parent',
  progress: 'Progression',
  results: 'Résultats',
  weaknesses: 'Points faibles',
  regional: 'Examens régionaux',
}

function ParentDashboardPage({ section = 'dashboard' }) {
  const [dashboard, setDashboard] = useState({ children: [], summary: null })
  const [selectedStudentId, setSelectedStudentId] = useState(null)
  const [studentData, setStudentData] = useState(null)
  const [notifications, setNotifications] = useState([])
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([getParentDashboard(), getParentNotifications()])
      .then(([data, notificationData]) => {
        if (!active) return
        setDashboard(data)
        setNotifications(notificationData.notifications || [])
        setSelectedStudentId(data.selected_student_id || data.children?.[0]?.id || null)
      })
      .catch((err) => {
        if (active) setMessage(err.message || 'Espace parent indisponible.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!selectedStudentId) {
      setStudentData(null)
      return
    }
    let active = true
    setLoading(true)
    getParentStudent(selectedStudentId)
      .then((data) => {
        if (active) setStudentData(data)
      })
      .catch((err) => {
        if (active) setMessage(err.message || 'Suivi indisponible.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [selectedStudentId])

  const selectedChild = useMemo(
    () => dashboard.children.find((child) => String(child.id) === String(selectedStudentId)) || dashboard.children[0],
    [dashboard.children, selectedStudentId],
  )

  const current = studentData || { student: selectedChild || {}, progression: {}, results: {}, competencies: dashboard.summary?.competencies || [], weak_points: [], recommendations: [] }
  const competencies = current.competencies || []
  const weakPoints = current.weak_points || []
  const recommendations = current.recommendations || dashboard.summary?.recommendations || []
  const title = SECTION_TITLES[section] || SECTION_TITLES.dashboard

  return (
    <section className="page-section dashboard-page parent-dashboard-page">
      <div className="page-heading">
        <div>
          <h1>{title}</h1>
          <p>Suivi pédagogique simple et sécurisé des enfants liés à votre compte.</p>
        </div>
        {dashboard.children.length > 1 && (
          <label className="parent-child-select">
            Enfant
            <select onChange={(event) => setSelectedStudentId(Number(event.target.value))} value={selectedStudentId || ''}>
              {dashboard.children.map((child) => <option key={child.id} value={child.id}>{child.full_name}</option>)}
            </select>
          </label>
        )}
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}
      {loading && !current.student?.id && <article className="panel-card"><p>Chargement du suivi...</p></article>}
      {!loading && dashboard.children.length === 0 && <article className="panel-card"><p>Aucun enfant n'est encore lié à votre compte.</p></article>}

      {current.student?.id && (
        <>
          <div className="page-heading compact-heading">
            <div>
              <h2>Suivi de {current.student.full_name}</h2>
              <p>{current.student.school_year || '1ère Bac'} - {current.student.region || 'Région non renseignée'}</p>
            </div>
          </div>

          {(section === 'dashboard' || section === 'progress') && (
            <>
              <div className="dashboard-stats">
                <MetricCard label="Niveau actuel" value={current.level || selectedChild?.level || 'Non évalué'} note="Donnée pédagogique" />
                <MetricCard label="Progression globale" value={`${Math.round(current.progression?.average || 0)}%`} note={`${current.progression?.courses_started || 0} cours commencés`} />
                <MetricCard label="Dernier score" value={formatScore(current.results?.recent_average)} note={`${current.results?.attempts_count || 0} tentative(s)`} />
                <MetricCard label="À renforcer" value={weakPoints[0]?.competence || 'Aucune priorité'} note={weakPoints[0]?.status === 'faible' ? 'Faible' : 'Suivi normal'} />
              </div>
              <CompetencyPanel competencies={competencies} />
              <ProgressPanel progression={current.progression} />
            </>
          )}

          {(section === 'dashboard' || section === 'weaknesses') && (
            <>
              <WeaknessPanel weakPoints={weakPoints} />
              <RecommendationsPanel recommendations={recommendations} />
            </>
          )}

          {(section === 'dashboard' || section === 'results') && (
            <ResultsPanel diagnostic={current.diagnostic} results={current.results} />
          )}

          {(section === 'dashboard' || section === 'regional') && (
            <RegionalPanel regionalExam={current.regional_exam} works={current.progression?.works || []} />
          )}

          {section === 'dashboard' && (
            <>
              <ActivityPanel current={current} notifications={notifications} />
            </>
          )}
        </>
      )}
    </section>
  )
}

function MetricCard({ label, value, note }) {
  return <article className="metric-card"><p>{label}</p><h2>{value}</h2><strong>{note}</strong></article>
}

function CompetencyPanel({ competencies }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Progression par compétence</h2><p>{competencies.length}</p></div>
      <div className="parent-competency-list">
        {competencies.map((item) => (
          <div className="parent-competency-row" key={item.competence}>
            <span>{item.competence}</span>
            <div><i style={{ width: `${Math.max(0, Math.min(100, item.score || 0))}%` }} /></div>
            <strong>{Math.round(item.score || 0)}%</strong>
            <em>{item.status_label}</em>
          </div>
        ))}
      </div>
    </article>
  )
}

function ProgressPanel({ progression = {} }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Cours et œuvres</h2><p>{progression.courses_completed || 0} terminé(s)</p></div>
      {(progression.courses || []).length ? progression.courses.map((course) => (
        <div className="history-item" key={course.course_id}>
          <span>{Math.round(course.progress || 0)}%</span>
          <div><strong>{course.course_title}</strong><p>Dernière mise à jour : {formatDate(course.updated_at)}</p></div>
        </div>
      )) : <p>Aucune progression de cours enregistrée.</p>}
      {(progression.works || []).length > 0 && (
        <div className="parent-work-grid">
          {progression.works.map((work) => <MetricCard key={work.title} label={work.title} value={`${Math.round(work.progress || 0)}%`} note="Progression œuvre" />)}
        </div>
      )}
    </article>
  )
}

function WeaknessPanel({ weakPoints }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Points faibles</h2><p>{weakPoints.length}</p></div>
      {weakPoints.length ? weakPoints.map((item) => (
        <div className="history-item" key={item.competence}>
          <span>{Math.round(item.score || 0)}%</span>
          <div><strong>{item.competence}</strong><p>{item.message}</p></div>
        </div>
      )) : <p>Aucune difficulté prioritaire détectée.</p>}
    </article>
  )
}

function RecommendationsPanel({ recommendations }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Recommandations</h2><p>{recommendations.length}</p></div>
      {recommendations.length ? recommendations.map((item) => (
        <div className="history-item" key={item}><span>→</span><div><strong>Conseil pédagogique</strong><p>{item}</p></div></div>
      )) : <p>Aucune recommandation disponible pour le moment.</p>}
    </article>
  )
}

function ResultsPanel({ diagnostic, results = {} }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Résultats et tentatives</h2><p>{results.attempts_count || 0}</p></div>
      {diagnostic && (
        <div className="history-item">
          <span>{diagnostic.score}</span>
          <div><strong>Test diagnostique</strong><p>Niveau {diagnostic.level} - {diagnostic.correct_count}/{diagnostic.total}</p></div>
        </div>
      )}
      {(results.recent || []).map((attempt) => (
        <div className="history-item" key={`${attempt.assessment_id}-${attempt.submitted_at}`}>
          <span>{Math.round(attempt.score || 0)}%</span>
          <div><strong>{attempt.title}</strong><p>{formatDate(attempt.submitted_at)}</p></div>
        </div>
      ))}
      {(results.quiz_scores || []).map((quiz) => (
        <div className="history-item" key={`${quiz.course_id}-${quiz.created_at}`}>
          <span>{quiz.score}</span>
          <div><strong>{quiz.course_title}</strong><p>Quiz : {quiz.correct}/{quiz.total}</p></div>
        </div>
      ))}
      {!diagnostic && !(results.recent || []).length && !(results.quiz_scores || []).length && <p>Aucun résultat enregistré.</p>}
    </article>
  )
}

function RegionalPanel({ regionalExam, works }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Examens régionaux</h2><p>{regionalExam ? `${Math.round(regionalExam.readiness_score || 0)}%` : '0%'}</p></div>
      {regionalExam ? (
        <div className="history-item">
          <span>{Math.round(regionalExam.readiness_score || 0)}%</span>
          <div>
            <strong>{regionalExam.region || 'Région non renseignée'}</strong>
            <p>{regionalExam.academic_year} - {regionalExam.exam_date || 'Date non renseignée'}</p>
          </div>
        </div>
      ) : <p>Aucun profil d'examen régional enregistré.</p>}
      {(works || []).map((work) => (
        <div className="history-item" key={work.title}>
          <span>{Math.round(work.progress || 0)}%</span>
          <div><strong>{work.title}</strong><p>Progression sur l'œuvre</p></div>
        </div>
      ))}
    </article>
  )
}

function ActivityPanel({ current, notifications }) {
  return (
    <article className="panel-card parent-panel">
      <div className="panel-title"><h2>Dernières activités</h2><p>{notifications.length}</p></div>
      <div className="history-item"><span>•</span><div><strong>Dernière activité</strong><p>{formatDate(current.last_activity) || 'Non disponible'}</p></div></div>
      {notifications.slice(0, 3).map((notification) => (
        <div className="history-item" key={notification.id}>
          <span>{notification.severity || 'info'}</span>
          <div><strong>{notification.title}</strong><p>{notification.message}</p></div>
        </div>
      ))}
    </article>
  )
}

function formatScore(value) {
  return value === null || value === undefined ? 'Aucun' : `${Math.round(value)}%`
}

function formatDate(value) {
  if (!value) return ''
  try {
    return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  } catch {
    return value
  }
}

export default ParentDashboardPage
