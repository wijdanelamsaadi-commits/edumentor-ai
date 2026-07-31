import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getRegionalExamPreparation } from '../services/api.js'

const EMPTY_REGIONAL_MESSAGE = "Aucun examen régional n'est encore disponible. Continuez vos cours et exercices en attendant une nouvelle évaluation."

function RegionalExamPreparationPage() {
  const [data, setData] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false

    getRegionalExamPreparation()
      .then((regionalData) => {
        if (!cancelled) {
          setData(regionalData)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setMessage(error?.message || 'Préparation régionale indisponible.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (!data) {
    return (
      <section className="page-section dashboard-page">
        <article className="panel-card">
          <p>{message || 'Chargement...'}</p>
        </article>
      </section>
    )
  }

  const works = Array.isArray(data.works) ? data.works : []
  const weakPoints = Array.isArray(data.weak_points) ? data.weak_points : []
  const progression = data.progression || {}
  const readiness = data.readiness || {}
  const hasPedagogicalData = Boolean(
    data.next_mock_exam ||
    data.study_path ||
    works.length ||
    weakPoints.length ||
    Number(progression.chapters_completed || 0) > 0
  )

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Préparation au régional de français</h1>
        <p>1ère Bac Maroc - indicateur pédagogique basé sur vos données d'apprentissage.</p>
      </div>

      {!hasPedagogicalData && (
        <article className="panel-card">
          <p>{EMPTY_REGIONAL_MESSAGE}</p>
        </article>
      )}

      <div className="dashboard-stats">
        <article className="metric-card">
          <p>Jours restants</p>
          <h2>{data.days_remaining ?? '--'}</h2>
          <strong>Selon la date renseignée</strong>
        </article>
        <article className="metric-card">
          <p>Préparation estimée</p>
          <h2>{Math.round(Number(readiness.score || 0))}%</h2>
          <strong>{readiness.certainty || 'Non prédictif'}</strong>
        </article>
        <article className="metric-card">
          <p>Chapitres terminés</p>
          <h2>{progression.chapters_completed || 0}</h2>
          <strong>{Math.round(Number(progression.global || 0))}% global</strong>
        </article>
      </div>

      <article className="panel-card">
        <div className="panel-title">
          <h2>Œuvres au programme importées</h2>
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
          <h2>Prochaine étape</h2>
          <p>Guide</p>
        </div>
        {data.study_path ? (
          <div className="history-item">
            <span>{Math.round(Number(data.study_path.progress_percentage || 0))}%</span>
            <div>
              <strong>{data.study_path.title}</strong>
              <p>Continuez votre parcours personnalisé.</p>
            </div>
            <Link to={`/study-paths/${data.study_path.id}`}>Continuer</Link>
          </div>
        ) : data.next_mock_exam ? (
          <div className="history-item">
            <span>Test</span>
            <div>
              <strong>{data.next_mock_exam.title}</strong>
              <p>{data.next_mock_exam.status}</p>
            </div>
            <Link to={`/assessments/${data.next_mock_exam.id}`}>Commencer</Link>
          </div>
        ) : <p>{EMPTY_REGIONAL_MESSAGE}</p>}
      </article>

      <article className="panel-card">
        <div className="panel-title">
          <h2>Points faibles</h2>
          <p>{weakPoints.length}</p>
        </div>
        {weakPoints.length ? weakPoints.map((point) => (
          <div className="history-item" key={point.assessment_id}>
            <span>{Math.round(Number(point.score || 0))}%</span>
            <div>
              <strong>Évaluation {point.assessment_id}</strong>
              <p>{point.message}</p>
            </div>
          </div>
        )) : <p>Aucun point faible récent détecté.</p>}
      </article>
    </section>
  )
}

export default RegionalExamPreparationPage
