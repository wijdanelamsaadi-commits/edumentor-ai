import { Link } from 'react-router-dom'
import { BookOpen, ClipboardCheck, GraduationCap, TrendingUp, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getProfessorDashboard } from '../services/api.js'

function ProfessorDashboardPage() {
  const [dashboard, setDashboard] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let ignore = false
    getProfessorDashboard()
      .then((data) => {
        if (!ignore) setDashboard(data)
      })
      .catch((err) => {
        if (!ignore) setError(err.message || "Impossible de charger l'espace professeur.")
      })
    return () => {
      ignore = true
    }
  }, [])

  if (!dashboard && !error) {
    return <section className="page-section"><article className="panel-card">Chargement...</article></section>
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Tableau de bord professeur</h1>
          <p>Suivi de vos cours, étudiants, évaluations et remédiations réelles.</p>
        </div>
        <div className="admin-actions">
          <Link className="outline-button" to="/professor/classrooms/new">Créer une classe</Link>
          <Link className="primary-button" to="/professor/assessments/new">Créer une évaluation</Link>
        </div>
      </div>

      {error && <article className="panel-card"><p>{error}</p></article>}

      <div className="dashboard-stats">
        <Stat icon={<GraduationCap size={24} />} label="Professeur" value={dashboard?.name || 'Professeur'} hint={dashboard?.email || '--'} />
        <Stat icon={<BookOpen size={24} />} label="Cours" value={dashboard?.total_courses || 0} hint={`${dashboard?.published_courses || 0} publiés, ${dashboard?.draft_courses || 0} brouillons`} />
        <Stat icon={<Users size={24} />} label="Classes" value={dashboard?.classroom_count || 0} hint={`${dashboard?.classroom_student_count || 0} étudiants inscrits`} />
      </div>

      <div className="dashboard-stats">
        <Stat icon={<ClipboardCheck size={24} />} label="Évaluations publiées" value={dashboard?.assessment_published_count || 0} hint={`${dashboard?.assessment_draft_count || 0} brouillons`} />
        <Stat icon={<TrendingUp size={24} />} label="Participation" value={`${dashboard?.assessment_participation_rate || 0}%`} hint={`Score moyen ${dashboard?.assessment_average_score || 0}%`} />
        <Stat icon={<Users size={24} />} label="Étudiants en difficulté" value={dashboard?.students_in_difficulty || 0} hint={`${dashboard?.active_remediations || 0} remédiations en cours`} />
      </div>

      <div className="dashboard-stats">
        <Stat icon={<ClipboardCheck size={24} />} label="Évaluations terminées" value={dashboard?.assessment_completed_count || 0} hint="Avec tentative ou clôture" />
        <Stat icon={<TrendingUp size={24} />} label="Amélioration moyenne" value={`${dashboard?.average_remediation_improvement || 0} pts`} hint="Après test personnalisé réel" />
        <Stat icon={<BookOpen size={24} />} label="Quiz réalisés" value={dashboard?.total_quiz_attempts || 0} hint={`Score moyen ${dashboard?.average_quiz_score || 0}%`} />
      </div>

      <div className="dashboard-stats">
        <Stat icon={<BookOpen size={24} />} label="Parcours actifs" value={dashboard?.study_path_active_count || 0} hint={`${dashboard?.study_path_average_progress || 0}% de progression moyenne`} />
        <Stat icon={<Users size={24} />} label="Etudiants bloques" value={dashboard?.study_path_blocked_students || 0} hint={`${dashboard?.study_path_not_started_students || 0} parcours non demarres`} />
        <Stat icon={<ClipboardCheck size={24} />} label="Parcours termines" value={dashboard?.study_path_completed_count || 0} hint={`${dashboard?.study_path_lessons_done_without_test || 0} mini-cours faits sans test`} />
      </div>

      <div className="dashboard-grid">
        <article className="panel-card">
          <div className="panel-title">
            <h2>Derniers cours</h2>
            <Link to="/professor/courses">Voir tout</Link>
          </div>
          {(dashboard?.recent_courses || []).length ? dashboard.recent_courses.map((course) => (
            <div className="history-item" key={course.id}>
              <span><BookOpen size={18} /></span>
              <div>
                <strong>{course.title}</strong>
                <p>{course.subject?.name || 'Matière non définie'} · {course.status}</p>
              </div>
              <Link to={`/professor/courses/${course.id}`}>Voir</Link>
            </div>
          )) : <p className="admin-empty">Aucun cours professeur pour le moment.</p>}
        </article>

        <article className="panel-card">
          <div className="panel-title">
            <h2>Évaluations récentes</h2>
            <Link to="/professor/assessments">Voir les résultats</Link>
          </div>
          {(dashboard?.recent_assessments || []).length ? dashboard.recent_assessments.map((assessment) => (
            <div className="history-item" key={assessment.id}>
              <span><ClipboardCheck size={18} /></span>
              <div>
                <strong>{assessment.title}</strong>
                <p>{assessment.assessment_type} · {assessment.status}</p>
              </div>
              <Link to={`/professor/assessments/${assessment.id}/results`}>Résultats</Link>
            </div>
          )) : <p className="admin-empty">Aucune évaluation créée.</p>}
        </article>
      </div>

      <div className="dashboard-grid">
        <article className="panel-card">
          <div className="panel-title">
            <h2>Activité récente</h2>
            <Link to="/professor/classrooms">Voir les étudiants</Link>
          </div>
          {(dashboard?.recent_student_activity || []).length ? dashboard.recent_student_activity.map((activity) => (
            <div className="history-item" key={`${activity.student_id}-${activity.course_id}-${activity.date}`}>
              <span><Users size={18} /></span>
              <div>
                <strong>{activity.student_name}</strong>
                <p>{activity.course_title} · {activity.progression}%</p>
              </div>
              <time>{activity.date ? new Date(activity.date).toLocaleDateString('fr-FR') : '--'}</time>
            </div>
          )) : <p className="admin-empty">Aucune activité étudiante enregistrée.</p>}
        </article>

        <article className="panel-card">
          <div className="panel-title">
            <h2>Prochaines échéances</h2>
            <Link to="/professor/assessments">Planifier</Link>
          </div>
          {(dashboard?.upcoming_assessment_deadlines || []).length ? dashboard.upcoming_assessment_deadlines.map((deadline) => (
            <div className="history-item" key={deadline.id}>
              <span><ClipboardCheck size={18} /></span>
              <div>
                <strong>{deadline.title}</strong>
                <p>{deadline.status}</p>
              </div>
              <time>{deadline.expires_at ? new Date(deadline.expires_at).toLocaleDateString('fr-FR') : '--'}</time>
            </div>
          )) : <p className="admin-empty">Aucune échéance proche.</p>}
        </article>
      </div>
      <article className="panel-card">
        <div className="panel-title">
          <h2>Parcours personnalises actifs</h2>
          <span>{dashboard?.study_path_active_count || 0}</span>
        </div>
        {(dashboard?.recent_study_paths || []).length ? dashboard.recent_study_paths.map((path) => (
          <div className="history-item" key={path.id}>
            <span><BookOpen size={18} /></span>
            <div>
              <strong>{path.student_name}</strong>
              <p>{path.course_title} - {Math.round(path.progress_percentage)}% - {path.current_item?.title || 'Aucune etape active'}</p>
            </div>
            <Link to={`/professor/study-paths/${path.id}`}>Ouvrir</Link>
          </div>
        )) : <p className="admin-empty">Aucun parcours personnalise actif.</p>}
      </article>
    </section>
  )
}

function Stat({ icon, label, value, hint }) {
  return (
    <article className="stat-card">
      <span>{icon}</span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>{hint}</p>
      </div>
    </article>
  )
}

export default ProfessorDashboardPage
