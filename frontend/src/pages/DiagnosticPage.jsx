import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, ArrowRight, BarChart3, BookOpen, BrainCircuit, CheckCircle2, ClipboardList, Clock3, GraduationCap, Home, Sparkles, Target, Trophy, XCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import {
  fetchDiagnosticAvailability,
  fetchDiagnosticQuestions,
  fetchEducationLevels,
  fetchSubjects,
  submitDiagnosticAnswers,
} from '../services/api.js'
import { addNotification } from '../services/notifications.js'
import './DiagnosticPage.css'

const RESULTS_BY_SUBJECT_STORAGE_KEY = 'edumentor:diagnosticResultsBySubject'

const DIAGNOSTIC_COMPETENCE_ORDER = [
  'Compréhension',
  'Langue et grammaire',
  'Connaissance des œuvres',
  'Figures de style et procédés',
  'Interprétation et justification',
]

function DiagnosticPage() {
  const navigate = useNavigate()
  const [subjects, setSubjects] = useState([])
  const [educationLevels, setEducationLevels] = useState([])
  const [selectedSubjectId, setSelectedSubjectId] = useState('')
  const [selectedEducationLevelId, setSelectedEducationLevelId] = useState('')
  const [questionSet, setQuestionSet] = useState(null)
  const [availability, setAvailability] = useState(null)
  const [availabilityLoading, setAvailabilityLoading] = useState(false)
  const [questions, setQuestions] = useState([])
  const [answers, setAnswers] = useState({})
  const [currentIndex, setCurrentIndex] = useState(0)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let isMounted = true
    Promise.allSettled([fetchSubjects(), fetchEducationLevels()])
      .then(([subjectsResult, educationResult]) => {
        if (!isMounted) return

        const loadedSubjects =
          subjectsResult.status === 'fulfilled' && Array.isArray(subjectsResult.value)
            ? subjectsResult.value
            : []
        const loadedEducationLevels =
          educationResult.status === 'fulfilled' && Array.isArray(educationResult.value)
            ? educationResult.value
            : []

        const frenchSubject =
          loadedSubjects.find((subject) => String(subject.slug || '').toLowerCase() === 'francais') ||
          loadedSubjects.find((subject) => String(subject.name || '').toLowerCase().includes('fran')) ||
          loadedSubjects[0]

        const firstBacLevel =
          loadedEducationLevels.find((level) => {
            const value = `${level.slug || ''} ${level.name || ''}`.toLowerCase()
            return value.includes('1ere') || value.includes('1ère') || value.includes('premiere') || value.includes('première')
          }) || null

        setSubjects(loadedSubjects)
        setEducationLevels(loadedEducationLevels)
        setSelectedSubjectId(String(frenchSubject?.id || ''))
        setSelectedEducationLevelId(String(firstBacLevel?.id || ''))
      })
      .catch(() => setError('Impossible de charger le test de français.'))
      .finally(() => {
        if (isMounted) setLoading(false)
      })

    return () => {
      isMounted = false
    }
  }, [])

  useEffect(() => {
    if (!selectedSubjectId || questionSet) {
      setAvailability(null)
      return undefined
    }
    let isMounted = true
    setAvailabilityLoading(true)
    setError('')
    fetchDiagnosticAvailability({
      subject_id: selectedSubjectId,
      education_level_id: selectedEducationLevelId,
      limit: 20,
    })
      .then((data) => {
        if (isMounted) setAvailability(data)
      })
      .catch((apiError) => {
        if (isMounted) {
          setAvailability(null)
          setError(apiError.message || 'Impossible de verifier la banque de questions.')
        }
      })
      .finally(() => {
        if (isMounted) setAvailabilityLoading(false)
      })
    return () => {
      isMounted = false
    }
  }, [selectedSubjectId, selectedEducationLevelId, questionSet])

  const selectedSubject = useMemo(
    () => subjects.find((subject) => String(subject.id) === String(selectedSubjectId)) || null,
    [subjects, selectedSubjectId],
  )
  const selectedEducationLevel = useMemo(
    () => educationLevels.find((level) => String(level.id) === String(selectedEducationLevelId)) || null,
    [educationLevels, selectedEducationLevelId],
  )
  const currentQuestion = questions[currentIndex]
  const progress = questions.length ? Math.round(((currentIndex + 1) / questions.length) * 100) : 0
  const isAnswered = currentQuestion ? answers[currentQuestion.id] !== undefined : false

  async function startTest() {
    if (!selectedSubjectId) {
      setError('Choisissez une matiere avant de commencer.')
      return
    }
    if (availability && !availability.can_start) {
      setError(buildAvailabilityMessage(availability))
      return
    }
    setStarting(true)
    setError('')
    try {
      const data = await fetchDiagnosticQuestions({
        subject_id: selectedSubjectId,
        education_level_id: selectedEducationLevelId,
        limit: 20,
      })
      if (!Array.isArray(data.questions) || data.questions.length === 0) {
        setError('Aucune question active disponible pour cette matiere.')
        return
      }
      setQuestionSet(data)
      setQuestions(data.questions)
      setAnswers({})
      setCurrentIndex(0)
      setResult(null)
    } catch (apiError) {
      setError(apiError.message || 'Impossible de charger le test de positionnement.')
    } finally {
      setStarting(false)
    }
  }

  function selectAnswer(optionIndex) {
    setAnswers((current) => ({
      ...current,
      [currentQuestion.id]: optionIndex,
    }))
  }

  function goNext() {
    if (!isAnswered) return
    if (currentIndex < questions.length - 1) {
      setCurrentIndex((current) => current + 1)
    } else {
      submitTest()
    }
  }

  function goPrevious() {
    if (currentIndex > 0) {
      setCurrentIndex((current) => current - 1)
    }
  }

  async function submitTest() {
    if (submitting) return

    setSubmitting(true)
    setError('')

    try {
      const data = await submitDiagnosticAnswers({
        subject_id: Number(selectedSubjectId),
        education_level_id: selectedEducationLevelId ? Number(selectedEducationLevelId) : null,
        session_id: questionSet?.session_id || null,
        answers,
      })
      const diagnosticResult = {
        ...data,
        date: data.created_at || data.date || new Date().toISOString(),
        subject: data.subject || selectedSubject,
        subject_id: data.subject_id || Number(selectedSubjectId),
      }
      setResult(diagnosticResult)
      saveDiagnosticLocally(diagnosticResult)
      addNotification({
        type: 'diagnostic',
        title: 'Test de positionnement termine',
        message: `Votre test ${diagnosticResult.subject?.name || ''} est termine avec un score de ${data.score}%.`,
      })
      addNotification({
        type: 'diagnostic',
        title: 'Nouveau niveau obtenu',
        message: `Votre niveau en ${diagnosticResult.subject?.name || 'matiere'} est ${data.level}.`,
      })
      addNotification({
        type: 'diagnostic',
        title: 'Nouveaux cours recommandes',
        message: 'Votre parcours peut maintenant etre adapte a votre niveau.',
      })
    } catch (apiError) {
      setError(apiError.message || "Impossible d'envoyer vos réponses.")
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <section className="page-section diagnostic-page">
        <div className="page-heading">
          <h1>Test de positionnement</h1>
          <p>Évaluez vos compétences en français et obtenez un parcours adapté à votre niveau.</p>
        </div>
        <article className="question-card diagnostic-card">
          <h3>Chargement du test...</h3>
        </article>
      </section>
    )
  }

  return (
    <section className="page-section diagnostic-page">
      <div className="page-heading">
        <h1>Test de positionnement</h1>
        <p>Évaluez vos compétences en français et obtenez un parcours adapté à votre niveau.</p>
      </div>

      {error && <article className="progress-banner"><span><XCircle size={28} /></span><p>{error}</p></article>}

      {result ? (
        <DiagnosticResult result={result} onDashboard={() => navigate('/dashboard')} />
      ) : !questionSet ? (
        <article className="diagnostic-start-card">
          <div className="diagnostic-start-hero">
            <div className="diagnostic-start-hero__content">
              <span className="diagnostic-start-badge">
                <Sparkles size={17} />
                Évaluation personnalisée
              </span>

              <h2>Découvrez votre niveau en français</h2>
              <p>
                Répondez à 20 questions équilibrées pour identifier vos acquis,
                vos points à renforcer et les cours les plus adaptés.
              </p>

              <div className="diagnostic-start-subject">
                <span className="diagnostic-start-subject__icon">
                  <BookOpen size={26} />
                </span>
                <div>
                  <strong>{selectedSubject?.name || 'Français'}</strong>
                  <span>{selectedEducationLevel?.name || '1ère année Baccalauréat'}</span>
                </div>
              </div>
            </div>

            <div className="diagnostic-start-hero__visual" aria-hidden="true">
              <BrainCircuit size={76} strokeWidth={1.5} />
            </div>
          </div>

          <div className="diagnostic-start-layout">
            <div className="diagnostic-start-main">
              <div className="diagnostic-start-metrics">
                <div className="diagnostic-start-metric">
                  <span><ClipboardList size={22} /></span>
                  <div>
                    <small>Banque disponible</small>
                    <strong>{availabilityLoading ? '...' : availability?.available_count ?? 0} questions</strong>
                  </div>
                </div>

                <div className="diagnostic-start-metric">
                  <span><Target size={22} /></span>
                  <div>
                    <small>Test personnalisé</small>
                    <strong>{availability?.questions_per_test || 20} questions</strong>
                  </div>
                </div>

                <div className="diagnostic-start-metric">
                  <span><Clock3 size={22} /></span>
                  <div>
                    <small>Durée estimée</small>
                    <strong>{availability?.estimated_duration || '10 à 20 min'}</strong>
                  </div>
                </div>

                <div className="diagnostic-start-metric">
                  <span><GraduationCap size={22} /></span>
                  <div>
                    <small>Résultat</small>
                    <strong>Niveau et parcours adaptés</strong>
                  </div>
                </div>
              </div>

              <div className="diagnostic-start-competences">
                <div className="diagnostic-start-section-heading">
                  <span><BarChart3 size={20} /></span>
                  <div>
                    <h3>Compétences évaluées</h3>
                    <p>Chaque test contient 4 questions par compétence.</p>
                  </div>
                </div>

                <div className="diagnostic-start-chips">
                  {DIAGNOSTIC_COMPETENCE_ORDER.map((competence) => (
                    <span key={competence}>
                      <CheckCircle2 size={17} />
                      {competence}
                    </span>
                  ))}
                </div>
              </div>

              {availability?.active_package && (
                <div className="diagnostic-start-program">
                  <BookOpen size={20} />
                  <div>
                    <strong>Programme actif</strong>
                    <span>
                      {availability.active_package.title ||
                        availability.active_package.academic_year ||
                        'Français 1ère Bac'}
                    </span>
                  </div>
                </div>
              )}

              {availability && !availability.can_start && (
                <article className="diagnostic-start-warning">
                  <XCircle size={21} />
                  <p>{buildAvailabilityMessage(availability)}</p>
                </article>
              )}
            </div>

            <aside className="diagnostic-start-aside">
              <span className="diagnostic-start-aside__icon">
                <Trophy size={30} />
              </span>
              <h3>Prête à commencer ?</h3>
              <p>
                Répondez sans aide extérieure afin d’obtenir un niveau réellement
                adapté à vos compétences.
              </p>

              <ul>
                <li><CheckCircle2 size={17} /> Une seule réponse par question</li>
                <li><CheckCircle2 size={17} /> Possibilité de revenir en arrière</li>
                <li><CheckCircle2 size={17} /> Résultat immédiat et recommandations</li>
              </ul>

              <button
                className="diagnostic-start-button"
                disabled={
                  starting ||
                  availabilityLoading ||
                  !selectedSubjectId ||
                  (availability && !availability.can_start)
                }
                onClick={startTest}
                type="button"
              >
                {starting ? 'Préparation du test...' : 'Commencer le test'}
                <ArrowRight size={20} />
              </button>

              <small>
                {availabilityLoading
                  ? 'Vérification de la banque de questions...'
                  : 'Vos réponses seront utilisées uniquement pour adapter votre parcours.'}
              </small>
            </aside>
          </div>
        </article>
      ) : (
        <div className="diagnostic-test-shell">
          <header className="diagnostic-test-header">
            <div className="diagnostic-test-header__top">
              <div className="diagnostic-test-subject">
                <span><BookOpen size={20} /></span>
                <div>
                  <small>Matière</small>
                  <strong>{questionSet.subject?.name || selectedSubject?.name || 'Français'}</strong>
                </div>
              </div>

              <div className="diagnostic-test-counter">
                <small>Progression</small>
                <strong>{currentIndex + 1} / {questions.length}</strong>
              </div>
            </div>

            <div className="diagnostic-test-progress-row">
              <div className="diagnostic-test-progress-track" aria-label={`Progression ${progress}%`}>
                <span style={{ width: `${progress}%` }} />
              </div>
              <strong>{progress}%</strong>
            </div>

            <div className="diagnostic-test-status">
              <span>{Object.keys(answers).length} réponse(s) enregistrée(s)</span>
              <span>{questions.length - Object.keys(answers).length} restante(s)</span>
            </div>
          </header>

          <article className="diagnostic-question-card">
            <div className="diagnostic-question-meta">
              <span className="diagnostic-question-number">
                Question {currentIndex + 1}
              </span>
              <span className="diagnostic-question-competence">
                <Target size={16} />
                {currentQuestion.competence
                  ? formatCompetenceLabel(currentQuestion.competence)
                  : currentQuestion.topic || 'Français'}
              </span>
            </div>

            <h2>{currentQuestion.question}</h2>
            <p className="diagnostic-question-help">
              Sélectionnez une seule réponse, puis passez à la question suivante.
            </p>

            <div className="diagnostic-answer-grid">
              {(currentQuestion.options || currentQuestion.choices || []).map((option, index) => {
                const selected = answers[currentQuestion.id] === index

                return (
                  <button
                    aria-pressed={selected}
                    className={selected ? 'diagnostic-answer selected' : 'diagnostic-answer'}
                    key={`${currentQuestion.id}-${index}`}
                    onClick={() => selectAnswer(index)}
                    type="button"
                  >
                    <span className="diagnostic-answer-letter">
                      {String.fromCharCode(65 + index)}
                    </span>
                    <span className="diagnostic-answer-text">{option}</span>
                    <span className="diagnostic-answer-check">
                      {selected && <CheckCircle2 size={21} />}
                    </span>
                  </button>
                )
              })}
            </div>

            <div className="diagnostic-question-footer">
              <button
                className="diagnostic-nav-button diagnostic-nav-button--secondary"
                disabled={currentIndex === 0 || submitting}
                onClick={goPrevious}
                type="button"
              >
                <ArrowLeft size={19} />
                Précédent
              </button>

              <div className="diagnostic-question-position" aria-hidden="true">
                {questions.map((question, index) => {
                  const answered = answers[question.id] !== undefined
                  const active = index === currentIndex
                  const className = [
                    'diagnostic-question-dot',
                    active ? 'active' : '',
                    answered ? 'answered' : '',
                  ].filter(Boolean).join(' ')

                  return <span className={className} key={question.id} />
                })}
              </div>

              <button
                className="diagnostic-nav-button diagnostic-nav-button--primary"
                disabled={!isAnswered || submitting}
                onClick={goNext}
                type="button"
              >
                {submitting
                  ? 'Analyse en cours...'
                  : currentIndex === questions.length - 1
                    ? 'Terminer le test'
                    : 'Question suivante'}
                {!submitting && <ArrowRight size={19} />}
              </button>
            </div>
          </article>
        </div>
      )}
    </section>
  )
}

