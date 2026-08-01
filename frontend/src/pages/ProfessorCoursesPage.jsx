import { Link } from 'react-router-dom'
import { Archive, BarChart3, BookOpen, Eye, Search, Trash2, Users } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  archiveProfessorCourse,
  deleteProfessorCourse,
  fetchDifficultyLevels,
  fetchEducationLevels,
  fetchSubjects,
  getProfessorCourses,
  publishProfessorCourse,
  unpublishProfessorCourse,
} from '../services/api.js'

function ProfessorCoursesPage() {
  const [courses, setCourses] = useState([])
  const [subjects, setSubjects] = useState([])
  const [educationLevels, setEducationLevels] = useState([])
  const [difficultyLevels, setDifficultyLevels] = useState([])
  const [filters, setFilters] = useState({ search: '', subject_id: 'all', education_level_id: 'all', difficulty_level_id: 'all', status: 'all' })
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([fetchSubjects(), fetchEducationLevels(), fetchDifficultyLevels()])
      .then(([subjectData, levelData, difficultyData]) => {
        setSubjects(subjectData)
        setEducationLevels(levelData)
        setDifficultyLevels(difficultyData)
      })
      .catch(() => setMessage('Impossible de charger les filtres.'))
  }, [])

  useEffect(() => {
    let ignore = false
    setLoading(true)
    getProfessorCourses(filters)
      .then((data) => {
        if (!ignore) setCourses(Array.isArray(data) ? data : [])
      })
      .catch((err) => {
        if (!ignore) setMessage(err.message || 'Impossible de charger vos cours.')
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })
    return () => {
      ignore = true
    }
  }, [filters])

  const stats = useMemo(() => ({
    total: courses.length,
    published: courses.filter((course) => course.published).length,
    draft: courses.filter((course) => !course.published && course.status !== 'archived').length,
    archived: courses.filter((course) => course.status === 'archived').length,
  }), [courses])

  async function reloadCourses(successMessage) {
    const fresh = await getProfessorCourses(filters)
    setCourses(Array.isArray(fresh) ? fresh : [])
    setMessage(successMessage)
  }

  async function handleStatus(course, action) {
    try {
      if (action === 'publish') await publishProfessorCourse(course.id)
      if (action === 'unpublish') await unpublishProfessorCourse(course.id)
      if (action === 'archive') await archiveProfessorCourse(course.id)
      const labels = {
        publish: 'Cours publié avec succès.',
        unpublish: 'Cours dépublié avec succès.',
        archive: 'Cours archivé avec succès.',
      }
      await reloadCourses(labels[action] || 'Action effectuée avec succès.')
    } catch (err) {
      setMessage(err.message || "L'action a échoué.")
    }
  }

  async function handleDelete(course) {
    const confirmed = window.confirm(
      `Supprimer le cours "${course.title}" ?\n\nCette action est définitive si le cours ne contient pas encore d'activité. Si des progressions ou résultats existent, le cours sera archivé et dépublié.`
    )
    if (!confirmed) return
    try {
      const result = await deleteProfessorCourse(course.id)
      await reloadCourses(result.archived ? 'Cours archivé et dépublié car il contient déjà des activités.' : 'Cours supprimé avec succès.')
    } catch (err) {
      setMessage(err.message || 'Suppression impossible.')
    }
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Mes cours</h1>
          <p>Consultez, publiez et suivez uniquement les cours créés par import automatique.</p>
        </div>
        <Link className="primary-button" to="/professor/courses/automatic-import">Importer un nouveau cours</Link>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <MiniStat label="Total" value={stats.total} />
        <MiniStat label="Publiés" value={stats.published} />
        <MiniStat label="Brouillons" value={stats.draft} />
        <MiniStat label="Archivés" value={stats.archived} />
      </div>

      <article className="panel-card admin-users-panel">
        <div className="admin-filters">
          <label className="admin-search"><Search size={18} /><input aria-label="Recherche cours" onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} placeholder="Rechercher..." value={filters.search} /></label>
          <SelectFilter label="Matière" options={subjects} value={filters.subject_id} onChange={(value) => setFilters((prev) => ({ ...prev, subject_id: value }))} />
          <SelectFilter label="Niveau" options={educationLevels} value={filters.education_level_id} onChange={(value) => setFilters((prev) => ({ ...prev, education_level_id: value }))} />
          <SelectFilter label="Difficulté" options={difficultyLevels} value={filters.difficulty_level_id} onChange={(value) => setFilters((prev) => ({ ...prev, difficulty_level_id: value }))} />
          <select onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))} value={filters.status}>
            <option value="all">Tous les statuts</option>
            <option value="draft">Brouillon</option>
            <option value="published">Publié</option>
            <option value="archived">Archivé</option>
          </select>
        </div>

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Cours</th>
                <th>Matière</th>
                <th>Niveau</th>
                <th>Statut</th>
                <th>Activité</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan="6">Chargement...</td></tr>}
              {!loading && courses.map((course) => (
                <tr key={course.id}>
                  <td><strong>{course.title}</strong><span>{course.summary || course.description || '--'}</span></td>
                  <td>{course.subject?.name || '--'}</td>
                  <td>{course.education_level?.name || course.level}</td>
                  <td><em className="admin-pill">{course.status || (course.published ? 'published' : 'draft')}</em></td>
                  <td>{course.chapter_count || course.chapters?.length || 0} chapitres<span>{course.student_count || 0} étudiants · {course.quiz_count || 0} quiz</span></td>
                  <td>
                    <div className="admin-actions">
                      <Link to={`/professor/courses/${course.id}`}><BookOpen size={15} /> Voir le cours</Link>
                      <Link to={`/professor/courses/${course.id}/students`}><Users size={15} /> Étudiants</Link>
                      <Link to={`/professor/analytics?course_id=${course.id}`}><BarChart3 size={15} /> Statistiques</Link>
                      {course.published ? <button onClick={() => handleStatus(course, 'unpublish')} type="button"><Eye size={15} /> Dépublier</button> : <button onClick={() => handleStatus(course, 'publish')} type="button"><Eye size={15} /> Publier</button>}
                      <button onClick={() => handleStatus(course, 'archive')} type="button"><Archive size={15} /> Archiver</button>
                      <button onClick={() => handleDelete(course)} type="button"><Trash2 size={15} /> Supprimer</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && !courses.length && <tr><td colSpan="6">Aucun cours professeur trouvé.</td></tr>}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  )
}

function SelectFilter({ label, options, value, onChange }) {
  return (
    <select aria-label={label} onChange={(event) => onChange(event.target.value)} value={value}>
      <option value="all">{label}</option>
      {options.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
    </select>
  )
}

function MiniStat({ label, value }) {
  return (
    <article className="stat-card">
      <span><BookOpen size={22} /></span>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
        <p>Données PostgreSQL</p>
      </div>
    </article>
  )
}

export default ProfessorCoursesPage
