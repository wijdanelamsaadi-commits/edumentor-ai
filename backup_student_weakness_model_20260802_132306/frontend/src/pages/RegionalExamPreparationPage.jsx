import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRegionalExamPreparation, getRegionalExams } from '../services/api.js'

const EMPTY_REGIONAL_MESSAGE = "Aucun examen régional n'est encore disponible. Continuez vos cours et exercices en attendant une nouvelle évaluation."

const DEFAULT_FILTERS = {
  year: '',
  region: '',
  work_id: '',
  session: '',
  status: '',
  search: '',
}

function RegionalExamPreparationPage() {
  const [preparation, setPreparation] = useState(null)
  const [examData, setExamData] = useState(null)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      getRegionalExamPreparation(),
      getRegionalExams(cleanFilters(filters)),
    ])
      .then(([regionalPreparation, exams]) => {
        if (cancelled) return
        setPreparation(regionalPreparation)
        setExamData(exams)
        setMessage('')
      })
      .catch((error) => {
        if (!cancelled) {
          setMessage(error?.message || 'Préparation régionale indisponible.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [filters])

  const exams = Array.isArray(examData?.exams) ? examData.exams : []
  const stats = examData?.stats || preparation?.regional_exam_stats || {}
  const options = examData?.filters || {}
  const works = useMemo(() => (
    Array.isArray(preparation?.works) ? preparation.works : []
  ), [preparation?.works])
  const weakPoints = Array.isArray(preparation?.weak_points) ? preparation.weak_points : []
  const progression = preparation?.progression || {}
  const readiness = preparation?.readiness || {}

  const workOptions = useMemo(() => {
    const fromExams = Array.isArray(options.works)
      ? options.works.map((item) => ({ id: item[0] || item[1], title: item[1] || item[0] })).filter((item) => item.id)
      : []
    if (fromExams.length) return fromExams
    return works.map((work) => ({ id: work.id, title: work.title }))
  }, [options.works, works])

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Préparation au régional de français</h1>
        <p>1ère Bac Maroc - examens, entraînements et suivi de progression.</p>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <Metric label="Examens disponibles" value={stats.total_exams || 0} hint={`${stats.completed_exams || 0} terminé(s)`} />
        <Metric label="Préparation estimée" value={`${Math.round(Number(readiness.score || 0))}%`} hint={readiness.certainty || 'Non prédictif'} />
        <Metric label="Meilleur score" value={stats.best_score === null || stats.best_score === undefined ? '--' : `${Math.round(Number(stats.best_score))}%`} hint={`${stats.attempts_count || 0} tentative(s)`} />
        <Metric label="Chapitres terminés" value={progression.chapters_completed || 0} hint={`${Math.round(Number(progression.global || 0))}% global`} />
      </div>

      <article className="panel-card">
        <div className="panel-title">
          <h2>Filtres</h2>
          <p>{exams.length} résultat(s)</p>
        </div>
        <div className="admin-form-row">
          <label>Recherche
            <input value={filters.search} onChange={(event) => updateFilter(setFilters, 'search', event.target.value)} placeholder="Titre, œuvre, région..." />
          </label>
          <label>Année
            <SelectFilter name="year" options={options.years} value={filters.year} onChange={setFilters} />
          </label>
          <label>Région
            <SelectFilter name="region" options={options.regions} value={filters.region} onChange={setFilters} />
          </label>
        </div>
        <div className="admin-form-row">
          <label>Œuvre
            <select value={filters.work_id} onChange={(event) => updateFilter(setFilters, 'work_id', event.target.value)}>
              <option value="">Toutes</option>
              {workOptions.map((work) => <option key={`${work.id}-${work.title}`} value={work.id}>{work.title}</option>)}
            </select>
          </label>
          <label>Session
            <SelectFilter name="session" options={options.sessions} value={filters.session} onChange={setFilters} />
          </label>
          <label>Statut
            <SelectFilter name="status" options={options.statuses} value={filters.status} onChange={setFilters} />
          </label>
        </div>
      </article>

      <article className="panel-card">
        <div className="panel-title">
          <h2>Examens disponibles</h2>
          <p>{loading ? 'Chargement...' : exams.length}</p>
        </div>
        {loading ? <p>Chargement...</p> : exams.length ? (
          <div className="course-grid">
            {exams.map((exam) => <RegionalExamCard exam={exam} key={exam.id} />)}
          </div>
        ) : <p className="admin-empty">{EMPTY_REGIONAL_MESSAGE}</p>}
      </article>

      <div className="dashboard-grid">
        <article className="panel-card">
          <div className="panel-title">
            <h2>Œuvres au programme</h2>
            <p>{works.length}</p>
          </div>
          {works.length ? works.map((work) => (
            <div className="history-item" key={work.id}>
              <span>{work.chapters_count}</span>
              <div>
                <strong>{work.title}</strong>
                <p>{work.author || 'Auteur fourni par le package'} - {work.genre || 'Genre non précisé'}</p>
              </div>
            </div>
          )) : <p>Aucune œuvre importée pour le moment.</p>}
        </article>

        <article className="panel-card">
          <div className="panel-title">
            <h2>Points faibles</h2>
            <p>{weakPoints.length}</p>
          </div>
          {weakPoints.length ? weakPoints.map((point) => (
            <div className="history-item" key={`${point.assessment_id}-${point.competence || point.message}`}>
              <span>{Math.round(Number(point.score || 0))}%</span>
              <div>
                <strong>{point.competence || `Évaluation ${point.assessment_id}`}</strong>
                <p>{point.message}</p>
              </div>
            </div>
          )) : <p>Aucun point faible récent détecté.</p>}
        </article>
      </div>
    </section>
  )
}

function RegionalExamCard({ exam }) {
  return (
    <article className="course-card">
      <div className="course-card-top">
        <span className="course-badge">{exam.type_label || 'Entraînement pédagogique'}</span>
        <span className="course-badge">{exam.status}</span>
      </div>
      <h3>{exam.title}</h3>
      <p>{exam.description || exam.work_title || 'Sujet de préparation régional.'}</p>
      <div className="profile-detail-list">
        <div><span>Œuvre</span><strong>{exam.work_title || '--'}</strong></div>
        <div><span>Année</span><strong>{exam.year || '--'}</strong></div>
        <div><span>Région</span><strong>{exam.region || '--'}</strong></div>
        <div><span>Session</span><strong>{exam.session || '--'}</strong></div>
        <div><span>Durée</span><strong>{exam.duration_minutes ? `${exam.duration_minutes} min` : '--'}</strong></div>
        <div><span>Barème</span><strong>{exam.total_points || 0} pts</strong></div>
        <div><span>Questions</span><strong>{exam.question_count}</strong></div>
        <div><span>Meilleur score</span><strong>{exam.best_score === null || exam.best_score === undefined ? '--' : `${Math.round(Number(exam.best_score))}%`}</strong></div>
      </div>
      <div className="course-actions">
        <Link className="primary-button" to={`/regional-exam-preparation/${exam.id}`}>Ouvrir l'examen</Link>
      </div>
    </article>
  )
}

function Metric({ label, value, hint }) {
  return <article className="metric-card"><p>{label}</p><h2>{value}</h2><strong>{hint}</strong></article>
}

function SelectFilter({ name, onChange, options = [], value }) {
  return (
    <select value={value} onChange={(event) => updateFilter(onChange, name, event.target.value)}>
      <option value="">Tous</option>
      {options.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>
  )
}

function updateFilter(setFilters, key, value) {
  setFilters((current) => ({ ...current, [key]: value }))
}

function cleanFilters(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
}

export default RegionalExamPreparationPage
