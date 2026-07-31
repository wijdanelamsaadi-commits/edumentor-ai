import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, ClipboardList } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getRegionalExam, getRegionalExamAttempts, startRegionalExam, submitRegionalExam } from '../services/api.js'

function RegionalExamDetailPage() {
  const { examId } = useParams()
  const navigate = useNavigate()
  const [exam, setExam] = useState(null)
  const [attempts, setAttempts] = useState([])
  const [attempt, setAttempt] = useState(null)
  const [answers, setAnswers] = useState({})
  const [currentIndex, setCurrentIndex] = useState(0)
  const [startedAt, setStartedAt] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([getRegionalExam(examId), getRegionalExamAttempts(examId)])
      .then(([examData, attemptData]) => {
        if (cancelled) return
        setExam(examData)
        setAttempts(Array.isArray(attemptData.attempts) ? attemptData.attempts : [])
        setMessage('')
      })
      .catch((error) => {
        if (!cancelled) setMessage(error?.message || 'Examen régional indisponible.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [examId])

  const questions = exam?.questions || []
  const currentQuestion = questions[currentIndex]
  const answeredCount = Object.values(answers).filter((value) => String(value || '').trim()).length
  const progress = questions.length ? Math.round((answeredCount / questions.length) * 100) : 0
  const latestCompleted = useMemo(() => attempts.find((item) => item.status === 'completed'), [attempts])

  async function start() {
    try {
      const data = await startRegionalExam(examId)
      setAttempt(data)
      setStartedAt(data.started_at || new Date().toISOString())
      setMessage('')
    } catch (error) {
      setMessage(error?.message || 'Impossible de démarrer cet examen.')
    }
  }

  function updateAnswer(questionId, value) {
    setAnswers((current) => ({ ...current, [questionId]: value }))
  }

  async function submit() {
    if (!window.confirm('Soumettre votre examen ? Les réponses seront verrouillées après la soumission.')) {
      return
    }
    setSubmitting(true)
    try {
      const data = await submitRegionalExam(examId, {
        attempt_id: attempt?.attempt_id,
        started_at: startedAt || new Date().toISOString(),
        answers,
      })
      setResult(data)
      setMessage('')
    } catch (error) {
      setMessage(error?.message || 'Soumission impossible.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <section className="page-section quiz-page"><article className="panel-card"><p>Chargement...</p></article></section>
  }

  if (!exam) {
    return (
      <section className="page-section quiz-page">
        <article className="panel-card">
          <p>{message || 'Examen régional introuvable.'}</p>
          <Link className="outline-button" to="/regional-exam-preparation">Retour</Link>
        </article>
      </section>
    )
  }

  if (result) {
    return (
      <RegionalExamResult
        exam={exam}
        onRestart={() => {
          setResult(null)
          setAttempt(null)
          setAnswers({})
          setCurrentIndex(0)
        }}
        result={result}
      />
    )
  }

  return (
    <section className="page-section quiz-page">
      <button className="back-link" onClick={() => navigate('/regional-exam-preparation')} type="button"><ArrowLeft size={20} /> Retour aux examens</button>
      <div className="quiz-header">
        <span className="soft-icon"><ClipboardList size={44} /></span>
        <div>
          <h1>{exam.title}</h1>
          <p>{exam.type_label || 'Entraînement inspiré des examens régionaux'}</p>
        </div>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <Metric label="Œuvre" value={exam.work_title || '--'} hint={`${exam.region || 'Région non précisée'} · ${exam.year || 'Année non précisée'}`} />
        <Metric label="Session" value={exam.session || '--'} hint={exam.duration_minutes ? `${exam.duration_minutes} min` : 'Durée non précisée'} />
        <Metric label="Barème" value={`${exam.total_points || 0} pts`} hint={`${exam.question_count || questions.length} question(s)`} />
        <Metric label="Tentatives" value={exam.attempts_count || 0} hint={exam.best_score === null || exam.best_score === undefined ? 'Aucun score' : `Meilleur score ${Math.round(Number(exam.best_score))}%`} />
      </div>

      {exam.support_text && (
        <article className="panel-card">
          <div className="panel-title"><h2>Texte support</h2><p>Lecture</p></div>
          <p>{exam.support_text}</p>
        </article>
      )}

      {!attempt ? (
        <article className="continue-card">
          <div>
            <h2>Commencer l'examen</h2>
            <p>Les corrections resteront cachées jusqu'à la soumission.</p>
            {latestCompleted && <p>Dernier score : {Math.round(Number(latestCompleted.percentage || 0))}%</p>}
          </div>
          <button className="primary-button" onClick={start} type="button">Commencer</button>
        </article>
      ) : (
        <>
          <div className="test-progress">
            <span>Question <strong>{currentIndex + 1}</strong> sur {questions.length}</span>
            <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
            <strong>{answeredCount}/{questions.length} répondues</strong>
          </div>
          <div className="quiz-layout">
            <article className="question-card quiz-card">
              <p>{currentQuestion.section || currentQuestion.competence || 'Question'}</p>
              <h2>Question {currentIndex + 1}</h2>
              <h3>{currentQuestion.question}</h3>
              <AnswerInput answer={answers[currentQuestion.id] || ''} question={currentQuestion} onChange={(value) => updateAnswer(currentQuestion.id, value)} />
              <div className="question-actions">
                <button className="ghost-button" disabled={currentIndex === 0} onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))} type="button"><ArrowLeft size={20} />Précédent</button>
                {currentIndex < questions.length - 1 ? (
                  <button className="primary-button" onClick={() => setCurrentIndex(currentIndex + 1)} type="button">Suivant <ArrowRight size={20} /></button>
                ) : (
                  <button className="primary-button" disabled={submitting} onClick={submit} type="button">{submitting ? 'Soumission...' : 'Soumettre mon examen'}</button>
                )}
              </div>
            </article>
          </div>
        </>
      )}
    </section>
  )
}

function AnswerInput({ answer, onChange, question }) {
  if (Array.isArray(question.choices) && question.choices.length) {
    return (
      <div className="answer-list">
        {question.choices.map((choice, index) => (
          <button className={answer === choice ? 'answer-option selected' : 'answer-option'} key={`${question.id}-${choice}`} onClick={() => onChange(choice)} type="button">
            <span />{String.fromCharCode(65 + index)}. {choice}
          </button>
        ))}
      </div>
    )
  }
  const rows = question.question_type === 'response_long' || question.question_type === 'production_ecrite' ? 7 : 4
  return <textarea value={answer} onChange={(event) => onChange(event.target.value)} placeholder="Rédigez votre réponse ici." rows={rows} />
}

function RegionalExamResult({ exam, onRestart, result }) {
  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Résultat de l'examen régional</h1>
          <p>{exam.title}</p>
        </div>
        <Link className="outline-button" to="/regional-exam-preparation">Retour aux examens</Link>
      </div>

      <div className="dashboard-stats">
        <Metric label="Note" value={`${result.score_on_20}/20`} hint={`${result.score}/${result.max_score} points`} />
        <Metric label="Score" value={`${Math.round(Number(result.percentage || 0))}%`} hint={`Tentative ${result.attempt_number}`} />
        <Metric label="Questions" value={result.questions?.length || 0} hint="Correction disponible" />
      </div>

      <div className="dashboard-grid">
        <ResultList title="Scores par compétence" rows={result.score_by_competence || []} />
        <WeaknessList rows={result.weak_points || []} />
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Correction</h2><p>{result.questions?.length || 0}</p></div>
        {(result.questions || []).map((question) => (
          <div className="history-item" key={question.id}>
            <span>{question.correct ? 'OK' : '!'}</span>
            <div>
              <strong>{question.question}</strong>
              <p>Votre réponse : {question.selected_answer || 'Aucune réponse'}</p>
              {question.correct_answer && <p>Correction attendue : {question.correct_answer}</p>}
              {question.explanation && <p>{question.explanation}</p>}
              {question.teacher_validation_message && <p>{question.teacher_validation_message}</p>}
            </div>
          </div>
        ))}
      </article>

      <article className="continue-card">
        <div>
          <h2>Prochaine étape</h2>
          <p>{(result.recommendations || [])[0] || 'Continuez vos révisions.'}</p>
        </div>
        <div className="course-actions">
          <button className="primary-button" onClick={onRestart} type="button">Refaire l'examen</button>
          <Link className="outline-button" to="/courses">Revoir mes cours</Link>
        </div>
      </article>
    </section>
  )
}

function ResultList({ rows = [], title }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>{title}</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((row) => (
        <div className="recommended-item" key={row.competence}>
          <div>
            <strong>{row.competence}</strong>
            <p>{row.score}/{row.max_score} points</p>
            <div className="progress-track"><span style={{ width: `${Math.min(100, Math.max(0, row.percentage))}%` }} /></div>
          </div>
          <strong>{Math.round(Number(row.percentage || 0))}%</strong>
        </div>
      )) : <p className="admin-empty">Aucune donnée.</p>}
    </article>
  )
}

function WeaknessList({ rows = [] }) {
  return (
    <article className="panel-card">
      <div className="panel-title"><h2>Compétences faibles</h2><p>{rows.length}</p></div>
      {rows.length ? rows.map((row) => (
        <div className="recommended-item" key={row.competence}>
          <div>
            <strong>{row.competence}</strong>
            <p>À renforcer avant la prochaine tentative.</p>
          </div>
          <strong>{Math.round(Number(row.percentage || 0))}%</strong>
        </div>
      )) : <p className="admin-empty">Aucune difficulté prioritaire détectée.</p>}
    </article>
  )
}

function Metric({ label, value, hint }) {
  return <article className="metric-card"><p>{label}</p><h2>{value}</h2><strong>{hint}</strong></article>
}

export default RegionalExamDetailPage
