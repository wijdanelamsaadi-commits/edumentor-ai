import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { closeProfessorAssessment, deleteProfessorAssessment, getProfessorAssessments, publishProfessorAssessment } from '../services/api.js'

function ProfessorAssessmentsPage() {
  const [assessments, setAssessments] = useState([])
  const [message, setMessage] = useState('')

  useEffect(() => {
    refresh()
  }, [])

  function refresh() {
    getProfessorAssessments()
      .then((data) => setAssessments(Array.isArray(data) ? data : []))
      .catch((err) => setMessage(err.message || 'Chargement impossible.'))
  }

  async function publish(id) {
    try {
      await publishProfessorAssessment(id)
      setMessage('Évaluation publiée.')
      refresh()
    } catch (err) {
      setMessage(err.message || 'Publication impossible.')
    }
  }

  async function close(id) {
    try {
      await closeProfessorAssessment(id)
      refresh()
    } catch (err) {
      setMessage(err.message || 'Clôture impossible.')
    }
  }

  async function remove(id) {
    if (!window.confirm('Supprimer ou archiver cette évaluation ?')) return
    try {
      await deleteProfessorAssessment(id)
      refresh()
    } catch (err) {
      setMessage(err.message || 'Suppression impossible.')
    }
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Évaluations</h1>
          <p>Tests initiaux, personnalisés et rapports de remédiation.</p>
        </div>
        <Link className="primary-button" to="/professor/assessments/new">Créer une évaluation</Link>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      <article className="panel-card">
        <div className="admin-table">
          <div className="admin-table-row admin-table-head"><span>Titre</span><span>Cours</span><span>Type</span><span>Statut</span><span>Actions</span></div>
          {assessments.map((assessment) => (
            <div className="admin-table-row" key={assessment.id}>
              <span><strong>{assessment.title}</strong><small>{assessment.question_count} questions</small></span>
              <span>{assessment.course_title}</span>
              <span>{assessment.assessment_type}</span>
              <span>{assessment.status}</span>
              <span className="admin-actions">
                <Link className="outline-button" to={`/professor/assessments/${assessment.id}/edit`}>Modifier</Link>
                <Link className="outline-button" to={`/professor/assessments/${assessment.id}/results`}>Résultats</Link>
                {assessment.status !== 'published' && <button onClick={() => publish(assessment.id)} type="button">Publier</button>}
                {assessment.status === 'published' && <button onClick={() => close(assessment.id)} type="button">Clôturer</button>}
                <button onClick={() => remove(assessment.id)} type="button">Supprimer</button>
              </span>
            </div>
          ))}
        </div>
        {!assessments.length && <p className="admin-empty">Aucune évaluation créée.</p>}
      </article>
    </section>
  )
}

export default ProfessorAssessmentsPage
