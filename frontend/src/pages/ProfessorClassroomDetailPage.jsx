import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  addProfessorClassroomStudent,
  getProfessorClassroom,
  removeProfessorClassroomStudent,
  updateProfessorClassroom,
} from '../services/api.js'

function ProfessorClassroomDetailPage() {
  const { id } = useParams()
  const [classroom, setClassroom] = useState(null)
  const [studentEmail, setStudentEmail] = useState('')
  const [message, setMessage] = useState('')

  const refreshClassroom = useCallback(() => {
    getProfessorClassroom(id)
      .then(setClassroom)
      .catch((err) => setMessage(err.message || 'Classe introuvable.'))
  }, [id])

  useEffect(() => {
    refreshClassroom()
  }, [refreshClassroom])

  async function addStudent() {
    try {
      await addProfessorClassroomStudent(id, { email: studentEmail })
      setStudentEmail('')
      setMessage('Étudiant ajouté.')
      refreshClassroom()
    } catch (err) {
      setMessage(err.message || 'Ajout impossible.')
    }
  }

  async function removeStudent(studentId) {
    if (!window.confirm('Retirer cet étudiant de la classe ?')) return
    try {
      await removeProfessorClassroomStudent(id, studentId)
      refreshClassroom()
    } catch (err) {
      setMessage(err.message || 'Suppression impossible.')
    }
  }

  async function toggleActive() {
    try {
      const updated = await updateProfessorClassroom(id, { active: !classroom.active })
      setClassroom(updated)
    } catch (err) {
      setMessage(err.message || 'Modification impossible.')
    }
  }

  if (!classroom) {
    return <section className="page-section admin-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{classroom.name}</h1>
          <p>Code classe : {classroom.code}</p>
        </div>
        <div className="admin-actions">
          <Link className="primary-button" to={`/professor/assessments/new?classroom_id=${classroom.id}`}>Créer une évaluation</Link>
          <button className="outline-button" onClick={toggleActive} type="button">{classroom.active ? 'Désactiver' : 'Activer'}</button>
        </div>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      <article className="panel-card admin-course-form">
        <h3>Ajouter un étudiant</h3>
        <div className="admin-form-row">
          <label>Email<input onChange={(event) => setStudentEmail(event.target.value)} value={studentEmail} /></label>
          <button className="primary-button" onClick={addStudent} type="button">Ajouter</button>
        </div>
      </article>
      <article className="panel-card">
        <div className="panel-title">
          <h2>Étudiants inscrits</h2>
          <p>{classroom.students?.length || 0} étudiants</p>
        </div>
        <div className="admin-table">
          <div className="admin-table-row admin-table-head"><span>Nom</span><span>Email</span><span>Inscription</span><span>Action</span></div>
          {(classroom.students || []).map((student) => (
            <div className="admin-table-row" key={student.id}>
              <span>{student.student_name}</span>
              <span>{student.email}</span>
              <span>{formatDate(student.joined_at)}</span>
              <span><button className="outline-button" onClick={() => removeStudent(student.student_id)} type="button">Retirer</button></span>
            </div>
          ))}
        </div>
        {!classroom.students?.length && <p className="admin-empty">Aucun étudiant inscrit.</p>}
      </article>
    </section>
  )
}

function formatDate(value) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('fr-FR').format(new Date(value))
}

export default ProfessorClassroomDetailPage