function formatCompetenceLabel(value) {
  const labels = {
    comprehension: 'Compréhension',
    langue_grammaire: 'Langue et grammaire',
    connaissance_oeuvres: 'Connaissance des œuvres',
    figures_procedes: 'Figures de style et procédés',
    interpretation_justification: 'Interprétation et justification',
  }

  return labels[String(value || '').trim()] || String(value || 'Français')
}

function buildAvailabilityMessage(availability) {
  if (!availability || availability.available_count === 0) {
    return 'La banque de questions pour cette matiere est en cours de preparation.'
  }
  return `Banque de questions insuffisante : ${availability.missing_count} question(s) manquante(s) pour lancer un test complet.`
}

function DiagnosticResult({ result, onDashboard }) {
  const recommendations = Array.isArray(result.recommendations) ? result.recommendations : []
  const topics = normalizeDiagnosticTopics(result.results_by_topic)
  const studentJustification = buildStudentJustification(result.level)

  return (
    <article className="panel-card diagnostic-result">
      <div className="result-heading">
        <span><Trophy size={46} /></span>
        <div><h2>Test termine !</h2><p>Voici votre resultat en {result.subject?.name || 'matiere'}</p></div>
      </div>

      <div className="result-content">
        <div className="score-ring"><strong>{result.score}%</strong><span>Score global</span></div>
        <div className="result-stats">
          <p><ClipboardList size={20} />Questions <strong>{result.total}</strong></p>
          <p><CheckCircle2 size={20} />Bonnes reponses <strong>{result.correct_count}</strong></p>
          <p><XCircle size={20} />Mauvaises reponses <strong>{result.total - result.correct_count}</strong></p>
        </div>
      </div>

      <div className="level-result">
        <span><BarChart3 size={42} /></span>
        <div>
          <h2>{result.level}</h2>
          <p>{studentJustification}</p>
        </div>
        <button
          className="outline-button"
          disabled={recommendations.length === 0}
          onClick={() => window.location.href = recommendations[0]?.path || '/courses'}
          type="button"
        >
          Voir mes recommandations →
        </button>
      </div>

      {topics.length > 0 && (
        <div className="level-scale">
          {topics.map((topic) => (
            <span key={topic.name}>{topic.name}<br /><small>{topic.percentage}%</small></span>
          ))}
        </div>
      )}

      {recommendations.length > 0 && (
        <div className="answer-list">
          {recommendations.map((course) => (
            <button className="answer-option" key={course.course_id} onClick={() => window.location.href = course.path} type="button">
              <span />
              <strong>{course.title}</strong> - {course.reason}
            </button>
          ))}
        </div>
      )}

      <div className="result-actions">
        <button className="ghost-button" type="button">Revoir mes reponses</button>
        <button className="primary-button" onClick={onDashboard} type="button">
          Retour au tableau de bord <Home size={20} />
        </button>
      </div>
    </article>
  )
}


