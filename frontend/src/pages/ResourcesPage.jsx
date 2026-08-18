import { BookOpen, Clock, Download, Eye, FileText, Layers, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_BASE_URL, fetchCourses, fetchSubjects } from '../services/api.js'
import { addNotification } from '../services/notifications.js'

const CHAPTER_PROGRESS_STORAGE_KEY = 'edumentor:chapterProgress'
const FILTERS = ['Tous', 'Débutant', 'Intermédiaire', 'Avancé']

function ResourcesPage() {
  const navigate = useNavigate()
  const [courses, setCourses] = useState([])
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState('Tous')
  const [activeSubject, setActiveSubject] = useState('')
  const [subjects, setSubjects] = useState([])
  const [selectedCourse, setSelectedCourse] = useState(null)
  const [progressMap, setProgressMap] = useState({})
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setProgressMap(readLocalStorage(CHAPTER_PROGRESS_STORAGE_KEY, {}))
  }, [])

  useEffect(() => {
    let isMounted = true

    Promise.all([fetchCourses({ subject_slug: activeSubject }), fetchSubjects()])
      .then(([data, subjectsData]) => {
        if (isMounted) {
          setCourses(Array.isArray(data) ? data : [])
          setSubjects(Array.isArray(subjectsData) ? subjectsData : [])
          setError('')
        }
      })
      .catch(() => {
        if (isMounted) {
          setError('Impossible de charger les ressources depuis le backend.')
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
  }, [activeSubject])

  const resources = useMemo(
    () => courses.map((course) => enrichCourse(course, progressMap[course.id])),
    [courses, progressMap],
  )
  const filteredResources = useMemo(
    () => resources.filter((course) => matchesFilter(course, activeFilter) && matchesSearch(course, query)),
    [activeFilter, query, resources],
  )
  const stats = useMemo(() => buildStats(resources), [resources])

  function downloadPdf(course) {
    if (!course.pdf_url) return

    window.open(resolvePdfUrl(course.pdf_url), '_blank', 'noopener,noreferrer')
    addNotification({
      type: 'pdf',
      title: 'Support PDF téléchargé',
      message: `Le support PDF du cours ${course.title} a été ouvert.`,
    })
  }

  return (
    <section className="page-section resources-page">
      <div className="page-heading page-heading-row">
        <div>
          <h1>Ressources</h1>
          <p>Bibliothèque pédagogique des supports EduMentor AI.</p>
        </div>
      </div>

      <div className="resources-stats dashboard-stats">
        <StatCard label="Supports" value={stats.totalSupports} />
        <StatCard label="Chapitres" value={stats.totalChapters} />
        <StatCard label="Temps total" value={stats.totalDuration} />
        <StatCard label="Cours commencés" value={stats.startedCourses} />
      </div>

      <article className="panel-card resources-controls">
        <label className="resource-search">
          <Search size={20} />
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Rechercher par titre, description ou niveau..."
            value={query}
          />
        </label>
        <div className="resource-filters">
          {FILTERS.map((filter) => (
            <button
              className={activeFilter === filter ? 'active' : ''}
              key={filter}
              onClick={() => setActiveFilter(filter)}
              type="button"
            >
              {filter}
            </button>
          ))}
          <select onChange={(event) => setActiveSubject(event.target.value)} value={activeSubject}>
            <option value="">Toutes les matieres</option>
            {subjects.map((subject) => <option key={subject.id} value={subject.slug}>{subject.name}</option>)}
          </select>
        </div>
      </article>

      {isLoading && <article className="panel-card"><h2>Chargement des ressources...</h2></article>}
      {error && <article className="panel-card"><h2>Ressources indisponibles</h2><p>{error}</p></article>}

      {!isLoading && !error && (
        <div className="resources-grid">
          {filteredResources.map((course) => (
            <article className="resource-card panel-card" key={course.id}>
              <div className="resource-card-top">
                <span className="resource-pdf-icon"><FileText size={34} /></span>
                <div>
                  <small>{course.level}</small>
                  <small>{course.subject?.name || 'Matiere non definie'}</small>
                  <h2>{course.title}</h2>
                </div>
              </div>
              <p>{course.summary}</p>
              <div className="resource-meta">
                <span><Clock size={17} />{course.duration}</span>
                <span><Layers size={17} />{course.chapterCount} chapitres</span>
                <span>MAJ {course.lastUpdate}</span>
              </div>
              {course.progress > 0 && (
                <div className="resource-progress">
                  <span>Progression actuelle</span>
                  <div className="progress-track"><span style={{ width: `${course.progress}%` }} /></div>
                  <strong>{course.progress}%</strong>
                </div>
              )}
              <div className="resource-actions">
                <button className="outline-button" onClick={() => setSelectedCourse(course)} type="button">
                  <Eye size={18} />
                  Aperçu
                </button>
                <button className="outline-button" onClick={() => navigate(`/courses/${course.id}`)} type="button">
                  <BookOpen size={18} />
                  Ouvrir le cours
                </button>
                <button className="primary-button" disabled={!course.pdf_url} onClick={() => downloadPdf(course)} type="button">
                  <Download size={18} />
                  Télécharger le PDF
                </button>
              </div>
            </article>
          ))}
        </div>
      )}

      {!isLoading && !error && filteredResources.length === 0 && (
        <article className="panel-card">
          <h2>Aucune ressource trouvée</h2>
          <p>Essayez un autre mot-clé ou un autre filtre.</p>
        </article>
      )}

      {selectedCourse && (
        <ResourcePreviewModal course={selectedCourse} onClose={() => setSelectedCourse(null)} />
      )}
    </section>
  )
}

function StatCard({ label, value }) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <h2>{value}</h2>
    </article>
  )
}

