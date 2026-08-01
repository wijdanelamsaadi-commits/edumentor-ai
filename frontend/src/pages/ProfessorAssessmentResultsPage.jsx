import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getProfessorAssessmentResults } from '../services/api.js'

function ProfessorAssessmentResultsPage() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getProfessorAssessmentResults(id)
      .then(setData)
      .catch((err) => setMessage(err.message || 'Resultats indisponibles.'))
  }, [id])

  if (!data) {
    return <section className="page-section admin-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  const analytics = data.analytics || {}

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Resultats d'evaluation</h1>
          <p>{data.assessment.title}</p>
        </div>
        <Link className="outline-button" to="/professor/assessments">Retour</Link>
      </div>

      <div className="dashboard-stats">
        <Metric label="Etudiants assignes" value={analytics.assigned_students ?? 0} />
        <Metric label="Ayant commence" value={analytics.started_students ?? 0} />
        <Metric label="Ayant termine" value={analytics.completed_students ?? 0} />
        <Metric label="Participation" value={`${Math.round(analytics.participation_rate || 0)}%`} />
      </div>
      <div className="dashboard-stats">
        <Metric label="Score moyen" value={formatPercent(analytics.average_score)} />
        <Metric label="Accuracy moyenne" value={formatPercent(analytics.average_accuracy)} />
        <Metric label="Completion moyenne" value={formatPercent(analytics.average_completion)} />
        <Metric label="Duree moyenne" value={formatDuration(analytics.average_duration_seconds)} />
      </div>
      <div className="dashboard-stats">
        <Metric label="Etudiants en difficulte" value={analytics.students_in_difficulty ?? 0} />
        <Metric label="Plans ouverts" value={analytics.open_remediation_plans ?? 0} />
        <Metric label="Mini-cours generes" value={analytics.personalized_lessons_generated ?? 0} />
        <Metric label="Mini-cours termines" value={analytics.personalized_lessons_completed ?? 0} />
      </div>

      <div className="dashboard-grid">
        <Distribution distribution={analytics.score_distribution || {}} />
        <WeaknessList title="Chapitres les plus faibles" rows={analytics.weakest_chapters || []} />
      </div>
      <div className="dashboard-grid">
        <WeaknessList title="Competences les plus faibles" rows={analytics.weakest_skills || []} />
        <article className="panel-card">
          <div className="panel-title"><h2>Amelioration apres remediation</h2><p>{analytics.remediation_improvement === null || analytics.remediation_improvement === undefined ? 'Non disponible' : `${Math.round(analytics.remediation_improvement)} pts`}</p></div>
          <p>La moyenne ignore les etudiants sans test personnalise termine.</p>
        </article>
      </div>

      <article className="panel-card">
        <div className="admin-table">
          <div className="admin-table-row admin-table-head"><span>Etudiant</span><span>Score</span><span>Accuracy</span><span>Completion</span><span>Duree</span><span>Competences faibles</span><span>Parcours</span></div>
          {data.results.map((result) => (
            <div className="admin-table-row" key={result.attempt_id}>
              <span><strong>{result.student_name}</strong><small>{result.student_email}</small></span>
              <span>{Math.round(result.percentage)}%</span>
              <span>{Math.round(result.precision ?? result.accuracy ?? 0)}%</span>
              <span>{Math.round(result.completion_rate || 0)}%</span>
              <span>{formatDuration(result.duration_seconds)}</span>
              <span>{weakSkills(result).join(', ') || 'Aucune'}</span>
              <span>{result.remediation_plan_id ? `#${result.remediation_plan_id}` : 'Non requis'}</span>
            </div>
          ))}
        </div>
        {!data.results.length && <p className="admin-empty">Aucun resultat pour cette evaluation.</p>}
      </article>
    </section>
  )
}

function Metric({ label, value }) {
  return <article className="metric-card"><p>{label}</p><h2>{value}</h2></article>
}

function Distribution({ distribution }) {
  const rows = [
    ['0-39%', distribution['0_39'] || 0],
    ['40-69%', distribution['40_69'] || 0],
    ['70-84%', distribution['70_84'] || 0],
    ['85-100%', distribution['85_100'] || 0],
  ]
  const max = Math.max(1, ...rows.map((row) => row[1]))
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>Repartition des scores</h2><p>{rows.reduce((sum, row) => sum + row[1], 0)}</p></div>
      {rows.map(([label, value]) => (
        <div className="inline-progress" key={label}>
          <span>{label}</span>
          <div className="progress-track"><span style={{ width: `${(value / max) * 100}%` }} /></div>
          <strong>{value}</strong>
        </div>
      ))}
    </article>
  )
}

function WeaknessList({ title, rows }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((row) => (
        <div className="recommended-item" key={`${title}-${row.id}`}>
          <div><strong>{row.name}</strong><p>{row.total_questions} question(s)</p></div>
          <strong>{Math.round(row.average_percentage)}%</strong>
        </div>
      )) : <p className="admin-empty">Non disponible.</p>}
    </article>
  )
}

function formatPercent(value) {
  return value === null || value === undefined ? 'Non disponible' : `${Math.round(value)}%`
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return 'Non disponible'
  const value = Number(seconds || 0)
  return `${Math.floor(value / 60)} min ${Math.round(value % 60)}s`
}

function weakSkills(result) {
  return (result.results_by_skill || [])
    .filter((item) => item.percentage < 70)
    .map((item) => item.name)
}

export default ProfessorAssessmentResultsPage
