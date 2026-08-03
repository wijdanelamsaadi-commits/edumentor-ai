import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { completeStudyPathItem, getStudyPath, refreshStudyPath, skipStudyPathItem, startStudyPathItem } from '../services/api.js'

function StudyPathPage() {
  const { pathId } = useParams()
  const navigate = useNavigate()
  const [path, setPath] = useState(null)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getStudyPath(pathId)
      .then(setPath)
      .catch((err) => setMessage(err.message || 'Parcours indisponible.'))
      .finally(() => setLoading(false))
  }, [pathId])

  useEffect(() => {
    load()
  }, [load])

  async function start(item) {
    try {
      const updated = await startStudyPathItem(pathId, item.id)
      setPath(updated)
      if (item.route) navigate(item.route)
    } catch (err) {
      setMessage(err.message || 'Etape indisponible.')
    }
  }

  async function complete(item) {
    try {
      setPath(await completeStudyPathItem(pathId, item.id))
    } catch (err) {
      setMessage(err.message || 'Impossible de terminer cette etape.')
    }
  }

  async function skip(item) {
    try {
      setPath(await skipStudyPathItem(pathId, item.id))
    } catch (err) {
      setMessage(err.message || "Impossible d'ignorer cette etape.")
    }
  }

  async function refresh() {
    try {
      setPath(await refreshStudyPath(pathId))
      setMessage('Parcours mis a jour.')
    } catch (err) {
      setMessage(err.message || 'Actualisation impossible.')
    }
  }

  if (loading) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>Chargement...</p></article></section>
  }

  if (!path) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Parcours introuvable.'}</p></article></section>
  }

  const current = path.current_item

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{path.title}</h1>
          <p>{path.reason}</p>
        </div>
        <div className="admin-actions">
          <Link className="outline-button" to="/dashboard">Dashboard</Link>
          <button className="outline-button" onClick={refresh} type="button">Actualiser</button>
        </div>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <article className="continue-card">
        <div>
          <h2>Mon parcours actuel</h2>
          <h3>{path.course_title}</h3>
          <p>{path.subject_name || 'Matiere'} - {path.progress?.completed_items || 0}/{path.progress?.required_items || 0} etapes obligatoires terminees</p>
          <div className="inline-progress">
            <div className="progress-track"><span style={{ width: `${path.progress_percentage}%` }} /></div>
            <strong>{Math.round(path.progress_percentage)}%</strong>
          </div>
          {path.progress?.blocked_reason && <p>{path.progress.blocked_reason}</p>}
        </div>
        <button className="primary-button" disabled={!current || current.status === 'locked'} onClick={() => current && start(current)} type="button">
          Continuer mon parcours
        </button>
      </article>

      <div className="dashboard-stats">
        <article className="metric-card"><p>Total etapes</p><h2>{path.progress?.total_items || 0}</h2><strong>{path.progress?.estimated_remaining_steps || 0} restantes</strong></article>
        <article className="metric-card"><p>Etape actuelle</p><h2>{current ? current.order_index : '--'}</h2><strong>{current?.title || 'Aucune etape disponible'}</strong></article>
        <article className="metric-card"><p>Statut</p><h2>{path.status}</h2><strong>{path.comparison_available ? 'Comparaison disponible' : 'En progression'}</strong></article>
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Etapes ordonnees</h2><p>{path.items?.length || 0}</p></div>
        {(path.items || []).map((item) => (
          <div className="history-item" key={item.id}>
            <span>{item.status === 'completed' ? 'OK' : item.order_index}</span>
            <div>
              <strong>{item.title}</strong>
              <p>{item.description}</p>
              <small>{labelType(item.item_type)} - {item.status} - {item.required ? 'obligatoire' : 'facultatif'}</small>
              {item.reason && <p>{item.reason}</p>}
            </div>
            <div className="admin-actions">
              {item.route && <button disabled={item.status === 'locked'} onClick={() => start(item)} type="button">Ouvrir</button>}
              {item.status !== 'completed' && <button disabled={item.status === 'locked'} onClick={() => complete(item)} type="button">Terminer</button>}
              {!item.required && item.status !== 'completed' && <button disabled={item.status === 'locked'} onClick={() => skip(item)} type="button">Ignorer</button>}
            </div>
          </div>
        ))}
      </article>
    </section>
  )
}

function labelType(type) {
  const labels = {
    review_chapter: 'Chapitre',
    personalized_lesson: 'Mini-cours',
    knowledge_check: 'Knowledge check',
    exercise: 'Exercice',
    ask_chatbot: 'Chatbot',
    personalized_assessment: 'Test personnalise',
    view_comparison: 'Comparaison',
    continue_course: 'Cours suivant',
    start_recommended_course: 'Cours recommande',
  }
  return labels[type] || type
}

export default StudyPathPage
