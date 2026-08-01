import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, BarChart3, BookOpen, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getProfessorCourse } from '../services/api.js'

function ProfessorCourseViewPage() {
  const { id } = useParams()
  const [course, setCourse] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let ignore = false
    getProfessorCourse(id)
      .then((data) => {
        if (!ignore) setCourse(data)
      })
      .catch((err) => {
        if (!ignore) setError(err.message || 'Cours introuvable.')
      })
    return () => {
      ignore = true
    }
  }, [id])

  if (error) {
    return (
      <section className="page-section">
        <article className="panel-card">
          <h1>Cours introuvable</h1>
          <p>{error}</p>
          <Link className="outline-button" to="/professor/courses">Retour aux cours</Link>
        </article>
      </section>
    )
  }

  if (!course) {
    return <section className="page-section"><article className="panel-card">Chargement...</article></section>
  }

  const chapters = Array.isArray(course.chapters) ? course.chapters : []
  const objectives = Array.isArray(course.objectives) ? course.objectives : []
  const skills = Array.isArray(course.skills) ? course.skills : []
  const examples = Array.isArray(course.examples) ? course.examples : []

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{course.title}</h1>
          <p>{course.summary || course.description || 'Cours importé automatiquement.'}</p>
        </div>
        <div className="admin-actions">
          <Link className="outline-button" to="/professor/courses"><ArrowLeft size={16} /> Retour</Link>
          <Link className="outline-button" to={`/professor/courses/${course.id}/students`}><Users size={16} /> Étudiants</Link>
          <Link className="outline-button" to={`/professor/analytics?course_id=${course.id}`}><BarChart3 size={16} /> Statistiques</Link>
        </div>
      </div>

      <div className="dashboard-stats">
        <MiniStat label="Statut" value={course.status || (course.published ? 'published' : 'draft')} />
        <MiniStat label="Chapitres" value={chapters.length} />
        <MiniStat label="Étudiants" value={course.student_count || 0} />
        <MiniStat label="Quiz" value={course.quiz_count || 0} />
      </div>

      <div className="dashboard-grid">
        <article className="panel-card">
          <div className="panel-title"><h2>Informations</h2></div>
          <p>{course.description || course.summary || '--'}</p>
          <ul>
            <li><strong>Matière</strong> : {course.subject?.name || '--'}</li>
            <li><strong>Niveau</strong> : {course.education_level?.name || course.level || '--'}</li>
            <li><strong>Durée</strong> : {course.duration || course.estimated_duration || '--'}</li>
          </ul>
        </article>

        <article className="panel-card">
          <div className="panel-title"><h2>Objectifs</h2></div>
          {objectives.length ? <ul>{objectives.map((item, index) => <li key={`${index}-${item.text || item}`}>{item.text || item}</li>)}</ul> : <p className="admin-empty">Aucun objectif renseigné.</p>}
        </article>
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Chapitres</h2></div>
        {chapters.length ? chapters.map((chapter) => (
          <div className="history-item" key={chapter.id}>
            <span><BookOpen size={18} /></span>
            <div>
              <strong>{chapter.title}</strong>
              <p>{chapter.duration || chapter.estimated_duration || '--'} · {chapter.status || '--'}</p>
            </div>
          </div>
        )) : <p className="admin-empty">Aucun chapitre importé.</p>}
      </article>

      <div className="dashboard-grid">
        <article className="panel-card">
          <div className="panel-title"><h2>Compétences</h2></div>
          {skills.length ? <ul>{skills.map((item, index) => <li key={`${index}-${item.text || item}`}>{item.text || item}</li>)}</ul> : <p className="admin-empty">Aucune compétence renseignée.</p>}
        </article>

        <article className="panel-card">
          <div className="panel-title"><h2>Exemples</h2></div>
          {examples.length ? <ul>{examples.map((item, index) => <li key={`${index}-${item.title || item.description || item}`}>{item.title || item.description || item}</li>)}</ul> : <p className="admin-empty">Aucun exemple renseigné.</p>}
        </article>
      </div>
    </section>
  )
}

function MiniStat({ label, value }) {
  return (
    <article className="stat-card">
      <span><BookOpen size={22} /></span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>Lecture seule</p>
      </div>
    </article>
  )
}

export default ProfessorCourseViewPage
