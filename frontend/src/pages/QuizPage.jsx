import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, CheckCircle2, ClipboardList, XCircle } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { fetchCourseById, fetchQuiz, submitQuiz } from '../services/api.js'
import { useLearning } from '../hooks/useLearning.js'

function QuizPage() {
  const navigate = useNavigate()
  const { id } = useParams()
  const { quizResults, saveQuizResult } = useLearning()
  const [course, setCourse] = useState(null)
  const [questions, setQuestions] = useState([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answers, setAnswers] = useState({})
  const [result, setResult] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const currentQuestion = questions[currentIndex]
  const progress = questions.length ? Math.round(((currentIndex + 1) / questions.length) * 100) : 0
  const answeredCount = Object.keys(answers).length
  const savedResult = quizResults[Number(id)]
  const visibleScore = result?.score ?? savedResult?.score
  const currentCorrection = result?.corrections?.[currentIndex]

  useEffect(() => {
    let isMounted = true

    Promise.all([fetchCourseById(id), fetchQuiz(id)])
      .then(([courseData, quizData]) => {
        if (isMounted) {
          setCourse(courseData)
          setQuestions(quizData.questions || [])
          setError('')
        }
      })
      .catch(() => {
        if (isMounted) {
          setError('Impossible de charger le quiz depuis le backend.')
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [id])

  const submittedAnswers = useMemo(
    () => questions.map((_, index) => answers[index] || ''),
    [answers, questions],
  )

  if (isLoading) {
    return (
      <section className="page-section quiz-page">
        <article className="panel-card"><h2>Chargement du quiz...</h2></article>
      </section>
    )
  }

  if (error || !course || questions.length === 0) {
    return (
      <section className="page-section quiz-page">
        <button className="back-link" onClick={() => navigate('/courses')} type="button"><ArrowLeft size={20} /> Retour aux cours</button>
        <article className="panel-card"><h2>Quiz indisponible</h2><p>{error || 'Aucune question disponible pour ce cours.'}</p></article>
      </section>
    )
  }

  function selectAnswer(choice) {
    if (result) return
    setAnswers((current) => ({ ...current, [currentIndex]: choice }))
  }

  function goToPrevious() {
    setCurrentIndex((index) => Math.max(index - 1, 0))
  }

  function goToNext() {
    if (result) {
      setCurrentIndex((index) => Math.min(index + 1, questions.length - 1))
      return
    }

    if (currentIndex < questions.length - 1) {
      setCurrentIndex((index) => index + 1)
      return
    }

    finishQuiz()
  }

  async function finishQuiz() {
    try {
      const finalResult = await submitQuiz(course.id, submittedAnswers)
      setResult(finalResult)
      saveQuizResult(course.id, {
        score: finalResult.score,
        correct: finalResult.correct_answers,
        total: finalResult.total_questions,
        answers,
        corrections: finalResult.corrections,
        recommendation: finalResult.recommendation,
      })
    } catch {
      setError("Impossible d'envoyer le quiz au backend.")
    }
  }

  return (
    <section className="page-section quiz-page">
      <button className="back-link" onClick={() => navigate(`/courses/${course.id}`)} type="button"><ArrowLeft size={20} /> Retour au cours</button>
      <div className="quiz-header">
        <span className="soft-icon"><ClipboardList size={44} /></span>
        <div>
          <h1>Quiz - {course.title}</h1>
          <p>Testez vos connaissances sur ce chapitre.</p>
        </div>
      </div>
      <div className="test-progress">
        <span>Question <strong>{currentIndex + 1}</strong> sur {questions.length}</span>
        <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
        <strong>{progress}%</strong>
      </div>

      <div className="quiz-layout">
        <div>
          <article className="question-card quiz-card">
            <h2>Question {currentIndex + 1}</h2>
            <h3>{currentQuestion.question}</h3>
            <div className="answer-list">
              {currentQuestion.choices.map((choice, index) => {
                const isSelected = answers[currentIndex] === choice
                const isCorrect = result && choice === currentCorrection?.correct_answer
                const isWrong = result && isSelected && choice !== currentCorrection?.correct_answer

                return (
                  <button
                    className={getAnswerClassName(isSelected, isCorrect, isWrong)}
                    key={choice}
                    onClick={() => selectAnswer(choice)}
                    type="button"
                  >
                    <span />{String.fromCharCode(65 + index)}. {choice}
                    {(isSelected || isCorrect) && <CheckCircle2 size={20} />}
                  </button>
                )
              })}
            </div>
            <div className="question-actions">
              <button className="ghost-button" disabled={currentIndex === 0} onClick={goToPrevious} type="button"><ArrowLeft size={20} />Précédent</button>
              <button className="primary-button" disabled={!answers[currentIndex]} onClick={goToNext} type="button">
                {!result && currentIndex === questions.length - 1 ? 'Terminer' : 'Suivant'} <ArrowRight size={20} />
              </button>
            </div>
          </article>

          {result && (
            <>
              <article className="panel-card correction-card">
                <h2>Correction</h2>
                <strong><CheckCircle2 size={22} />{currentCorrection?.is_correct ? 'Bonne réponse !' : 'Correction'}</strong>
                <p>Votre réponse : {currentCorrection?.user_answer || 'Aucune réponse'}</p>
                <p>La réponse correcte est : {currentCorrection?.correct_answer}</p>
              </article>
              <article className="panel-card explanation-card">
                <h2>Explication</h2>
                <p>{currentCorrection?.explanation}</p>
                <div className="success-note"><strong>Score final</strong><p>{result.correct_answers} bonnes réponses sur {questions.length}, soit {result.score}%.</p></div>
                <div className="danger-note"><strong>Recommandation :</strong><p>{result.recommendation}</p></div>
              </article>
            </>
          )}
        </div>
        <aside className="quiz-side">
          <article className="panel-card score-card">
            <h2>Votre score</h2>
            <div className="score-ring"><strong>{visibleScore ?? 0}%</strong><span>{result?.correct_answers ?? savedResult?.correct ?? 0} / {questions.length}</span></div>
            <p><CheckCircle2 size={18} />Bonnes r?ponses <strong>{result?.correct_answers ?? savedResult?.correct ?? 0}</strong></p>
            <p><XCircle size={18} />Mauvaises réponses <strong>{result ? questions.length - result.correct_answers : savedResult ? questions.length - savedResult.correct : 0}</strong></p>
          </article>
          <article className="panel-card question-index">
            <h2>Questions</h2>
            {questions.map((question, index) => (
              <p key={question.question} className={index === currentIndex ? 'active' : ''}>
                <span>{index + 1}</span>{getQuestionStatus(index, answers, result)}
              </p>
            ))}
            <button className="primary-button" disabled={answeredCount < questions.length || Boolean(result)} onClick={finishQuiz} type="button">Voir le résumé</button>
          </article>
        </aside>
      </div>
    </section>
  )
}

function getAnswerClassName(isSelected, isCorrect, isWrong) {
  if (isCorrect) return 'answer-option selected correct'
  if (isWrong) return 'answer-option selected'
  if (isSelected) return 'answer-option selected'
  return 'answer-option'
}

function getQuestionStatus(index, answers, result) {
  if (!answers[index]) return 'Non répondu'
  if (!result) return 'Répondu'
  return result.corrections?.[index]?.is_correct ? 'Correct' : 'Incorrect'
}

export default QuizPage
