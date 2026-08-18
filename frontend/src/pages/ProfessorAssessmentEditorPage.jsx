import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  createProfessorAssessment,
  fetchDifficultyLevels,
  getProfessorAssessment,
  getProfessorClassrooms,
  getProfessorCourses,
  proposeProfessorAssessmentQuestions,
  publishProfessorAssessment,
  updateProfessorAssessment,
} from '../services/api.js'

const blankQuestion = {
  question: '',
  choices: ['', '', '', ''],
  correct_answer: '',
  explanation: '',
  chapter_id: '',
  difficulty_level_id: '',
  active: true,
  draft: false,
  manually_edited: true,
}

const STEP_MIN = 1
const STEP_MAX = 4
const ASSESSMENT_STATUSES = new Set(['draft', 'scheduled', 'published', 'closed', 'archived'])

function ProfessorAssessmentEditorPage() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [step, setStep] = useState(parseStep(searchParams.get('step')))
  const [courses, setCourses] = useState([])
  const [classrooms, setClassrooms] = useState([])
  const [difficulties, setDifficulties] = useState([])
  const [message, setMessage] = useState('')
  const [savedAssessmentId, setSavedAssessmentId] = useState(id || '')
  const [isSavingDraft, setIsSavingDraft] = useState(false)
  const [isGeneratingQuestions, setIsGeneratingQuestions] = useState(false)
  const [proposalCount, setProposalCount] = useState(5)
  const [proposalMode, setProposalMode] = useState('append')
  const [draft, setDraft] = useState({
    title: '',
    classroom_id: searchParams.get('classroom_id') || '',
    course_id: '',
    subject_id: '',
    difficulty_level_id: '',
    assessment_type: 'initial',
    status: 'draft',
    description: '',
    instructions: '',
    publication_at: '',
    expires_at: '',
    time_limit_minutes: '',
    max_attempts: 1,
    questions: [],
  })

  useEffect(() => {
    Promise.all([getProfessorCourses(), getProfessorClassrooms(), fetchDifficultyLevels()])
      .then(([courseData, classroomData, difficultyData]) => {
        setCourses(Array.isArray(courseData) ? courseData : [])
        setClassrooms(Array.isArray(classroomData) ? classroomData : [])
        setDifficulties(Array.isArray(difficultyData) ? difficultyData : [])
      })
      .catch((err) => setMessage(err.message || 'Chargement impossible.'))
  }, [])

  useEffect(() => {
    setStep(parseStep(searchParams.get('step')))
  }, [searchParams])

  useEffect(() => {
    setSavedAssessmentId(id || '')
    if (!id) return
    getProfessorAssessment(id)
      .then((data) => setDraft(normalizeDraftFromApi(data)))
      .catch((err) => setMessage(err.message || 'Evaluation introuvable.'))
  }, [id])

  const effectiveAssessmentId = savedAssessmentId || id || ''
  const selectedCourse = useMemo(
    () => courses.find((course) => course.id === Number(draft.course_id)),
    [courses, draft.course_id],
  )

  function updateField(field, value) {
    setDraft((prev) => {
      const next = { ...prev, [field]: value }
      if (field === 'course_id') {
        const course = courses.find((item) => item.id === Number(value))
        next.subject_id = course?.subject_id || ''
        if (!next.title && course?.title) {
          next.title = `Evaluation initiale - ${course.title}`
        }
      }
      return next
    })
  }

  function addQuestion(question = blankQuestion) {
    setDraft((prev) => ({
      ...prev,
      questions: [...prev.questions, { ...question, order_index: prev.questions.length + 1 }],
    }))
  }

  function updateQuestion(index, field, value) {
    setDraft((prev) => ({
      ...prev,
      questions: prev.questions.map((question, currentIndex) =>
        currentIndex === index ? { ...question, [field]: value, draft: false, manually_edited: true } : question,
      ),
    }))
  }

  function updateChoice(questionIndex, choiceIndex, value) {
    setDraft((prev) => ({
      ...prev,
      questions: prev.questions.map((question, currentIndex) => {
        if (currentIndex !== questionIndex) return question
        const nextChoices = normalizeChoices(question.choices)
        nextChoices[choiceIndex] = value
        const previousChoice = question.choices?.[choiceIndex]
        const nextCorrectAnswer = question.correct_answer === previousChoice ? value : question.correct_answer
        return {
          ...question,
          choices: nextChoices,
          correct_answer: nextCorrectAnswer,
          draft: false,
          manually_edited: true,
        }
      }),
    }))
  }

  function removeQuestion(index) {
    setDraft((prev) => ({
      ...prev,
      questions: prev.questions.filter((_, currentIndex) => currentIndex !== index),
    }))
  }

  async function saveAssessment({
    redirect = true,
    redirectStep = null,
    statusOverride = null,
    successMessage = 'Évaluation brouillon sauvegardée.',
    forceActiveQuestions = false,
  } = {}) {
    if (!Number(draft.course_id)) {
      setMessage('Selectionnez un cours avant de creer le brouillon.')
      return null
    }

    try {
      setIsSavingDraft(true)
      const payload = normalizePayload({ ...draft, status: statusOverride || draft.status }, { forceActiveQuestions })
      const currentAssessmentId = effectiveAssessmentId
      logAssessmentDebug('save:start', {
        assessmentId: currentAssessmentId || null,
        courseId: payload.course_id,
      })
      const saved = currentAssessmentId
        ? await updateProfessorAssessment(currentAssessmentId, payload)
        : await createProfessorAssessment(payload)

      setSavedAssessmentId(String(saved.id))
      setDraft(normalizeDraftFromApi(saved))
      if (successMessage) {
        setMessage(successMessage)
      }
      logAssessmentDebug('save:success', {
        assessmentId: saved.id,
        courseId: saved.course_id,
        status: 200,
        response: saved,
      })

      if (redirect) {
        const stepQuery = redirectStep ? `?step=${redirectStep}` : ''
        navigate(`/professor/assessments/${saved.id}/edit${stepQuery}`, { replace: true })
      }
      return saved
    } catch (err) {
      const cleanMessage = err.message || 'Sauvegarde impossible.'
      setMessage(cleanMessage)
      logAssessmentDebug('save:error', {
        assessmentId: effectiveAssessmentId || null,
        courseId: draft.course_id,
        status: err.status,
        error: cleanMessage,
      })
      return null
    } finally {
      setIsSavingDraft(false)
    }
  }

  async function savePublicationWorkflow() {
    const targetStatus = normalizeAssessmentStatus(draft.status)
    const publicationIsFuture = isFutureDateTime(draft.publication_at)

    if (targetStatus === 'published' && publicationIsFuture) {
      await saveAssessment({
        redirect: false,
        statusOverride: 'scheduled',
        successMessage: 'Évaluation programmée.',
      })
      return
    }

    if (targetStatus !== 'published') {
      const messageByStatus = {
        draft: 'Évaluation brouillon sauvegardée.',
        scheduled: 'Évaluation programmée.',
        closed: 'Évaluation sauvegardée.',
        archived: 'Évaluation sauvegardée.',
      }
      await saveAssessment({
        redirect: false,
        statusOverride: targetStatus,
        successMessage: messageByStatus[targetStatus] || 'Évaluation sauvegardée.',
      })
      return
    }

    const saved = await saveAssessment({
      redirect: false,
      statusOverride: 'draft',
      successMessage: '',
      forceActiveQuestions: true,
    })
    if (!saved) return

    try {
      setIsSavingDraft(true)
      const published = await publishProfessorAssessment(saved.id)
      setSavedAssessmentId(String(published.id))
      setDraft(normalizeDraftFromApi(published))
      const assignedCount = Number(published.assigned_student_count || 0)
      setMessage(`Évaluation publiée et assignée à ${assignedCount} étudiant(s).`)
    } catch (err) {
      setMessage(err.message || 'Publication impossible.')
    } finally {
      setIsSavingDraft(false)
    }
  }

  async function goToStep(nextStep) {
    if (nextStep > 1 && !effectiveAssessmentId) {
      const saved = await saveAssessment({ redirect: true, redirectStep: nextStep })
      if (!saved) return
    }
    setStep(nextStep)
  }

  async function proposeQuestions() {
    if (!Number(draft.course_id)) {
      setMessage('Selectionnez un cours avant de proposer des questions.')
      return
    }

    let targetAssessmentId = effectiveAssessmentId
    if (!targetAssessmentId) {
      setMessage('Creation du brouillon avant generation...')
      const saved = await saveAssessment({ redirect: true, redirectStep: 2 })
      if (!saved) return
      targetAssessmentId = String(saved.id)
    }

    try {
      setIsGeneratingQuestions(true)
      setMessage('Generation en cours...')
      logAssessmentDebug('propose:start', {
        assessmentId: targetAssessmentId,
        courseId: draft.course_id,
      })
      const data = await proposeProfessorAssessmentQuestions(targetAssessmentId, { count: proposalCount })
      const proposedQuestions = Array.isArray(data.questions) ? data.questions : []
      logAssessmentDebug('propose:success', {
        assessmentId: targetAssessmentId,
        courseId: draft.course_id,
        status: 200,
        response: data,
      })

      if (!proposedQuestions.length) {
        setMessage(data.message || 'Aucune question de qualite ne peut etre proposee pour ce cours. Ajoutez des questions manuellement ou verifiez le contenu structure du cours.')
        return
      }

      setDraft((prev) => {
        const keptQuestions = proposalMode === 'replace'
          ? prev.questions.filter((question) => !(question.draft === true && question.manually_edited !== true))
          : prev.questions
        return {
          ...prev,
          questions: [
            ...keptQuestions,
            ...proposedQuestions.map((question, index) => ({
              ...question,
              choices: normalizeChoices(question.choices),
              draft: true,
              manually_edited: false,
              order_index: keptQuestions.length + index + 1,
            })),
          ],
        }
      })
      setMessage(`${proposedQuestions.length} questions proposees depuis le cours. Elles restent modifiables avant publication.`)
    } catch (err) {
      const cleanMessage = err.message || 'Generation impossible.'
      setMessage(cleanMessage)
      logAssessmentDebug('propose:error', {
        assessmentId: targetAssessmentId,
        courseId: draft.course_id,
        status: err.status,
        error: cleanMessage,
      })
    } finally {
      setIsGeneratingQuestions(false)
    }
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{effectiveAssessmentId ? 'Modifier l evaluation' : 'Creer une evaluation'}</h1>
          <p>Assistant en 4 etapes : parametres, questions, revision, publication.</p>
        </div>
        <Link className="outline-button" to="/professor/assessments">Retour</Link>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      <div className="tabs-row">
        {[1, 2, 3, 4].map((item) => (
          <button
            className={step === item ? 'active' : ''}
            disabled={isSavingDraft || isGeneratingQuestions}
            key={item}
            onClick={() => goToStep(item)}
            type="button"
          >
            Etape {item}
          </button>
        ))}
      </div>
      {step === 1 && (
        <article className="panel-card admin-course-form">
          <h3>Parametres</h3>
          <label>Titre<input onChange={(event) => updateField('title', event.target.value)} value={draft.title} /></label>
          <div className="admin-form-row">
            <label>Classe<select onChange={(event) => updateField('classroom_id', event.target.value)} value={draft.classroom_id}>
              <option value="">Aucune classe</option>
              {classrooms.map((classroom) => <option key={classroom.id} value={classroom.id}>{classroom.name}</option>)}
            </select></label>
            <label>Cours<select onChange={(event) => updateField('course_id', event.target.value)} value={draft.course_id}>
              <option value="">Choisir</option>
              {courses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
            </select></label>
            <label>Difficulte<select onChange={(event) => updateField('difficulty_level_id', event.target.value)} value={draft.difficulty_level_id}>
              <option value="">Non definie</option>
              {difficulties.map((difficulty) => <option key={difficulty.id} value={difficulty.id}>{difficulty.name}</option>)}
            </select></label>
          </div>
          <div className="admin-form-row">
            <label>Type<select onChange={(event) => updateField('assessment_type', event.target.value)} value={draft.assessment_type}>
              <option value="initial">Initiale</option>
              <option value="personalized">Personnalisee</option>
              <option value="final">Finale</option>
              <option value="practice">Entrainement</option>
            </select></label>
            <label>Publication<input onChange={(event) => updateField('publication_at', event.target.value)} type="datetime-local" value={draft.publication_at} /></label>
            <label>Expiration<input onChange={(event) => updateField('expires_at', event.target.value)} type="datetime-local" value={draft.expires_at} /></label>
          </div>
          <div className="admin-form-row">
            <label>Temps limite<input onChange={(event) => updateField('time_limit_minutes', event.target.value)} type="number" value={draft.time_limit_minutes} /></label>
            <label>Tentatives<input min="1" onChange={(event) => updateField('max_attempts', Number(event.target.value))} type="number" value={draft.max_attempts} /></label>
          </div>
          <label>Description<textarea onChange={(event) => updateField('description', event.target.value)} value={draft.description} /></label>
          <label>Instructions<textarea onChange={(event) => updateField('instructions', event.target.value)} value={draft.instructions} /></label>
          <button className="primary-button" disabled={isSavingDraft || !Number(draft.course_id)} onClick={() => goToStep(2)} type="button">
            {isSavingDraft ? 'Creation du brouillon...' : 'Sauvegarder et continuer'}
          </button>
        </article>
      )}
      {step === 2 && (
        <article className="panel-card admin-course-form">
          <div className="panel-title assessment-question-toolbar">
            <div>
              <h2>Questions</h2>
              <p>{draft.questions.length} questions dans cette evaluation. Demande actuelle : {proposalCount} propositions.</p>
            </div>
            <div className="assessment-proposal-actions">
              <label>
                Nombre
                <input
                  max="10"
                  min="1"
                  onChange={(event) => setProposalCount(Math.max(1, Math.min(10, Number(event.target.value) || 1)))}
                  type="number"
                  value={proposalCount}
                />
              </label>
              <label>
                Mode
                <select onChange={(event) => setProposalMode(event.target.value)} value={proposalMode}>
                  <option value="append">Ajouter aux questions existantes</option>
                  <option value="replace">Remplacer les propositions non validees</option>
                </select>
              </label>
              <button className="outline-button" disabled={isGeneratingQuestions || isSavingDraft || !Number(draft.course_id)} onClick={proposeQuestions} type="button">
                {isGeneratingQuestions ? 'Generation en cours...' : 'Proposer depuis le cours'}
              </button>
            </div>
          </div>
          {draft.questions.map((question, index) => (
            <div className="professor-question-editor" key={`${question.id || 'new'}-${index}`}>
              <div className="assessment-question-meta">
                <strong>Question {index + 1}</strong>
                {question.draft && <span className="assessment-draft-badge">Brouillon propose</span>}
                <label>
                  Chapitre
                  <select onChange={(event) => updateQuestion(index, 'chapter_id', event.target.value)} value={question.chapter_id || ''}>
                    <option value="">Aucun chapitre</option>
                    {(selectedCourse?.chapters || []).map((chapter) => <option key={chapter.id} value={chapter.id}>{chapter.title}</option>)}
                  </select>
                </label>
                <label>
                  Difficulte
                  <select onChange={(event) => updateQuestion(index, 'difficulty_level_id', event.target.value)} value={question.difficulty_level_id || ''}>
                    <option value="">Non definie</option>
                    {difficulties.map((difficulty) => <option key={difficulty.id} value={difficulty.id}>{difficulty.name}</option>)}
                  </select>
                </label>
                <button className="question-remove-button" onClick={() => removeQuestion(index)} type="button">Supprimer</button>
              </div>

              <label className="question-full-field">
                Question
                <textarea onChange={(event) => updateQuestion(index, 'question', event.target.value)} placeholder="Redigez une question precise" value={question.question} />
              </label>

              <div className="question-choice-grid">
                {normalizeChoices(question.choices).map((choice, choiceIndex) => (
                  <label key={choiceIndex}>
                    Choix {choiceIndex + 1}
                    <input onChange={(event) => updateChoice(index, choiceIndex, event.target.value)} value={choice} />
                  </label>
                ))}
              </div>

              <label className="question-full-field">
                Bonne reponse
                <select onChange={(event) => updateQuestion(index, 'correct_answer', event.target.value)} value={question.correct_answer || ''}>
                  <option value="">Choisir la bonne reponse</option>
                  {normalizeChoices(question.choices).filter(Boolean).map((choice) => (
                    <option key={choice} value={choice}>{choice}</option>
                  ))}
                </select>
              </label>

              <label className="question-full-field">
                Explication
                <textarea onChange={(event) => updateQuestion(index, 'explanation', event.target.value)} placeholder="Expliquez pourquoi cette reponse est correcte" value={question.explanation || ''} />
              </label>
            </div>
          ))}
          {!draft.questions.length && <p className="admin-empty">Aucune question pour le moment.</p>}
          <button className="outline-button" onClick={() => addQuestion()} type="button">Ajouter une question</button>
        </article>
      )}
      {step === 3 && (
        <article className="panel-card">
          <h3>Revision</h3>
          <p>{draft.questions.length} questions. Les reponses sont visibles uniquement ici pour validation professeur.</p>
          {draft.questions.map((question, index) => <p className="question-index" key={`${question.question}-${index}`}><span>{index + 1}</span>{question.question} - reponse : {question.correct_answer}</p>)}
        </article>
      )}
      {step === 4 && (
        <article className="panel-card admin-course-form">
          <h3>Publication</h3>
          <label>Statut<select onChange={(event) => updateField('status', normalizeAssessmentStatus(event.target.value))} value={normalizeAssessmentStatus(draft.status)}>
            <option value="draft">Brouillon</option>
            <option value="scheduled">Planifie</option>
            <option value="published">Publie</option>
            <option value="closed">Ferme</option>
            <option value="archived">Archive</option>
          </select></label>
          <button className="primary-button" disabled={isSavingDraft} onClick={savePublicationWorkflow} type="button">{isSavingDraft ? 'Sauvegarde...' : 'Sauvegarder'}</button>
        </article>
      )}
    </section>
  )
}

