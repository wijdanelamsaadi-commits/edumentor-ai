import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BookOpen, ClipboardCheck, Target, TrendingUp, Users } from 'lucide-react'
import { getProfessorStudentDetail } from '../services/api.js'

function ProfessorStudentDetailPage() {
  const { studentId } = useParams()
  const [student, setStudent] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let ignore = false
    getProfessorStudentDetail(studentId)
      .then((data) => {
        if (!ignore) setStudent(data)
      })
      .catch((error) => {
        if (!ignore) setMessage(error.message || 'Suivi etudiant indisponible.')
      })
    return () => {
      ignore = true
    }
  }, [studentId])

  if (!student && !message) {
    return <section className="page-section"><article className="panel-card">Chargement...</article></section>
  }

  if (!student) {
    return (
      <section className="page-section">
        <article className="panel-card">
          <p>{message}</p>
          <Link className="outline-button" to="/professor/classrooms">Retour aux classes</Link>
        </article>
      </section>
    )
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{student.full_name}</h1>
          <p>{student.email} - Niveau actuel : {student.level || '--'}</p>
        </div>
        <Link className="outline-button" to="/professor/classrooms">Retour aux classes</Link>
      </div>

      <div className="dashboard-stats">
        <Stat icon={<TrendingUp size={22} />} label="Progression globale" value={`${student.global_progress || 0}%`} hint={`${student.started_courses || 0} cours commencés`} />
        <Stat icon={<ClipboardCheck size={22} />} label="Dernier score" value={student.latest_score == null ? '--' : `${Math.round(Number(student.latest_score))}%`} hint={`${student.regional_attempts || 0} tentative(s) régionale(s)`} />
        <Stat icon={<Target size={22} />} label="Point faible principal" value={student.main_weak_point?.competence || 'Non évalué'} hint={student.main_weak_point?.status || student.general_status || '--'} />
      </div>

      <div className="dashboard-grid">
        <Panel title="Classes">
          {(student.classrooms || []).map((classroom) => (
            <HistoryItem key={classroom.id} icon={<Users size={18} />} title={classroom.name} subtitle={classroom.code} />
          ))}
        </Panel>
        <Panel title="Compétences">
          {(student.competencies || []).map((item) => (
            <HistoryItem key={item.competence} icon={<Target size={18} />} title={item.competence} subtitle={`${item.status || 'non évalué'} - ${item.score_percentage ?? 0}%`} />
          ))}
        </Panel>
      </div>

      <div className="dashboard-grid">
        <Panel title="Cours commencés / terminés">
          {(student.course_progress || []).map((item) => (
            <HistoryItem key={item.course_id} icon={<BookOpen size={18} />} title={item.course_title} subtitle={`${item.progress || 0}% - ${formatDate(item.updated_at)}`} />
          ))}
        </Panel>
        <Panel title="Résultats quiz">
          {(student.quiz_results || []).map((item) => (
            <HistoryItem key={item.id} icon={<ClipboardCheck size={18} />} title={item.course_title} subtitle={`${item.score || 0}% - ${item.correct || 0}/${item.total || 0} - ${formatDate(item.created_at)}`} />
          ))}
        </Panel>
      </div>

      <div className="dashboard-grid">
        <Panel title="Tentatives régionales">
          {(student.regional_attempts || []).map((attempt) => (
            <HistoryItem key={attempt.attempt_id} icon={<ClipboardCheck size={18} />} title={attempt.title} subtitle={`${attempt.status} - ${attempt.percentage || 0}% - ${formatDate(attempt.submitted_at || attempt.started_at)}`} />
          ))}
        </Panel>
        <Panel title="Recommandations">
          {(student.recommendations || []).map((item) => (
            <HistoryItem key={item} icon={<Target size={18} />} title={item} subtitle="Recommandation pédagogique" />
          ))}
        </Panel>
      </div>
    </section>
  )
}

function Panel({ children, title }) {
  const rows = Array.isArray(children) ? children.filter(Boolean) : children
  return (
    <article className="panel-card">
      <div className="panel-title">
        <h2>{title}</h2>
      </div>
      {Array.isArray(rows) && rows.length ? rows : <p className="admin-empty">Aucune donnée.</p>}
    </article>
  )
}

function HistoryItem({ icon, subtitle, title }) {
  return (
    <div className="history-item">
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <p>{subtitle}</p>
      </div>
    </div>
  )
}

function Stat({ hint, icon, label, value }) {
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

function formatDate(value) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

export default ProfessorStudentDetailPage
