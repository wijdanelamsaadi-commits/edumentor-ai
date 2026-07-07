import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, BarChart3, CheckCircle2, ClipboardList, Home, Trophy, XCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8001'
const API_URL = `${API_BASE_URL}/api`

function DiagnosticPage() {
  const navigate = useNavigate()
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [currentIndex, setCurrentIndex] = useState(0)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(`${API_URL}/diagnostic/questions`)
      .then((res) => res.json())
      .then((data) => {
        setQuestions(data.questions || [])
        setLoading(false)
      })
      .catch(() => {
        setError("Impossible de charger le test diagnostique.")
        setLoading(false)
      })
  }, [])

  const currentQuestion = questions[currentIndex]
  const progress = questions.length ? Math.round(((currentIndex + 1) / questions.length) * 100) : 0
  const isAnswered = answers[currentQuestion?.id] !== undefined

  const selectAnswer = (optionIndex) => {
    setAnswers((current) => ({
      ...current,
      [currentQuestion.id]: optionIndex,
    }))
  }

  const goNext = () => {
    if (!isAnswered) return

    if (currentIndex < questions.length - 1) {
      setCurrentIndex((current) => current + 1)
    } else {
      submitTest()
    }
  }

  const goPrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex((current) => current - 1)
    }
  }

  const submitTest = async () => {
    try {
      const response = await fetch(`${API_URL}/diagnostic/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
      })

      const data = await response.json()
      setResult(data)

      localStorage.setItem(
        'diagnosticResult',
        JSON.stringify({
          score: data.score,
          level: data.level,
          date: new Date().toISOString(),
          corrections: data.corrections,
        }),
      )
    } catch {
      setError("Impossible d'envoyer vos réponses.")
    }
  }

  if (loading) {
    return (
      <section className="page-section diagnostic-page">
        <div className="page-heading">
          <h1>Test diagnostique</h1>
        </div>
        <article className="question-card diagnostic-card">
          <h3>Chargement du test...</h3>
        </article>
      </section>
    )
  }

  if (error) {
    return (
      <section className="page-section diagnostic-page">
        <div className="page-heading">
          <h1>Test diagnostique</h1>
        </div>
        <article className="question-card diagnostic-card">
          <h3>{error}</h3>
        </article>
      </section>
    )
  }

  return (
    <section className="page-section diagnostic-page">
      <div className="page-heading">
        <h1>Test diagnostique</h1>
      </div>

      {result ? (
        <DiagnosticResult result={result} onDashboard={() => navigate('/dashboard')} />
      ) : (
        <>
          <div className="test-progress">
            <span>
              Question <strong>{currentIndex + 1}</strong> sur {questions.length}
            </span>
            <div className="progress-track">
              <span style={{ width: `${progress}%` }} />
            </div>
            <strong>{progress}%</strong>
          </div>

          <article className="question-card diagnostic-card">
            <h2>Q{currentIndex + 1}.</h2>
            <h3>{currentQuestion.question}</h3>

            <div className="answer-list">
              {currentQuestion.options.map((option, index) => (
                <button
                  className={answers[currentQuestion.id] === index ? 'answer-option selected' : 'answer-option'}
                  key={option}
                  onClick={() => selectAnswer(index)}
                  type="button"
                >
                  <span />
                  {option}
                </button>
              ))}
            </div>

            <div className="question-actions">
              <button className="ghost-button" disabled={currentIndex === 0} onClick={goPrevious} type="button">
                <ArrowLeft size={20} />
                Précédent
              </button>

              <button className="primary-button" disabled={!isAnswered} onClick={goNext} type="button">
                {currentIndex === questions.length - 1 ? 'Terminer' : 'Suivant'}
                <ArrowRight size={20} />
              </button>
            </div>
          </article>
        </>
      )}
    </section>
  )
}

function DiagnosticResult({ result, onDashboard }) {
  return (
    <article className="panel-card diagnostic-result">
      <div className="result-heading">
        <span><Trophy size={46} /></span>
        <div><h2>Test terminé !</h2><p>Voici votre résultat</p></div>
      </div>

      <div className="result-content">
        <div className="score-ring"><strong>{result.score}%</strong><span>Score global</span></div>
        <div className="result-stats">
          <p><ClipboardList size={20} />Questions <strong>{result.total}</strong></p>
          <p><CheckCircle2 size={20} />Bonnes réponses <strong>{result.correct_count}</strong></p>
          <p><XCircle size={20} />Mauvaises réponses <strong>{result.total - result.correct_count}</strong></p>
        </div>
      </div>

      <div className="level-result">
        <span><BarChart3 size={42} /></span>
        <div>
          <h2>{result.level}</h2>
          <p>Votre parcours sera adapté automatiquement selon ce niveau.</p>
        </div>
        <button className="outline-button" onClick={() => window.location.href = '/courses'} type="button">
          Voir mes recommandations →
        </button>
      </div>

      <div className="level-scale">
        <span className={result.level === 'Débutant' ? 'active' : ''}>Débutant<br /><small>0 - 40%</small></span>
        <span className={result.level === 'Intermédiaire' ? 'active' : ''}>Intermédiaire<br /><small>41 - 75%</small></span>
        <span className={result.level === 'Avancé' ? 'active' : ''}>Avancé<br /><small>76 - 100%</small></span>
      </div>

      <div className="result-actions">
        <button className="ghost-button" type="button">Revoir mes réponses</button>
        <button className="primary-button" onClick={onDashboard} type="button">
          Retour au tableau de bord <Home size={20} />
        </button>
      </div>
    </article>
  )
}

export default DiagnosticPage