function ResourcePreviewModal({ course, onClose }) {
  return (
    <div className="resource-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <article className="resource-modal panel-card" onMouseDown={(event) => event.stopPropagation()}>
        <div className="resource-modal-header">
          <div>
            <p>{course.level}</p>
            <h2>{course.title}</h2>
          </div>
          <button className="icon-button" onClick={onClose} type="button" aria-label="Fermer l'aperçu">
            <X size={20} />
          </button>
        </div>
        <section>
          <h3>Résumé</h3>
          <p>{course.summary}</p>
        </section>
        <section>
          <h3>Objectifs</h3>
          <ul>{course.objectives.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
        <section>
          <h3>Chapitres</h3>
          <ul>{course.chapters.map((chapter) => <li key={chapter.title}>{chapter.title} · {chapter.duration}</li>)}</ul>
        </section>
        <section>
          <h3>Compétences acquises</h3>
          <ul>{course.skills.map((skill) => <li key={skill}>{skill}</li>)}</ul>
        </section>
      </article>
    </div>
  )
}

function enrichCourse(course, savedProgress) {
  const information = course.information || {}
  const chapters = Array.isArray(course.chapters) ? course.chapters : []
  const progress = Number(savedProgress?.progress ?? course.progress ?? 0)

  return {
    ...course,
    chapterCount: information.chapter_count ?? information.chapters_count ?? chapters.length,
    chapters,
    description: course.description || course.summary || '',
    duration: information.duration || course.duration || '-',
    lastUpdate: information.last_update || course.last_update || '-',
    level: information.level || course.level || 'Tous',
    objectives: Array.isArray(course.objectives) ? course.objectives : [],
    progress,
    skills: Array.isArray(course.skills) ? course.skills : [],
    summary: course.summary || course.description || '',
  }
}

function matchesFilter(course, filter) {
  if (filter === 'Tous') return true
  return normalizeText(course.level) === normalizeText(filter)
}

function matchesSearch(course, query) {
  const normalizedQuery = normalizeText(query)
  if (!normalizedQuery) return true
  return normalizeText(`${course.title} ${course.description} ${course.summary} ${course.level}`).includes(normalizedQuery)
}

function buildStats(resources) {
  const totalMinutes = resources.reduce((sum, course) => sum + parseDurationToMinutes(course.duration), 0)
  return {
    totalSupports: resources.length,
    totalChapters: resources.reduce((sum, course) => sum + Number(course.chapterCount || 0), 0),
    totalDuration: formatDuration(totalMinutes),
    startedCourses: resources.filter((course) => course.progress > 0).length,
  }
}

function parseDurationToMinutes(duration) {
  const text = String(duration || '').toLowerCase()
  const hoursMatch = text.match(/(\d+)\s*h/)
  const minutesMatch = text.match(/(\d+)\s*min/)
  return (hoursMatch ? Number(hoursMatch[1]) * 60 : 0) + (minutesMatch ? Number(minutesMatch[1]) : 0)
}

function formatDuration(totalMinutes) {
  if (!totalMinutes) return '-'
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (!hours) return `${minutes} min`
  return minutes ? `${hours}h ${minutes}min` : `${hours}h`
}

function resolvePdfUrl(pdfUrl) {
  if (pdfUrl.startsWith('http')) return pdfUrl
  return `${API_BASE_URL}${pdfUrl}`
}

function readLocalStorage(key, fallback) {
  try {
    const storedValue = localStorage.getItem(key)
    return storedValue ? JSON.parse(storedValue) : fallback
  } catch {
    return fallback
  }
}

function normalizeText(value) {
  return String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
}

export default ResourcesPage
