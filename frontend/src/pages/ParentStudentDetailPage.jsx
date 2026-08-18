import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getParentStudent } from '../services/api.js'

function ParentStudentDetailPage() {
  const { studentId } = useParams()
  const [data, setData] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getParentStudent(studentId)
      .then(setData)
      .catch((err) => setMessage(err.message || 'Suivi indisponible.'))
  }, [studentId])

  if (!data) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>{data.student.full_name}</h1>
        <p>{data.student.school_year || '1ere Bac'} - {data.student.region || 'Region non renseignee'}</p>
      </div>

      <div className="dashboard-stats">
        <article className="metric-card"><p>Progression</p><h2>{Math.round(data.progression.average)}%</h2><strong>{data.progression.courses_started} cours suivis</strong></article>
        <article className="metric-card"><p>Moyenne recente</p><h2>{Math.round(data.results.recent_average)}%</h2><strong>{data.results.attempts_count} evaluations</strong></article>
        <article className="metric-card"><p>Preparation regional</p><h2>{Math.round(data.regional_exam?.readiness_score || 0)}%</h2><strong>Indicateur pedagogique</strong></article>
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Alertes</h2><p>{data.alerts.length}</p></div>
        {data.alerts.length ? data.alerts.map((alert) => (
          <div className="history-item" key={alert.type}><span>!</span><div><strong>{alert.type}</strong><p>{alert.message}</p></div></div>
        )) : <p>Aucune alerte importante.</p>}
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Cours suivis</h2><p>{data.progression.courses.length}</p></div>
        {data.progression.courses.map((course) => (
          <div className="history-item" key={course.course_id}>
            <span>{course.progress}%</span>
            <div><strong>{course.course_title}</strong><p>Progression enregistree.</p></div>
          </div>
        ))}
      </article>
    </section>
  )
}

export default ParentStudentDetailPage
