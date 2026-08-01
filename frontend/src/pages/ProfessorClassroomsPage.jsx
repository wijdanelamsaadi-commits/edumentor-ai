import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getProfessorClassrooms } from '../services/api.js'

function ProfessorClassroomsPage() {
  const [classrooms, setClassrooms] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    getProfessorClassrooms()
      .then((data) => setClassrooms(Array.isArray(data) ? data : []))
      .catch((err) => setError(err.message || 'Impossible de charger les classes.'))
  }, [])

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Classes</h1>
          <p>Gestion des groupes et des étudiants inscrits.</p>
        </div>
        <Link className="primary-button" to="/professor/classrooms/new">Nouvelle classe</Link>
      </div>
      {error && <article className="panel-card"><p>{error}</p></article>}
      <article className="panel-card">
        <div className="admin-table">
          <div className="admin-table-row admin-table-head">
            <span>Classe</span><span>Code</span><span>Étudiants</span><span>Statut</span><span>Action</span>
          </div>
          {classrooms.map((classroom) => (
            <div className="admin-table-row" key={classroom.id}>
              <span><strong>{classroom.name}</strong><small>{classroom.academic_year || 'Année non définie'}</small></span>
              <span>{classroom.code}</span>
              <span>{classroom.student_count || 0}</span>
              <span>{classroom.active ? 'Active' : 'Inactive'}</span>
              <span><Link className="outline-button" to={`/professor/classrooms/${classroom.id}`}>Ouvrir</Link></span>
            </div>
          ))}
        </div>
        {!classrooms.length && <p className="admin-empty">Aucune classe créée.</p>}
      </article>
    </section>
  )
}

export default ProfessorClassroomsPage
