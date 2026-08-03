import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Award,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  MessageCircle,
  Star,
  Target,
} from 'lucide-react'
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
  const [supportExpanded, setSupportExpanded] = useState(false)

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
  const unansweredCount = Math.max(0, questions.length - answeredCount)
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
    const warning = unansweredCount
      ? `\n\nAttention : ${unansweredCount} question(s) ne sont pas encore répondues.`
      : ''
    if (!window.confirm(`Soumettre votre examen ? Les réponses seront verrouillées après la soumission.${warning}`)) {
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
    <section className="regional-taking-page">
      <RegionalTakingHeader exam={exam} onBack={() => navigate('/regional-exam-preparation')} />

      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="regional-taking-info-grid">
        <ExamInfoCard
          icon={BookOpen}
          label="Œuvre"
          value={exam.work_title || '--'}
          details={[
            exam.author && exam.genre ? `${exam.author} - ${exam.genre}` : exam.author || exam.genre || exam.description,
            [exam.region, exam.year].filter(Boolean).join(' - '),
          ]}
        />
        <ExamInfoCard
          icon={CalendarDays}
          label="Session"
          value={exam.session || 'Normale'}
          details={[exam.duration_minutes ? `${exam.duration_minutes} min` : 'Durée non précisée']}
        />
        <ExamInfoCard
          icon={Star}
          label="Barème"
          value={`${exam.total_points || 0} pts`}
          details={[`${exam.question_count || questions.length} question(s)`]}
        />
        <ExamInfoCard
          icon={Target}
          label="Score actuel"
          value={latestCompleted?.score_on_20 ? `${formatNumber(latestCompleted.score_on_20)} / 20` : '0 / 20'}
          details={[latestCompleted?.percentage ? `${Math.round(Number(latestCompleted.percentage))}% dernière tentative` : 'Aucun score']}
        />
      </div>

      {!attempt ? (
        <article className="regional-start-card">
          <div>
            <h2>Commencer l'examen</h2>
            <p>Les corrections resteront cachées jusqu'à la soumission. Vos réponses restent visibles pendant toute la navigation entre les questions.</p>
            {latestCompleted && <p>Dernier score : {Math.round(Number(latestCompleted.percentage || 0))}%</p>}
          </div>
          <button className="primary-button" onClick={start} type="button">Commencer</button>
        </article>
      ) : (
        <div className="regional-taking-layout">
          <main className="regional-taking-main">
            <SupportTextCard
              currentIndex={currentIndex}
              expanded={supportExpanded}
              onToggle={() => setSupportExpanded((value) => !value)}
              progress={progress}
              questionCount={questions.length}
              supportText={exam.support_text}
            />
            <QuestionCard
              answer={answers[currentQuestion.id] || ''}
              currentIndex={currentIndex}
              onAnswer={updateAnswer}
              onNext={() => setCurrentIndex(Math.min(questions.length - 1, currentIndex + 1))}
              onPrevious={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
              onSubmit={submit}
              question={currentQuestion}
              questionCount={questions.length}
              submitting={submitting}
            />
          </main>
          <aside className="regional-taking-aside" aria-label="Navigation de l'examen">
            <QuestionNavigation
              answers={answers}
              currentIndex={currentIndex}
              onSelect={setCurrentIndex}
              questions={questions}
            />
            <ExamSummaryCard
              answeredCount={answeredCount}
              onSubmit={submit}
              questionCount={questions.length}
              score={latestCompleted?.score_on_20 ? `${formatNumber(latestCompleted.score_on_20)} / 20` : '0 / 20'}
              submitting={submitting}
              unansweredCount={unansweredCount}
            />
          </aside>
        </div>
      )}
    </section>
  )
}

function RegionalTakingHeader({ exam, onBack }) {
  return (
    <header className="regional-taking-header">
      <button className="regional-taking-back" onClick={onBack} type="button">
        <ArrowLeft size={18} /> Retour aux examens
      </button>
      <h1>{exam.title}</h1>
      <span className="regional-verified-badge"><CheckCircle2 size={16} /> Officiel vérifié</span>
    </header>
  )
}

