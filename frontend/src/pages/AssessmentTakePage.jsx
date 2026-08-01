import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, ClipboardList } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { getStudentAssessment, submitStudentAssessment } from '../services/api.js'

function AssessmentTakePage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [assessment, setAssessment] = useState(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answers, setAnswers] = useState({})
  const [timeSpent, setTimeSpent] = useState({})
  const [questionStartedAt, setQuestionStartedAt] = useState(() => Date.now())
  const [startedAt] = useState(() => new Date().toISOString())
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    getStudentAssessment(id)
      .then(setAssessment)
      .catch((err) => setMessage(err.message || 'Evaluation indisponible.'))
  }, [id])

  const questions = assessment?.questions || []
  const currentQuestion = questions[currentIndex]
  const progress = questions.length ? Math.round(((currentIndex + 1) / questions.length) * 100) : 0
  const answeredCount = Object.keys(answers).filter((key) => answers[key]).length
  const remainingText = useMemo(() => assessment?.time_limit_minutes ? `${assessment.time_limit_minutes} min maximum` : 'Sans limite stricte', [assessment])

  function recordCurrentQuestionTime() {
    if (!currentQuestion) return
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - questionStartedAt) / 1000))
    setTimeSpent((prev) => ({
      ...prev,
      [currentQuestion.id]: Math.min(24 * 60 * 60, Number(prev[currentQuestion.id] || 0) + elapsedSeconds),
    }))
    setQuestionStartedAt(Date.now())
  }

  function goToQuestion(nextIndex) {
    recordCurrentQuestionTime()
    setCurrentIndex(nextIndex)
  }

  function selectAnswer(choice) {
    setAnswers((prev) => ({ ...prev, [currentQuestion.id]: choice }))
  }

  async function finishAssessment() {
    if (submitting) return
    const elapsedSeconds = currentQuestion ? Math.max(0, Math.round((Date.now() - questionStartedAt) / 1000)) : 0
    const finalTimes = currentQuestion
      ? { ...timeSpent, [currentQuestion.id]: Math.min(24 * 60 * 60, Number(timeSpent[currentQuestion.id] || 0) + elapsedSeconds) }
      : timeSpent
    setTimeSpent(finalTimes)
    setSubmitting(true)
    try {
      const result = await submitStudentAssessment(id, { started_at: startedAt, answers, time_spent_seconds: finalTimes })
      navigate(`/assessment-results/${result.attempt_id}`)
    } catch (err) {
      setMessage(err.message || 'Soumission impossible.')
      setSubmitting(false)
    }
  }

  if (message && !assessment) {
    return <section className="page-section quiz-page"><article className="panel-card"><p>{message}</p></article></section>
  }

  if (!assessment) {
    return <section className="page-section quiz-page"><article className="panel-card"><p>Chargement...</p></article></section>
  }

  return (
    <section className="page-section quiz-page">
      <button className="back-link" onClick={() => navigate('/assessments')} type="button"><ArrowLeft size={20} /> Retour aux evaluations</button>
      <div className="quiz-header">
        <span className="soft-icon"><ClipboardList size={44} /></span>
        <div>
          <h1>{assessment.title}</h1>
          <p>{assessment.instructions || 'Repondez aux questions puis soumettez votre evaluation.'}</p>
        </div>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      <div className="test-progress">
        <span>Question <strong>{currentIndex + 1}</strong> sur {questions.length}</span>
        <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
        <strong>{remainingText}</strong>
      </div>
      <div className="quiz-layout">
        <article className="question-card quiz-card">
          <h2>Question {currentIndex + 1}</h2>
          <h3>{currentQuestion.question}</h3>
          <div className="answer-list">
            {(currentQuestion.choices || []).map((choice, index) => (
              <button
                className={answers[currentQuestion.id] === choice ? 'answer-option selected' : 'answer-option'}
                key={choice}
                onClick={() => selectAnswer(choice)}
                type="button"
              >
                <span />{String.fromCharCode(65 + index)}. {choice}
              </button>
            ))}
          </div>
          <div className="question-actions">
            <button className="ghost-button" disabled={currentIndex === 0} onClick={() => goToQuestion(Math.max(0, currentIndex - 1))} type="button"><ArrowLeft size={20} />Precedent</button>
            {currentIndex < questions.length - 1 ? (
              <button className="primary-button" onClick={() => goToQuestion(currentIndex + 1)} type="button">Suivant <ArrowRight size={20} /></button>
            ) : (
              <button className="primary-button" disabled={submitting} onClick={finishAssessment} type="button">Soumettre</button>
            )}
          </div>
          <p className="admin-empty">{answeredCount}/{questions.length} reponse(s) selectionnee(s). Les questions sans reponse seront signalees dans le rapport.</p>
        </article>
      </div>
    </section>
  )
}

export default AssessmentTakePage
