import { Link, useParams } from 'react-router-dom'
import { Search, Users } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { getProfessorCourse, getProfessorCourseAnalytics, getProfessorCourseStudents } from '../services/api.js'

function ProfessorCourseStudentsPage() {
  const { id } = useParams()
  const [course, setCourse] = useState(null)
  const [students, setStudents] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [search, setSearch] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    Promise.all([getProfessorCourse(id), getProfessorCourseStudents(id), getProfessorCourseAnalytics(id)])
      .then(([courseData, studentsData, analyticsData]) => {
        setCourse(courseData)
        setStudents(studentsData)
        setAnalytics(analyticsData)
      })
      .catch((err) => setMessage(err.message || 'Impossible de charger les résultats.'))
  }, [id])

  const filteredStudents = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return students
    return students.filter((student) => `${student.full_name} ${student.email}`.toLowerCase().includes(needle))
  }, [search, students])

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Étudiants / Résultats</h1>
          <p>{course?.title || 'Activité réelle des étudiants sur ce cours.'}</p>
        </div>
        <Link className="outline-button" to="/professor/courses">Retour aux cours</Link>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <Stat label="Étudiants actifs" value={analytics?.active_students || 0} />
        <Stat label="Progression moyenne" value={`${analytics?.average_progress || 0}%`} />
        <Stat label="Score moyen" value={`${analytics?.average_score || 0}%`} />
      </div>

      <article className="panel-card admin-users-panel">
        <div className="admin-filters">
          <label className="admin-search"><Search size={18} /><input onChange={(event) => setSearch(event.target.value)} placeholder="Rechercher un étudiant..." value={search} /></label>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Étudiant</th>
                <th>Progression</th>
                <th>Score moyen</th>
                <th>Quiz réalisés</th>
                <th>Dernière activité</th>
              </tr>
            </thead>
            <tbody>
              {filteredStudents.map((student) => (
                <tr key={student.student_id}>
                  <td><strong>{student.full_name}</strong><span>{student.email}</span></td>
                  <td>{student.progression}%</td>
                  <td>{student.average_score}%</td>
                  <td>{student.quiz_attempts}</td>
                  <td>{student.last_activity ? new Date(student.last_activity).toLocaleString('fr-FR') : '--'}</td>
                </tr>
              ))}
              {!filteredStudents.length && <tr><td colSpan="5">Aucune activité étudiante sur ce cours.</td></tr>}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  )
}

function Stat({ label, value }) {
  return (
    <article className="stat-card">
      <span><Users size={22} /></span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>Données du cours</p>
      </div>
    </article>
  )
}

export default ProfessorCourseStudentsPage
