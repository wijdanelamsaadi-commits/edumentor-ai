import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createProfessorClassroom, fetchEducationLevels, fetchSubjects } from '../services/api.js'

function ProfessorClassroomFormPage() {
  const navigate = useNavigate()
  const [subjects, setSubjects] = useState([])
  const [levels, setLevels] = useState([])
  const [message, setMessage] = useState('')
  const [draft, setDraft] = useState({
    name: '',
    subject_id: '',
    education_level_id: '',
    academic_year: '2026',
    description: '',
    active: true,
  })

  useEffect(() => {
    Promise.all([fetchSubjects(), fetchEducationLevels()])
      .then(([subjectData, levelData]) => {
        setSubjects(subjectData)
        setLevels(levelData)
      })
      .catch(() => setMessage('Impossible de charger les listes.'))
  }, [])

  async function saveClassroom() {
    try {
      const saved = await createProfessorClassroom({
        ...draft,
        subject_id: Number(draft.subject_id) || null,
        education_level_id: Number(draft.education_level_id) || null,
      })
      navigate(`/professor/classrooms/${saved.id}`)
    } catch (err) {
      setMessage(err.message || 'Création impossible.')
    }
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Nouvelle classe</h1>
          <p>Créer un groupe pour assigner des évaluations.</p>
        </div>
        <Link className="outline-button" to="/professor/classrooms">Retour</Link>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      <article className="panel-card admin-course-form">
        <label>Nom<input onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))} value={draft.name} /></label>
        <div className="admin-form-row">
          <label>Matière<select onChange={(event) => setDraft((prev) => ({ ...prev, subject_id: event.target.value }))} value={draft.subject_id}>
            <option value="">Non définie</option>
            {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
          </select></label>
          <label>Niveau scolaire<select onChange={(event) => setDraft((prev) => ({ ...prev, education_level_id: event.target.value }))} value={draft.education_level_id}>
            <option value="">Non défini</option>
            {levels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
          </select></label>
          <label>Année<input onChange={(event) => setDraft((prev) => ({ ...prev, academic_year: event.target.value }))} value={draft.academic_year} /></label>
        </div>
        <label>Description<textarea onChange={(event) => setDraft((prev) => ({ ...prev, description: event.target.value }))} value={draft.description} /></label>
        <button className="primary-button" onClick={saveClassroom} type="button">Créer la classe</button>
      </article>
    </section>
  )
}

export default ProfessorClassroomFormPage