function ExamInfoCard({ details = [], icon: Icon, label, value }) {
  return (
    <article className="regional-exam-info-card">
      <span><Icon size={28} /></span>
      <div>
        <p>{label}</p>
        <h2>{value}</h2>
        {details.filter(Boolean).map((item, index) => (
          <strong key={`${label}-${index}`}>{item}</strong>
        ))}
      </div>
    </article>
  )
}

function SupportTextCard({ currentIndex, expanded, onToggle, progress, questionCount, supportText }) {
  return (
    <article className="regional-support-card">
      <header>
        <div><BookOpen size={22} /><h2>Texte support</h2></div>
        {supportText && (
          <button aria-expanded={expanded} onClick={onToggle} type="button">
            {expanded ? 'Réduire' : 'Lire plus'} <ChevronDown size={16} />
          </button>
        )}
      </header>
      <div className={expanded ? 'regional-support-text expanded' : 'regional-support-text'}>
        {supportText ? splitParagraphs(supportText).map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>) : <p>Aucun texte support fourni pour cet examen.</p>}
      </div>
      <footer>
        <span>Question {currentIndex + 1} sur {questionCount}</span>
        <div className="regional-taking-progress"><i style={{ width: `${progress}%` }} /></div>
        <strong>{progress}% complété</strong>
      </footer>
    </article>
  )
}

function QuestionCard({ answer, currentIndex, onAnswer, onNext, onPrevious, onSubmit, question, questionCount, submitting }) {
  if (!question) return null
  const isLast = currentIndex >= questionCount - 1
  return (
    <article className="regional-question-card">
      <p>{question.section || question.competence || 'Étude de texte'}</p>
      <h2>Question {currentIndex + 1}</h2>
      <h3>{question.question}</h3>
      <QuestionRenderer answer={answer} onChange={(value) => onAnswer(question.id, value)} question={question} />
      <ExamNavigationButtons
        currentIndex={currentIndex}
        isLast={isLast}
        onNext={onNext}
        onPrevious={onPrevious}
        onSubmit={onSubmit}
        submitting={submitting}
      />
    </article>
  )
}

function QuestionRenderer({ answer, onChange, question }) {
  if (Array.isArray(question.choices) && question.choices.length) {
    return (
      <div className="regional-choice-list" role="radiogroup" aria-label={question.question}>
        {question.choices.map((choice, index) => (
          <button
            aria-checked={answer === choice}
            className={answer === choice ? 'regional-choice-option selected' : 'regional-choice-option'}
            key={`${question.id}-${choice}`}
            onClick={() => onChange(choice)}
            role="radio"
            type="button"
          >
            <span>{String.fromCharCode(65 + index)}</span>{choice}
          </button>
        ))}
      </div>
    )
  }
  const rows = question.question_type === 'response_long' || question.question_type === 'production_ecrite' ? 8 : 5
  return (
    <label className="regional-answer-field">
      <span>Votre réponse</span>
      <textarea value={answer} onChange={(event) => onChange(event.target.value)} placeholder="Écrivez votre réponse ici..." rows={rows} />
    </label>
  )
}

function ExamNavigationButtons({ currentIndex, isLast, onNext, onPrevious, onSubmit, submitting }) {
  return (
    <div className="regional-question-actions">
      <button disabled={currentIndex === 0} onClick={onPrevious} type="button">
        <ArrowLeft size={18} /> Précédente
      </button>
      {isLast ? (
        <button className="primary" disabled={submitting} onClick={onSubmit} type="button">
          {submitting ? 'Soumission...' : "Vérifier et terminer"} <ArrowRight size={18} />
        </button>
      ) : (
        <button className="primary" onClick={onNext} type="button">
          Suivante <ArrowRight size={18} />
        </button>
      )}
    </div>
  )
}

