import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ChevronDown, Clock, TrendingUp } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fetchCourses, fetchDifficultyLevels, fetchEducationLevels, fetchSubjects } from '../services/api.js'

function CoursesPage() {
  const navigate = useNavigate()
  const [courses, setCourses] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [diagnosticResult, setDiagnosticResult] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [educationLevels, setEducationLevels] = useState([])
  const [difficultyLevels, setDifficultyLevels] = useState([])
  const [filters, setFilters] = useState({ subject_slug: '', education_level_id: '', difficulty_level_id: '', search: '' })

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    Promise.all([
      fetchCourses(filters),
      fetchSubjects(),
      fetchEducationLevels(),
      fetchDifficultyLevels(),
    ])
      .then(([coursesData, subjectsData, educationData, difficultyData]) => {
        if (isMounted) {
          setCourses(Array.isArray(coursesData) ? coursesData : [])
          setSubjects(Array.isArray(subjectsData) ? subjectsData : [])
          setEducationLevels(Array.isArray(educationData) ? educationData : [])
          setDifficultyLevels(Array.isArray(difficultyData) ? difficultyData : [])
          setError('')
        }
      })
      .catch(() => {
        if (isMounted) {
          setError('Impossible de charger les cours depuis le backend.')
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [filters])

  const learnerLevel = diagnosticResult?.level || ''
  const visibleCourses = useMemo(
    () => dedupeCoursesById(courses),
    [courses],
  )
  const visibleDifficultyLevels = useMemo(
    () => mergeDifficultyLevels(difficultyLevels, visibleCourses),
    [difficultyLevels, visibleCourses],
  )

  if (isLoading) {
    return (
      <section className="page-section courses-page">
        <PageHeader />
        <article className="panel-card">
          <h2>Chargement des cours...</h2>
          <p>Les cours sont recuperes depuis le backend.</p>
        </article>
      </section>
    )
  }

  if (error) {
    return (
      <section className="page-section courses-page">
        <PageHeader />
        <article className="panel-card">
          <h2>Cours indisponibles</h2>
          <p>{error}</p>
        </article>
      </section>
    )
  }

  return (
    <section className="page-section courses-page">
      <PageHeader />

      <CourseFilters
        difficultyLevels={visibleDifficultyLevels}
        educationLevels={educationLevels}
        filters={filters}
        onChange={setFilters}
        subjects={subjects}
      />

      <div className="course-list">
        {visibleCourses.map((course) => (
          <article className="course-row" key={course.id}>
            <span className="course-icon"><BookOpen size={42} /></span>
            <div className="course-copy">
              <small>{course.tag || String(course.id).padStart(2, '0')}</small>
              <h2>{course.title}</h2>
              <span className="course-level-badge">Adapte a votre niveau : {course.level || learnerLevel || 'Adaptatif'}</span>
              <span className="course-level-badge">{course.subject?.name || 'Matiere non definie'}</span>
              {course.difficulty_level && <span className="course-level-badge">{course.difficulty_level.name}</span>}
              {course.education_level && <span className="course-level-badge">{course.education_level.name}</span>}
              <p>{course.summary}</p>
            </div>
            <div className="course-progress">
              <p>Progression</p>
              <h3>{course.progress}%</h3>
              <div className="progress-track"><span style={{ width: `${course.progress}%` }} /></div>
            </div>
            <div className="course-time"><Clock size={22} />{course.estimated_duration || course.duration}</div>
            <button
              aria-label={`Ouvrir ${course.title}`}
              className={course.progress > 0 ? 'primary-button' : 'outline-button'}
              onClick={() => navigate(`/courses/${course.id}`)}
              type="button"
            >
              {course.progress > 0 ? 'Continuer' : 'Commencer'}
            </button>
          </article>
        ))}
      </div>

      {visibleCourses.length === 0 && (
        <article className="panel-card">
          <h2>Aucun cours trouve</h2>
          <p>Aucun cours du backend ne correspond actuellement a vos filtres.</p>
        </article>
      )}

      <article className="progress-banner">
        <span><TrendingUp size={30} /></span>
        <div>
          <strong>{diagnosticResult ? <>Niveau diagnostique <em>{learnerLevel}</em></> : 'Test diagnostique non encore passe'}</strong>
          <p>{diagnosticResult ? 'Les cours affiches sont autorises pour votre parcours.' : 'Passez le test pour enrichir vos recommandations.'}</p>
        </div>
        <button className="outline-button" onClick={() => navigate(diagnosticResult ? '/profile' : '/diagnostic')} type="button">
          {diagnosticResult ? 'Voir ma progression' : 'Passer le test diagnostique'} {'->'}
        </button>
      </article>
    </section>
  )
}

function CourseFilters({ difficultyLevels, educationLevels, filters, onChange, subjects }) {
  function updateFilter(field, value) {
    onChange((current) => ({ ...current, [field]: value }))
  }

  return (
    <article className="panel-card admin-filters">
      <label className="admin-search">
        <input
          onChange={(event) => updateFilter('search', event.target.value)}
          placeholder="Rechercher un cours..."
          value={filters.search}
        />
      </label>
      <select onChange={(event) => updateFilter('subject_slug', event.target.value)} value={filters.subject_slug}>
        <option value="">Toutes les matieres</option>
        {subjects.map((subject) => <option key={subject.id} value={subject.slug}>{subject.name}</option>)}
      </select>
      <select onChange={(event) => updateFilter('education_level_id', event.target.value)} value={filters.education_level_id}>
        <option value="">Tous les niveaux d'etudes</option>
        {educationLevels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
      </select>
      <select onChange={(event) => updateFilter('difficulty_level_id', event.target.value)} value={filters.difficulty_level_id}>
        <option value="">Toutes les difficultes</option>
        {difficultyLevels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
      </select>
    </article>
  )
}

function PageHeader() {
  return (
    <div className="page-heading page-heading-row">
      <div>
        <h1>Mes cours</h1>
        <p>Continuez votre apprentissage et progressez chaque jour.</p>
      </div>
      <button className="sort-button" type="button">Trier par <strong>Ordre du cours</strong> <ChevronDown size={18} /></button>
    </div>
  )
}

function dedupeCoursesById(courses) {
  const seen = new Set()
  return courses.filter((course) => {
    const key = course?.id
    if (key === undefined || key === null) {
      return false
    }
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

function mergeDifficultyLevels(levels, courses) {
  const merged = new Map()

  levels.forEach((level) => {
    if (level?.id) {
      merged.set(String(level.id), level)
    }
  })

  courses.forEach((course) => {
    const level = course?.difficulty_level
    if (level?.id && !merged.has(String(level.id))) {
      merged.set(String(level.id), level)
    }
  })

  return Array.from(merged.values())
}

export default CoursesPage
