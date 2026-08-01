import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getProfessorStudyPath, updateProfessorStudyPathItem } from '../services/api.js'

function ProfessorStudyPathPage() {
  const { pathId } = useParams()
  const [path, setPath] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getProfessorStudyPath(pathId)
      .then(setPath)
      .catch((err) => setMessage(err.message || 'Parcours indisponible.'))
  }, [pathId])

  async function toggleRequired(item) {
    try {
      setPath(await updateProfessorStudyPathItem(pathId, item.id, { required: !item.required }))
      setMessage('Etape mise a jour.')
    } catch (err) {
      setMessage(err.message || 'Mise a jour impossible.')
    }
  }

  if (!path) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{path.title}</h1>
          <p>{path.student_name} - {path.course_title}</p>
        </div>
        <Link className="outline-button" to="/professor">Retour</Link>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <article className="metric-card"><p>Progression</p><h2>{Math.round(path.progress_percentage)}%</h2><strong>{path.progress.completed_items}/{path.progress.required_items} obligatoires</strong></article>
        <article className="metric-card"><p>Etape actuelle</p><h2>{path.current_item?.order_index || '--'}</h2><strong>{path.current_item?.title || 'Aucune'}</strong></article>
        <article className="metric-card"><p>Statut</p><h2>{path.status}</h2><strong>{path.comparison_available ? 'Comparaison disponible' : 'En cours'}</strong></article>
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Etapes du parcours</h2><p>{path.items?.length || 0}</p></div>
        {(path.items || []).map((item) => (
          <div className="history-item" key={item.id}>
            <span>{item.order_index}</span>
            <div>
              <strong>{item.title}</strong>
              <p>{item.reason || item.description}</p>
              <small>{item.item_type} - {item.status} - {item.required ? 'obligatoire' : 'facultatif'}</small>
            </div>
            <button type="button" onClick={() => toggleRequired(item)}>
              {item.required ? 'Rendre facultatif' : 'Rendre obligatoire'}
            </button>
          </div>
        ))}
      </article>
    </section>
  )
}

export default ProfessorStudyPathPage
