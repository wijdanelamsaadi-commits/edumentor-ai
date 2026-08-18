import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getStudentAssessments } from '../services/api.js'

function AssessmentsPage() {
  const [assessments, setAssessments] = useState([])
  const [message, setMessage] = useState('')

  useEffect(() => {
    getStudentAssessments()
      .then((data) => setAssessments(Array.isArray(data) ? data : []))
      .catch((err) => setMessage(err.message || 'Impossible de charger les évaluations.'))
  }, [])

  const available = assessments.filter((item) => item.assignment_status !== 'completed')
  const completed = assessments.filter((item) => item.assignment_status === 'completed')

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Évaluations</h1>
        <p>Tests disponibles, à venir et terminés.</p>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      <div className="dashboard-grid">
        <AssessmentList title="Tests disponibles" assessments={available} />
        <AssessmentList title="Tests terminés" assessments={completed} />
      </div>
    </section>
  )
}

function AssessmentList({ title, assessments }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{assessments.length}</p></div>
      {assessments.map((assessment) => (
        <div className="recommended-item" key={assessment.id}>
          <div>
            <strong>{assessment.title}</strong>
            <p>{assessment.course_title} — {assessment.question_count} questions — tentatives {assessment.attempts_used}/{assessment.max_attempts}</p>
            {assessment.personalized_context && (
              <small>
                Test cible : {assessment.personalized_context.targeted_skills?.length || 0} competence(s),
                {' '}{assessment.personalized_context.targeted_chapters?.length || 0} chapitre(s),
                statut {assessment.personalized_context.status}
              </small>
            )}
          </div>
          <Link className="outline-button" to={`/assessments/${assessment.id}`}>Ouvrir</Link>
        </div>
      ))}
      {!assessments.length && <p className="admin-empty">Aucun test dans cette section.</p>}
    </article>
  )
}

export default AssessmentsPage