function parseStep(rawStep) {
  const parsed = Number(rawStep) || STEP_MIN
  return parsed >= STEP_MIN && parsed <= STEP_MAX ? parsed : STEP_MIN
}

function normalizeDraftFromApi(data) {
  return {
    ...data,
    classroom_id: data.classroom_id || '',
    course_id: data.course_id || '',
    subject_id: data.subject_id || '',
    difficulty_level_id: data.difficulty_level_id || '',
    publication_at: data.publication_at ? data.publication_at.slice(0, 16) : '',
    expires_at: data.expires_at ? data.expires_at.slice(0, 16) : '',
    time_limit_minutes: data.time_limit_minutes || '',
    questions: (data.questions || []).map((question) => ({ ...question, choices: normalizeChoices(question.choices) })),
  }
}

function normalizePayload(draft, options = {}) {
  return {
    ...draft,
    title: draft.title || 'Évaluation brouillon',
    status: normalizeAssessmentStatus(draft.status),
    classroom_id: Number(draft.classroom_id) || null,
    course_id: Number(draft.course_id),
    subject_id: Number(draft.subject_id),
    difficulty_level_id: Number(draft.difficulty_level_id) || null,
    publication_at: draft.publication_at || null,
    expires_at: draft.expires_at || null,
    time_limit_minutes: Number(draft.time_limit_minutes) || null,
    max_attempts: Math.max(1, Number(draft.max_attempts) || 1),
    questions: draft.questions.map((question, index) => {
      const choices = normalizeChoices(question.choices).map((choice) => choice.trim()).filter(Boolean)
      return {
        ...question,
        choices,
        chapter_id: Number(question.chapter_id) || null,
        skill_id: Number(question.skill_id) || null,
        difficulty_level_id: Number(question.difficulty_level_id) || null,
        order_index: index + 1,
        active: options.forceActiveQuestions ? true : question.active !== false,
      }
    }),
  }
}

function normalizeChoices(choices) {
  const values = Array.isArray(choices) ? choices : []
  return [0, 1, 2, 3].map((index) => values[index] || '')
}

function normalizeAssessmentStatus(status) {
  const normalized = String(status || '').trim().toLowerCase()
  const aliases = {
    brouillon: 'draft',
    planifie: 'scheduled',
    planifiee: 'scheduled',
    programmee: 'scheduled',
    publie: 'published',
    publiee: 'published',
    ferme: 'closed',
    fermee: 'closed',
    archive: 'archived',
    archivee: 'archived',
  }
  const value = aliases[normalized] || normalized
  return ASSESSMENT_STATUSES.has(value) ? value : 'draft'
}

function isFutureDateTime(value) {
  if (!value) return false
  const date = new Date(value)
  return !Number.isNaN(date.getTime()) && date.getTime() > Date.now()
}

function logAssessmentDebug(eventName, payload) {
  if (import.meta.env.DEV) {
    console.info(`[ProfessorAssessmentEditor] ${eventName}`, payload)
  }
}

export default ProfessorAssessmentEditorPage
