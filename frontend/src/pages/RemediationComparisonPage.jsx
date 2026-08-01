import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { compareRemediationPlanDetailed } from '../services/api.js'

function RemediationComparisonPage() {
  const { planId } = useParams()
  const [comparison, setComparison] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    compareRemediationPlanDetailed(planId)
      .then(setComparison)
      .catch((err) => setMessage(err.message || 'Comparaison indisponible.'))
  }, [planId])

  if (!comparison) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  if (!comparison.available) {
    return (
      <section className="page-section dashboard-page">
        <article className="panel-card">
          <h1>Comparaison avant / apres</h1>
          <p>{comparison.message || 'Non disponible'}</p>
          {comparison.next_action?.route && <Link className="primary-button" to={comparison.next_action.route}>{comparison.next_action.label}</Link>}
        </article>
      </section>
    )
  }

  const initial = comparison.initial.global_metrics
  const final = comparison.after_remediation.global_metrics

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Comparaison avant / apres</h1>
          <p>{comparison.trend} - evolution {Math.round(comparison.score_delta)} points</p>
        </div>
        <Link className="outline-button" to={`/remediation/${planId}`}>Retour au parcours</Link>
      </div>

      <div className="dashboard-stats">
        <Metric label="Score avant" value={`${Math.round(initial.percentage)}%`} />
        <Metric label="Score apres" value={`${Math.round(final.percentage)}%`} />
        <Metric label="Accuracy" value={`${Math.round(initial.accuracy)}% -> ${Math.round(final.accuracy)}%`} />
        <Metric label="Duree" value={`${formatDuration(initial.duration_seconds)} -> ${formatDuration(final.duration_seconds)}`} />
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Evolution globale</h2><p>{comparison.trend}</p></div>
        <ComparisonBar label="Avant" value={initial.percentage} />
        <ComparisonBar label="Apres" value={final.percentage} />
      </article>

      <div className="dashboard-grid">
        <ComparisonGroup title="Progression par competence" rows={comparison.skill_comparison} />
        <ComparisonGroup title="Progression par chapitre" rows={comparison.chapter_comparison} />
      </div>

      <div className="dashboard-grid">
        <Summary title="Competences acquises ou ameliorees" rows={comparison.improved_skills} emptyText="Aucune amelioration mesuree." />
        <Summary title="Competences encore a renforcer" rows={comparison.still_weak_skills} emptyText="Aucune competence faible mesuree dans le test final." />
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Mini-cours termines</h2><p>{comparison.completed_lessons?.length || 0}</p></div>
        {(comparison.completed_lessons || []).length ? comparison.completed_lessons.map((lesson) => (
          <div className="history-item" key={lesson.id}>
            <span>✓</span>
            <div><strong>{lesson.title}</strong><p>{lesson.objective}</p></div>
          </div>
        )) : <p className="admin-empty">Aucun mini-cours termine.</p>}
      </article>

      <article className="continue-card">
        <div>
          <h2>Prochaine etape</h2>
          <p>{comparison.next_action?.reason || 'Continuer votre parcours.'}</p>
        </div>
        {comparison.next_action?.route && <Link className="primary-button" to={comparison.next_action.route}>{comparison.next_action.label}</Link>}
      </article>
    </section>
  )
}

function Metric({ label, value }) {
  return <article className="metric-card"><p>{label}</p><h2>{value}</h2></article>
}

function ComparisonBar({ label, value }) {
  return (
    <div className="inline-progress">
      <span>{label}</span>
      <div className="progress-track"><span style={{ width: `${Math.min(100, Math.max(0, value || 0))}%` }} /></div>
      <strong>{Math.round(value || 0)}%</strong>
    </div>
  )
}

function ComparisonGroup({ title, rows = [] }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.map((row) => (
        <div className="recommended-item" key={`${title}-${row.id}`}>
          <div>
            <strong>{row.name}</strong>
            <p>{row.conclusion}</p>
            <ComparisonBar label="Avant" value={row.initial_percentage} />
            {row.final_percentage === null ? <p>Non evaluee dans le test personnalise</p> : <ComparisonBar label="Apres" value={row.final_percentage} />}
          </div>
          <strong>{row.delta === null ? '--' : `${Math.round(row.delta)} pts`}</strong>
        </div>
      ))}
      {!rows.length && <p className="admin-empty">Non disponible.</p>}
    </article>
  )
}

function Summary({ title, rows = [], emptyText }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((row) => (
        <div className="recommended-item" key={`${title}-${row.id}`}>
          <div><strong>{row.name}</strong><p>{row.initial_status} {'->'} {row.final_status}</p></div>
          <strong>{row.delta === null ? '--' : `${Math.round(row.delta)} pts`}</strong>
        </div>
      )) : <p className="admin-empty">{emptyText}</p>}
    </article>
  )
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return 'Non disponible'
  const value = Number(seconds || 0)
  return `${Math.floor(value / 60)} min ${value % 60}s`
}

export default RemediationComparisonPage