function QuestionNavigation({ answers, currentIndex, onSelect, questions }) {
  return (
    <article className="regional-navigation-card">
      <h2>Navigation</h2>
      <div className="regional-question-grid">
        {questions.map((question, index) => {
          const answered = Boolean(String(answers[question.id] || '').trim())
          const current = index === currentIndex
          return (
            <button
              aria-current={current ? 'step' : undefined}
              aria-label={`Aller à la question ${index + 1}${answered ? ', répondue' : ', non répondue'}`}
              className={`${current ? 'current' : ''} ${answered ? 'answered' : ''}`.trim()}
              key={question.id}
              onClick={() => onSelect(index)}
              type="button"
            >
              {index + 1}
            </button>
          )
        })}
      </div>
      <div className="regional-navigation-legend">
        <span><i className="current" />Actuelle</span>
        <span><i />Non répondu</span>
        <span><i className="answered" />Répondu</span>
      </div>
    </article>
  )
}

function ExamSummaryCard({ answeredCount, onSubmit, questionCount, score, submitting, unansweredCount }) {
  return (
    <article className="regional-exam-summary-card">
      <h2>Résumé de l'examen</h2>
      <dl>
        <div><dt>Questions totales</dt><dd>{questionCount}</dd></div>
        <div><dt>Répondues</dt><dd>{answeredCount}</dd></div>
        <div><dt>Non répondues</dt><dd>{unansweredCount}</dd></div>
        <div><dt>Score actuel</dt><dd>{score}</dd></div>
      </dl>
      <button disabled={submitting} onClick={onSubmit} type="button">
        {submitting ? 'Soumission...' : "Terminer l'examen"}
      </button>
    </article>
  )
}

