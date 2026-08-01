import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getDetailedAssessmentResult } from '../services/api.js'

function AssessmentResultPage() {
  const { attemptId } = useParams()
  const [report, setReport] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    getDetailedAssessmentResult(attemptId)
      .then(setReport)
      .catch((err) => setMessage(err.message || 'Resultat indisponible.'))
  }, [attemptId])

  if (!report) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  const metrics = report.global_metrics || {}

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Rapport pedagogique detaille</h1>
          <p>{report.assessment?.title}</p>
        </div>
        {report.remediation_plan && <Link className="primary-button" to={`/remediation/${report.remediation_plan.id}`}>Ouvrir le parcours personnalise</Link>}
      </div>

      <div className="dashboard-stats">
        <Metric label="Score" value={`${Math.round(metrics.percentage || 0)}%`} hint={`${metrics.score}/${metrics.max_score} points`} />
        <Metric label="Accuracy" value={`${Math.round(metrics.accuracy || 0)}%`} hint={metrics.accuracy_note || `${metrics.correct_answers}/${metrics.answered_questions} reponses donnees`} />
        <Metric label="Completion rate" value={`${Math.round(metrics.completion_rate || 0)}%`} hint={`${metrics.answered_questions}/${metrics.total_questions} questions`} />
        <Metric label="Duree" value={formatDuration(metrics.duration_seconds)} hint={`Temps moyen : ${metrics.average_time_per_question_label || 'Non disponible'}`} />
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Resume</h2><p>{metrics.mastery_status}</p></div>
        <ProgressBar value={metrics.percentage || 0} label="Score global" />
        <p>Questions correctes : {metrics.correct_answers}. Incorrectes : {metrics.incorrect_answers}. Non repondues : {metrics.unanswered_questions}.</p>
      </article>

      <div className="dashboard-grid">
        <ResultGroup title="Resultats par chapitre" rows={report.chapter_results} />
        <ResultGroup title="Resultats par competence" rows={report.skill_results} />
      </div>

      <div className="dashboard-grid">
        <SummarySection title="Forces" rows={report.strengths} emptyText="Aucune force nette detectee pour cette tentative." />
        <SummarySection title="Notions a renforcer" rows={report.weaknesses} emptyText="Aucune difficulte prioritaire detectee." />
      </div>

      <QuestionList title="Questions incorrectes" rows={report.incorrect_answers} emptyText="Aucune question incorrecte." />
      <QuestionList title="Questions non repondues" rows={report.unanswered_questions} emptyText="Aucune question non repondue." />
      <SlowQuestionList rows={report.slow_questions} />

      <article className="continue-card">
        <div>
          <h2>Prochaine etape</h2>
          <p>{report.next_action?.reason || 'Continuer votre parcours.'}</p>
        </div>
        {report.next_action?.route ? (
          <Link className="primary-button" to={report.next_action.route}>{report.next_action.label}</Link>
        ) : (
          <Link className="outline-button" to="/assessments">Voir les evaluations</Link>
        )}
      </article>
    </section>
  )
}

function Metric({ label, value, hint }) {
  return <article className="metric-card"><p>{label}</p><h2>{value}</h2><strong>{hint}</strong></article>
}

function ProgressBar({ value, label }) {
  return (
    <div className="inline-progress">
      <span>{label}</span>
      <div className="progress-track"><span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>
      <strong>{Math.round(value)}%</strong>
    </div>
  )
}

function ResultGroup({ title, rows = [] }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.map((row) => (
        <div className="recommended-item" key={`${title}-${row.id}-${row.name}`}>
          <div>
            <strong>{row.name}</strong>
            <p>{row.correct_answers}/{row.total_questions} - {row.mastery_status}</p>
            <ProgressBar value={row.percentage} label="Progression" />
          </div>
          <strong>{Math.round(row.percentage)}%</strong>
        </div>
      ))}
      {!rows.length && <p className="admin-empty">Aucune donnee.</p>}
    </article>
  )
}

function SummarySection({ title, rows = [], emptyText }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((row) => (
        <div className="recommended-item" key={`${title}-${row.id}-${row.name}`}>
          <div>
            <strong>{row.name}</strong>
            <p>{row.reason}</p>
          </div>
          <strong>{Math.round(row.percentage)}%</strong>
        </div>
      )) : <p className="admin-empty">{emptyText}</p>}
    </article>
  )
}

function QuestionList({ title, rows = [], emptyText }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((question) => (
        <div className="history-item" key={question.question_id}>
          <span>!</span>
          <div>
            <strong>{question.question}</strong>
            {'selected_answer' in question && <p>Votre reponse : {question.selected_answer || 'Aucune'} - Bonne reponse : {question.correct_answer}</p>}
            {question.explanation && <p>{question.explanation}</p>}
            <small>{question.chapter || question.chapter_id || 'Chapitre non associe'} - {question.skill || question.skill_id || 'Competence non associee'}</small>
          </div>
        </div>
      )) : <p className="admin-empty">{emptyText}</p>}
    </article>
  )
}

function SlowQuestionList({ rows = [] }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>Questions lentes</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((question) => (
        <div className="history-item" key={question.question_id}>
          <span>{question.correct ? '✓' : '!'}</span>
          <div>
            <strong>{question.question}</strong>
            <p>{question.time_spent_seconds}s utilises - mediane {question.median_time_seconds}s</p>
            <small>{question.chapter || 'Chapitre non associe'} - {question.skill || 'Competence non associee'}</small>
          </div>
        </div>
      )) : <p className="admin-empty">Non disponible ou moins de trois temps fiables.</p>}
    </article>
  )
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return 'Non disponible'
  const value = Number(seconds || 0)
  return `${Math.floor(value / 60)} min ${value % 60}s`
}

export default AssessmentResultPage
