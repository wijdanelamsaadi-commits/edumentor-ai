import { useEffect, useMemo, useState } from 'react'
import { BookOpen, ChevronDown, Clock, TrendingUp } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useLearning } from '../hooks/useLearning.js'

function CoursesPage() {
  const navigate = useNavigate()
  const { courses } = useLearning()
  const [diagnosticResult, setDiagnosticResult] = useState(null)

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
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
        <div className="page-heading page-heading-row">
          <div>
            <h1>Mes cours</h1>
            <p>Continuez votre apprentissage et progressez chaque jour.</p>
          </div>
          <button className="sort-button" type="button">Trier par <strong>Ordre du cours</strong> <ChevronDown size={18} /></button>
        </div>

        <article className="progress-banner">
          <span><TrendingUp size={30} /></span>
          <div>
            <strong>Test diagnostique non encore passé</strong>
            <p>Passez le test pour afficher les cours adaptés à votre niveau.</p>
          </div>
          <button className="outline-button" onClick={() => navigate('/diagnostic')} type="button">
            Passer le test diagnostique
          </button>
        </article>
      </section>
    )
  }

  return (
    <section className="page-section courses-page">
      <div className="page-heading page-heading-row">
        <div>
          <h1>Mes cours</h1>
          <p>Continuez votre apprentissage et progressez chaque jour.</p>
        </div>
        <button className="sort-button" type="button">Trier par <strong>Ordre du cours</strong> <ChevronDown size={18} /></button>
      </div>

      <div className="course-list">
        {adaptedCourses.map((course) => (
          <article className="course-row" key={course.id}>
            <span className="course-icon"><BookOpen size={42} /></span>
            <div className="course-copy">
              <small>{course.tag}</small>
              <h2>{course.title}</h2>
              <span className="course-level-badge">Adapté à votre niveau : {learnerLevel}</span>
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

      <article className="progress-banner">
        <span><TrendingUp size={30} /></span>
        <div>
          <strong>Niveau diagnostique <em>{learnerLevel}</em></strong>
          <p>Les cours affichés sont adaptés à votre résultat diagnostique.</p>
        </div>
        <button className="outline-button" onClick={() => navigate('/profile')} type="button">Voir ma progression →</button>
      </article>
    </section>
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
