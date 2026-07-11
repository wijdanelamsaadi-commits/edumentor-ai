import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ChevronDown, Clock, TrendingUp } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fetchCourses } from '../services/api.js'

function CoursesPage() {
  const navigate = useNavigate()
  const [courses, setCourses] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [diagnosticResult, setDiagnosticResult] = useState(null)

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

    fetchCourses()
      .then((data) => {
        if (isMounted) {
          setCourses(Array.isArray(data) ? data : [])
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
  }, [])

  const learnerLevel = diagnosticResult?.level || ''
  const normalizedLevel = normalizeLevel(learnerLevel)
  const adaptedCourses = useMemo(
    () => courses.filter((course) => normalizeLevel(course.level) === normalizedLevel),
    [courses, normalizedLevel],
  )

  if (!diagnosticResult) {
    return (
      <section className="page-section courses-page">
        <PageHeader />

        <article className="progress-banner">
          <span><TrendingUp size={30} /></span>
          <div>
            <strong>Test diagnostique non encore passe</strong>
            <p>Passez le test pour afficher les cours adaptes a votre niveau.</p>
          </div>
          <button className="outline-button" onClick={() => navigate('/diagnostic')} type="button">
            Passer le test diagnostique
          </button>
        </article>
      </section>
    )
  }

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

      <div className="course-list">
        {adaptedCourses.map((course) => (
          <article className="course-row" key={course.id}>
            <span className="course-icon"><BookOpen size={42} /></span>
            <div className="course-copy">
              <small>{course.tag || String(course.id).padStart(2, '0')}</small>
              <h2>{course.title}</h2>
              <span className="course-level-badge">Adapte a votre niveau : {learnerLevel}</span>
              <p>{course.summary}</p>
            </div>
            <div className="course-progress">
              <p>Progression</p>
              <h3>{course.progress}%</h3>
              <div className="progress-track"><span style={{ width: `${course.progress}%` }} /></div>
            </div>
            <div className="course-time"><Clock size={22} />{course.duration}</div>
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

      {adaptedCourses.length === 0 && (
        <article className="panel-card">
          <h2>Aucun cours adapte trouve</h2>
          <p>Aucun cours du backend ne correspond actuellement a votre niveau diagnostique.</p>
        </article>
      )}

      <article className="progress-banner">
        <span><TrendingUp size={30} /></span>
        <div>
          <strong>Niveau diagnostique <em>{learnerLevel}</em></strong>
          <p>Les cours affiches sont adaptes a votre resultat diagnostique.</p>
        </div>
        <button className="outline-button" onClick={() => navigate('/profile')} type="button">Voir ma progression {'->'}</button>
      </article>
    </section>
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

function normalizeLevel(level) {
  const normalized = String(level || '')
    .replace(/\u00c3\u00a9/g, 'e')
    .replace(/\u00c3\u00a8/g, 'e')
    .replace(/\u00c3\u00a0/g, 'a')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

  if (normalized.includes('debut')) return 'debutant'
  if (normalized.includes('avance') || normalized.includes('avanc')) return 'avance'
  return normalized.includes('inter') ? 'intermediaire' : ''
}

export default CoursesPage