function normalizeDiagnosticTopics(rawTopics) {
  const topics = Array.isArray(rawTopics) ? rawTopics : []
  const topicsByName = new Map(
    topics.map((topic) => [String(topic?.name || '').trim(), topic]),
  )

  return DIAGNOSTIC_COMPETENCE_ORDER.map((name) => {
    const topic = topicsByName.get(name)
    return {
      name,
      percentage: Number(topic?.percentage || 0),
      correct: Number(topic?.correct || 0),
      total: Number(topic?.total || 0),
    }
  })
}

function buildStudentJustification(level) {
  const normalizedLevel = String(level || '').trim().toLocaleLowerCase('fr-FR')

  if (normalizedLevel.startsWith('début') || normalizedLevel.startsWith('debut')) {
    return 'Niveau débutant détecté : les bases doivent être consolidées avant de passer aux notions plus complexes.'
  }

  if (normalizedLevel.startsWith('interm')) {
    return 'Niveau intermédiaire détecté : vous maîtrisez une partie des bases et pouvez progresser avec des exercices guidés.'
  }

  if (normalizedLevel.startsWith('avanc')) {
    return 'Niveau avancé détecté : vous maîtrisez les notions essentielles et réussissez une partie significative des questions difficiles.'
  }

  return 'Votre parcours sera adapté automatiquement selon votre niveau et vos résultats par compétence.'
}

function saveDiagnosticLocally(result) {
  localStorage.setItem('diagnosticResult', JSON.stringify(result))
  try {
    const stored = JSON.parse(localStorage.getItem(RESULTS_BY_SUBJECT_STORAGE_KEY) || '{}')
    stored[result.subject_id] = result
    localStorage.setItem(RESULTS_BY_SUBJECT_STORAGE_KEY, JSON.stringify(stored))
  } catch {
    localStorage.setItem(RESULTS_BY_SUBJECT_STORAGE_KEY, JSON.stringify({ [result.subject_id]: result }))
  }
}

export default DiagnosticPage