function RegionalExamResult({ exam, onRestart, result }) {
  const questions = result.questions || []
  const competencyRows = result.score_by_competence || []
  const weakPoints = result.weak_points || []
  const percentage = Math.round(Number(result.percentage || 0))
  const scoreOn20 = formatNumber(result.score_on_20)
  const resultSubtitle = [
    exam?.type_label || 'Examen régional de français',
    exam?.region,
    exam?.year,
  ].filter(Boolean).join(' • ')

  return (
    <section className="regional-result-page">
      <div className="regional-result-header">
        <div>
          <h1>Résultat de l'examen régional</h1>
          <p>{resultSubtitle || exam.title}</p>
        </div>
        <Link className="regional-result-back" to="/regional-exam-preparation">
          Retour aux examens <ArrowRight size={18} />
        </Link>
      </div>

      <div className="regional-result-summary-grid">
        <ResultSummaryCard
          icon={ClipboardCheck}
          label="Note"
          value={`${scoreOn20} / 20`}
          hint={`${formatNumber(result.score)}/${formatNumber(result.max_score)} points`}
          progress={Math.min(100, Math.max(0, Number(result.score_on_20 || 0) * 5))}
        />
        <ResultSummaryCard
          icon={Award}
          label="Score"
          value={`${percentage}%`}
          hint={`Tentative ${result.attempt_number || 1}`}
        />
        <ResultSummaryCard
          icon={MessageCircle}
          label="Questions"
          value={questions.length}
          hint="Correction disponible"
        />
      </div>

      <div className="regional-result-insights-grid">
        <CompetencyScoreCard rows={competencyRows} />
        <WeakCompetenciesCard rows={weakPoints} recommendations={result.recommendations || []} />
      </div>

      <article className="regional-correction-card">
        <header>
          <div>
            <ClipboardCheck size={22} />
            <h2>Correction</h2>
          </div>
          <span>{questions.length} question{questions.length > 1 ? 's' : ''}</span>
        </header>
        <div className="regional-correction-list">
          {questions.map((question, index) => (
            <CorrectionAccordionItem index={index} key={question.id || `${index}-${question.question}`} question={question} />
          ))}
        </div>
      </article>

      <article className="continue-card regional-result-next-step">
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

function ResultSummaryCard({ icon: Icon, label, value, hint, progress }) {
  return (
    <article className="regional-summary-card">
      <span className="regional-summary-icon"><Icon size={28} /></span>
      <div>
        <p>{label}</p>
        <h2>{value}</h2>
        <strong>{hint}</strong>
        {typeof progress === 'number' && (
          <div className="regional-summary-progress" aria-label={`Progression ${Math.round(progress)}%`}>
            <span style={{ width: `${progress}%` }} />
          </div>
        )}
      </div>
    </article>
  )
}

function CompetencyScoreCard({ rows = [] }) {
  return (
    <article className="regional-insight-card">
      <header>
        <div><ClipboardList size={22} /><h2>Scores par compétence</h2></div>
        <span>{rows.length}</span>
      </header>
      {rows.length ? (
        <div className="regional-competency-list">
          {rows.map((row) => {
            const percent = Math.min(100, Math.max(0, Number(row.percentage || 0)))
            return (
              <div className="regional-competency-row" key={row.competence}>
                <div className="regional-competency-line">
                  <strong>{row.competence}</strong>
                  <span>{formatNumber(row.score)}/{formatNumber(row.max_score)} points</span>
                  <b>{Math.round(percent)}%</b>
                </div>
                <div className="regional-competency-track">
                  <span style={{ width: `${percent}%` }} />
                </div>
              </div>
            )
          })}
        </div>
      ) : <p className="regional-empty-state">Aucune donnée.</p>}
    </article>
  )
}

function WeakCompetenciesCard({ recommendations = [], rows = [] }) {
  return (
    <article className="regional-insight-card regional-weakness-card">
      <header>
        <div><Target size={22} /><h2>Compétences faibles</h2></div>
        <span>{rows.length}</span>
      </header>
      {rows.length ? (
        <div className="regional-weakness-list">
          {rows.map((row) => (
            <div className="regional-weakness-item" key={row.competence}>
              <strong>{row.competence}</strong>
              <p>{row.recommendation || row.message || 'À renforcer avant la prochaine tentative.'}</p>
              <span>{Math.round(Number(row.percentage || 0))}%</span>
            </div>
          ))}
          {recommendations.length > 0 && (
            <div className="regional-recommendations">
              {recommendations.map((item) => <p key={item}>{item}</p>)}
            </div>
          )}
        </div>
      ) : (
        <div className="regional-success-state">
          <span><CheckCircle2 size={28} /></span>
          <div>
            <p>Aucune difficulté prioritaire détectée.</p>
            <strong>Excellent travail ! Continuez comme ça.</strong>
          </div>
        </div>
      )}
    </article>
  )
}

function CorrectionAccordionItem({ index, question }) {
  const correct = Boolean(question.correct)
  const statusLabel = correct ? 'OK' : 'À revoir'
  const statusClass = correct ? 'correct' : 'review'
  const selectedAnswer = question.selected_answer || 'Aucune réponse'
  const feedback = question.teacher_validation_message || question.explanation || 'Feedback non disponible.'

  return (
    <details className="regional-correction-row">
      <summary>
        <span className={`regional-correction-status ${statusClass}`}>{statusLabel}</span>
        <div className="regional-correction-summary">
          <strong>{question.question || `Question ${index + 1}`}</strong>
          <p>
            <span>Votre réponse : {truncateText(selectedAnswer, 82)}</span>
            <span>Feedback : {truncateText(feedback, 92)}</span>
          </p>
        </div>
        <ChevronDown aria-hidden="true" size={20} />
      </summary>
      <div className="regional-correction-detail">
        <DetailLine label="Votre réponse" value={selectedAnswer} />
        {question.correct_answer && <DetailLine label="Correction attendue" value={question.correct_answer} />}
        {question.teacher_validation_message && <DetailLine label="Feedback du correcteur" value={question.teacher_validation_message} />}
        {question.explanation && <DetailLine label="Explication" value={question.explanation} />}
        <div className="regional-correction-meta">
          <DetailLine label="Points obtenus" value={formatNumber(question.points_awarded ?? question.score ?? 0)} />
          <DetailLine label="Points maximums" value={formatNumber(question.max_points ?? question.points ?? 0)} />
          <DetailLine label="Compétence" value={question.competence || question.section || 'Non précisée'} />
        </div>
      </div>
    </details>
  )
}

function DetailLine({ label, value }) {
  return (
    <div className="regional-detail-line">
      <span>{label}</span>
      <p>{value}</p>
    </div>
  )
}

function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value ?? 0
  return Number.isInteger(number) ? number : number.toFixed(2).replace(/\.?0+$/, '')
}

function truncateText(value, maxLength) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`
}

function splitParagraphs(text) {
  return String(text || '')
    .split(/\n{2,}|\r\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export default RegionalExamDetailPage
