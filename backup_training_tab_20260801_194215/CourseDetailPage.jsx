import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, BookOpen, CheckCircle2, Download, ExternalLink, FileText, Lock, Play, Target } from 'lucide-react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  API_BASE_URL,
  fetchCourseById,
  getChapterExercises,
  submitChapterExercise,
  testOllamaVariantPreview,
  updateCourseProgress,
} from '../services/api.js'
import { addNotification } from '../services/notifications.js'
import { useAuth } from '../hooks/useAuth.js'

const TABS = [
  { id: 'content', label: 'Contenu', icon: BookOpen },
  { id: 'summary', label: 'Resume', icon: FileText },
  { id: 'examples', label: 'Exemples', icon: CheckCircle2 },
  { id: 'objectives', label: 'Objectifs', icon: Target },
]

const CHAPTER_TABS = [
  { id: 'resume', label: 'Résumé' },
  { id: 'sequences', label: 'Séquences' },
  { id: 'schemas', label: 'Schémas' },
  { id: 'training_exams', label: 'Entraînement' },
  { id: 'regional_exams', label: 'Examens régionaux' },
  { id: 'corrections', label: 'Corrections' },
  { id: 'takeaways', label: 'À retenir' },
]

const CHAPTER_PROGRESS_STORAGE_KEY = 'edumentor:chapterProgress'
const CHAPTER_EXERCISE_DRAFTS_STORAGE_KEY = 'edumentor:chapterExerciseDrafts'

function CourseDetailPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { id } = useParams()
  const { userProfile } = useAuth()
  const [course, setCourse] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [errorStatus, setErrorStatus] = useState(null)
  const [diagnosticResult, setDiagnosticResult] = useState(null)
  const [activeTab, setActiveTab] = useState('content')
  const [selectedChapter, setSelectedChapter] = useState(null)
  const [selectedExample, setSelectedExample] = useState(null)
  const [notice, setNotice] = useState('')
  const [chapterProgressMap, setChapterProgressMap] = useState({})
  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  )
  const requestedChapterId = Number(searchParams.get('chapter_id') || 0)
  const requestedMode = searchParams.get('mode') || 'review'
  const ollamaTestMode = String(id) === '23' && searchParams.get('ollamaTest') === '1'

  useEffect(() => {
    try {
      const storedResult = localStorage.getItem('diagnosticResult')
      setDiagnosticResult(storedResult ? JSON.parse(storedResult) : null)
    } catch {
      setDiagnosticResult(null)
    }
  }, [])

  useEffect(() => {
    setChapterProgressMap(loadChapterProgressMap())
  }, [])

  useEffect(() => {
    let isMounted = true

    setSelectedChapter(null)
    setSelectedExample(null)
    setNotice('')
    setIsLoading(true)

    fetchCourseById(id)
      .then((data) => {
        if (isMounted) {
          setCourse(data)
          setErrorStatus(null)
        }
      })
      .catch((error) => {
        if (isMounted) {
          setErrorStatus(error.status || 500)
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
  }, [id, ollamaTestMode])

  const courseWithLocalProgress = useMemo(
    () => applyLocalChapterProgress(course, chapterProgressMap[course?.id]),
    [course, chapterProgressMap],
  )
  const normalizedLearnerLevel = normalizeLevel(
    courseWithLocalProgress?.learner_level || resolveLearnerLevel(diagnosticResult, userProfile, courseWithLocalProgress),
  )
  const learnerLevel = getDisplayLevel(normalizedLearnerLevel)
  const courseWithSelectedVariant = useMemo(
    () => applySelectedVariant(courseWithLocalProgress, normalizedLearnerLevel),
    [courseWithLocalProgress, normalizedLearnerLevel],
  )
  const courseContent = useMemo(() => buildCourseContent(courseWithSelectedVariant), [courseWithSelectedVariant])

  useEffect(() => {
    if (courseContent.chapters.length === 0) {
      return
    }

    const requestedChapter = requestedChapterId
      ? courseContent.chapters.find(
        (chapter) => Number(chapter.id) === Number(requestedChapterId),
      )
      : null

    if (
      requestedChapter
      && Number(selectedChapter?.id) !== Number(requestedChapter.id)
    ) {
      setSelectedChapter(requestedChapter)
      return
    }

    if (!selectedChapter) {
      setSelectedChapter(getInitialSelectedChapter(courseContent.chapters))
      return
    }

    const syncedChapter = courseContent.chapters.find(
      (chapter) => Number(chapter.id) === Number(selectedChapter.id)
        || chapter.title === selectedChapter.title,
    )
    if (syncedChapter && syncedChapter !== selectedChapter) {
      setSelectedChapter(syncedChapter)
    }
  }, [courseContent.chapters, requestedChapterId, selectedChapter])

  useEffect(() => {
    if (!selectedExample && courseContent.examples.length > 0) {
      setSelectedExample(courseContent.examples[0])
    }
  }, [courseContent.examples, selectedExample])

  if (isLoading) {
    return (
      <section className="page-section course-detail-page">
        <button className="back-link" onClick={() => navigate('/courses')} type="button"><ArrowLeft size={20} /> Retour aux cours</button>
        <article className="panel-card">
          <h1>Chargement du cours...</h1>
          <p>Les informations du cours sont recuperees depuis le backend.</p>
        </article>
      </section>
    )
  }

  if (errorStatus === 404) {
    return (
      <section className="page-section course-detail-page">
        <button className="back-link" onClick={() => navigate('/courses')} type="button"><ArrowLeft size={20} /> Retour aux cours</button>
        <article className="panel-card">
          <h1>Cours introuvable</h1>
          <p>Le cours demande n'existe pas ou n'est plus disponible.</p>
          <button className="primary-button" onClick={() => navigate('/courses')} type="button">Voir mes cours</button>
        </article>
      </section>
    )
  }

  if (!course) {
    return (
      <section className="page-section course-detail-page">
        <button className="back-link" onClick={() => navigate('/courses')} type="button"><ArrowLeft size={20} /> Retour aux cours</button>
        <article className="panel-card">
          <h1>Cours indisponible</h1>
          <p>Impossible de charger les informations du cours depuis le backend.</p>
        </article>
      </section>
    )
  }

  return (
    <section className="page-section course-detail-page">
      <button className="back-link" onClick={() => navigate('/courses')} type="button"><ArrowLeft size={20} /> Retour aux cours</button>
      <div className="detail-layout">
        <div className="detail-main">
          <section className="course-hero">
            <span className="course-big-icon"><BookOpen size={64} /><strong>{courseWithSelectedVariant.tag || String(courseWithSelectedVariant.id).padStart(2, '0')}</strong></span>
            <div>
              <h1>{courseWithSelectedVariant.title}</h1>
              <span className="course-level-badge">Niveau de l'apprenant : {learnerLevel}</span>
              {courseWithSelectedVariant.aiVariantApplied && <span className="course-level-badge">Contenu adapte par IA - Niveau {learnerLevel}</span>}
              {courseWithSelectedVariant.subject && <span className="course-level-badge">{courseWithSelectedVariant.subject.name}</span>}
              {courseWithSelectedVariant.difficulty_level && <span className="course-level-badge">{courseWithSelectedVariant.difficulty_level.name}</span>}
              {courseWithSelectedVariant.education_level && <span className="course-level-badge">{courseWithSelectedVariant.education_level.name}</span>}
              <p>{courseWithSelectedVariant.summary}</p>
              {courseWithSelectedVariant.aiVariantApplied && (
                <p className="course-variant-provenance">
                  {hasGeneratedAiVariant(courseWithSelectedVariant.selected_variant)
                    ? 'Contenu partiellement adapté par IA'
                    : 'Version de secours deterministe'}
                </p>
              )}
              <div className="course-hero-progress">
                <span>Progression dans ce cours</span>
                <div className="progress-track"><span style={{ width: `${courseContent.progress}%` }} /></div>
                <strong>{courseContent.progress}%</strong>
                <small>({courseContent.completedChapters}/{courseContent.chapters.length} chapitres)</small>
              </div>
            </div>
          </section>

          <nav className="tabs-row">
            {TABS.map((tab) => {
              const Icon = tab.icon
              return (
                <button
                  className={activeTab === tab.id ? 'active' : ''}
                  key={tab.id}
                  onClick={() => {
                    setActiveTab(tab.id)
                    setNotice('')
                  }}
                  type="button"
                >
                  <Icon size={18} />{tab.label}
                </button>
              )
            })}
          </nav>

          <ContentPanel
            activeTab={activeTab}
            courseId={courseWithSelectedVariant.id}
            courseContent={courseContent}
            learnerLevel={learnerLevel}
            notice={notice}
            ollamaTestMode={ollamaTestMode}
            requestedMode={requestedMode}
            onSelectExample={setSelectedExample}
            onSelectChapter={(chapter) => {
              setSelectedChapter(chapter)
              setNotice('')
            }}
            onSelectNextChapter={() => {
              const currentIndex = courseContent.chapters.findIndex((chapter) => chapter.title === selectedChapter?.title)

              if (!courseWithSelectedVariant || currentIndex === -1) {
                return
              }

              const isLastChapter = currentIndex === courseContent.chapters.length - 1
              const nextProgress = isLastChapter
                ? 100
                : calculateChapterProgress(currentIndex + 1, courseContent.chapters.length)
              const updatedChapters = advanceChapters(courseContent.chapters, currentIndex)
              const progressRecord = buildChapterProgressRecord(updatedChapters, nextProgress)

              setChapterProgressMap((previousMap) => {
                const nextMap = {
                  ...previousMap,
                  [courseWithSelectedVariant.id]: progressRecord,
                }
                persistChapterProgress(courseWithSelectedVariant.id, progressRecord, nextMap)
                return nextMap
              })

              if (isLastChapter) {
                const completedCurrentChapter = {
                  ...courseContent.chapters[currentIndex],
                  completed: true,
                  status: 'completed',
                  openable: true,
                }
                setSelectedChapter(completedCurrentChapter)
                addNotification({
                  type: 'progress',
                  title: 'Progression mise à jour',
                  message: `Votre progression dans ${courseWithSelectedVariant.title} est maintenant de 100%.`,
                })
                setNotice('Cours terminé')
                addNotification({
                  type: 'progress',
                  title: 'Cours terminé',
                  message: `Vous avez terminé le cours ${courseWithSelectedVariant.title}.`,
                })
                return
              }

              const nextChapter = {
                ...courseContent.chapters[currentIndex + 1],
                ...updatedChapters[currentIndex + 1],
              }
              setSelectedChapter(nextChapter)
              setNotice('')
              addNotification({
                type: 'progress',
                title: 'Nouveau chapitre débloqué',
                message: `Le chapitre "${nextChapter.title}" est maintenant disponible.`,
              })
              addNotification({
                type: 'progress',
                title: 'Progression mise à jour',
                message: `Votre progression dans ${courseWithSelectedVariant.title} est maintenant de ${nextProgress}%.`,
              })
            }}
            selectedExample={selectedExample}
            selectedChapter={selectedChapter}
          />
        </div>
        <aside className="detail-side">
          <article className="panel-card course-info">
            <h2>Informations du cours</h2>
            <InfoLine label="Matière" value={courseWithSelectedVariant.subject?.name || '-'} />
            <InfoLine label="Niveau apprenant" value={learnerLevel} highlight />
            <InfoLine label="Difficulte" value={courseWithSelectedVariant.difficulty_level?.name || courseWithSelectedVariant.level || '-'} />
            <InfoLine label="Niveau d'etudes" value={courseWithSelectedVariant.education_level?.name || '-'} />
            <InfoLine label="Professeur" value={courseWithSelectedVariant.professor?.full_name || '-'} />
            <InfoLine label="Durée estimée" value={courseWithSelectedVariant.estimated_duration || courseContent.information.duration} />
            <InfoLine label="Prérequis" value={courseWithSelectedVariant.prerequisites || '-'} />
            <InfoLine label="Chapitres" value={courseContent.information.chapters_count} />
            {courseContent.information.language !== '-' && <InfoLine label="Langue" value={courseContent.information.language} />}
            <InfoLine label="Derniere mise a jour" value={courseContent.information.last_update} />
          </article>
          {courseWithSelectedVariant.quiz?.active !== false && courseWithSelectedVariant.quiz?.published !== false && courseWithSelectedVariant.quiz?.questions?.length > 0 && <article className="panel-card center-card">
            <button className="primary-button quiz-cta" onClick={() => navigate(`/quiz/${courseWithSelectedVariant.id}`)} type="button"><FileText size={24} />Commencer le quiz</button>
            <p>Testez vos connaissances sur ce cours</p>
          </article>}
          {courseWithSelectedVariant.pdf_url && <button
            className="download-button"
            onClick={() => {
              window.open(resolvePdfUrl(courseWithSelectedVariant.pdf_url), '_blank', 'noopener,noreferrer')
              addNotification({
                type: 'pdf',
                title: 'Support PDF téléchargé',
                message: `Le support PDF du cours ${courseWithSelectedVariant.title} a été ouvert.`,
              })
            }}
            type="button"
          >
            <Download size={22} />Telecharger le support PDF
          </button>}
        </aside>
      </div>
    </section>
  )
}

function ContentPanel({
  activeTab,
  courseId,
  courseContent,
  learnerLevel,
  notice,
  ollamaTestMode,
  requestedMode,
  onSelectChapter,
  onSelectExample,
  onSelectNextChapter,
  selectedChapter,
  selectedExample,
}) {
  if (activeTab === 'summary') {
    return (
      <article className="panel-card lesson-panel">
        <h2>Resume</h2>
        <section className="rich-section">
          <h3>Vue generale</h3>
          <p>{courseContent.summary}</p>
          {courseContent.description && <p>{courseContent.description}</p>}
        </section>
        {courseContent.summarySections.keyPoints.length > 0 && (
          <section className="rich-section">
            <h3>Points clés</h3>
            <ul>{courseContent.summarySections.keyPoints.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
        )}
        {courseContent.summarySections.importantConcepts.length > 0 && (
          <section className="rich-section">
            <h3>Notions importantes</h3>
            <ul>{courseContent.summarySections.importantConcepts.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
        )}
        {courseContent.summarySections.takeaways.length > 0 && (
          <section className="rich-section">
            <h3>A retenir</h3>
            <ul>{courseContent.summarySections.takeaways.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
        )}
      </article>
    )
  }

  if (activeTab === 'examples') {
    return (
      <article className="panel-card examples-panel">
        <h2>Exemples</h2>
        {courseContent.examples.length > 0 ? <div className="example-grid">
          {courseContent.examples.map((item) => (
            <button
              className={selectedExample?.title === item.title ? 'example-card active' : 'example-card'}
              key={item.title}
              onClick={() => onSelectExample(item)}
              type="button"
            >
              <span />
              <strong>{item.title}</strong>
              <p>{item.description}</p>
            </button>
          ))}
        </div> : <p className="admin-empty">Aucun exemple ajoute.</p>}
        {selectedExample && (
          <article className="lesson-panel example-detail">
            <h3>{selectedExample.title}</h3>
            <p>{selectedExample.fullDescription}</p>
            <h4>Explication</h4>
            <p>{selectedExample.explanation}</p>
            <h4>Resultat attendu</h4>
            <p>{selectedExample.expectedResult}</p>
            {selectedExample.code && <pre><code>{selectedExample.code}</code></pre>}
          </article>
        )}
      </article>
    )
  }

  if (activeTab === 'objectives') {
    return (
      <>
        <article className="panel-card objectives-panel">
          <h2>Objectifs</h2>
          {courseContent.objectives.map((item, index) => (
            <label className="objective-check" key={item}>
              <input checked={index < courseContent.completedObjectiveCount} readOnly type="checkbox" />
              <span>{item}</span>
            </label>
          ))}
          {courseContent.objectives.length === 0 && <p className="admin-empty">Aucun objectif ajoute.</p>}
        </article>
        <article className="panel-card objectives-panel">
          <h2>Competences acquises</h2>
          {courseContent.skills.map((item, index) => (
            <p className={index < courseContent.unlockedSkillCount ? 'skill-unlocked' : 'skill-locked'} key={item}>
              {index < courseContent.unlockedSkillCount ? <CheckCircle2 size={20} /> : <Lock size={20} />}
              {item}
            </p>
          ))}
          {courseContent.skills.length === 0 && <p className="admin-empty">Aucune competence ajoutee.</p>}
        </article>
      </>
    )
  }

  return (
    <>
      <article className="panel-card content-panel">
        <h2>Contenu</h2>
        {courseContent.chapters.map((item, index) => (
          <div
            className={selectedChapter?.title === item.title || item.openable === true ? 'lesson-row active' : 'lesson-row'}
            key={item.title}
            onClick={() => onSelectChapter(item)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelectChapter(item)
              }
            }}
            role="button"
            tabIndex={0}
          >
            <span>{item.openable === true ? <Play size={18} /> : <Lock size={18} />}</span>
            <strong>{index + 1}. {item.title}</strong>
            <time>{item.duration}</time>
            {item.completed === true && <CheckCircle2 size={22} />}
          </div>
        ))}
      </article>
      {notice && (
        <article className="panel-card lesson-panel">
          <p>{notice}</p>
        </article>
      )}
      {selectedChapter && !notice && selectedChapter.openable === false && (
        <article className="panel-card lesson-panel">
          <p>Ce chapitre est verrouille</p>
        </article>
      )}
      {selectedChapter && !notice && selectedChapter.openable === true && (
        <ChapterLesson
          chapter={selectedChapter}
          courseId={courseId}
          hasNext={courseContent.chapters.findIndex((chapter) => chapter.title === selectedChapter.title) < courseContent.chapters.length - 1}
          initialMode={requestedMode}
          learnerLevel={learnerLevel}
          ollamaTestMode={ollamaTestMode}
          onNext={onSelectNextChapter}
        />
      )}
    </>
  )
}

function ChapterLesson({ chapter, courseId, hasNext, initialMode, learnerLevel, ollamaTestMode, onNext }) {
  const normalizedLevel = normalizeLevel(learnerLevel)
  const initialChapterTab = initialMode === 'exercise' ? 'training_exams' : 'resume'
  const [activeChapterTab, setActiveChapterTab] = useState(initialChapterTab)
  const [ollamaPreviewView, setOllamaPreviewView] = useState('current')
  const [ollamaPreview, setOllamaPreview] = useState(null)
  const [ollamaPreviewError, setOllamaPreviewError] = useState('')
  const [isGeneratingOllamaPreview, setIsGeneratingOllamaPreview] = useState(false)
  const [exerciseState, setExerciseState] = useState({ loading: false, message: '', exercises: [], progress: null })
  const [exerciseAnswers, setExerciseAnswers] = useState({})
  const [exerciseResults, setExerciseResults] = useState({})
  const [currentExerciseIndex, setCurrentExerciseIndex] = useState(0)
  const [validatingExerciseId, setValidatingExerciseId] = useState('')
  const [studyPathSync, setStudyPathSync] = useState(null)
  const rawBlocks = selectChapterBlocks(chapter, learnerLevel)
  const normalizedBlocks = normalizeRawChapterBlocks(rawBlocks, chapter)
  const blocks = sanitizeRenderableBlocks(normalizedBlocks, chapter, normalizedLevel)
  const fallbackParagraphs = splitParagraphs(chapter.content)
  const displayBlocks = prepareChapterDisplayBlocks(blocks, chapter)
  const chapterSections = useMemo(() => classifyChapterBlocks(displayBlocks), [displayBlocks])
  const visibleChapterTabs = useMemo(
    () => CHAPTER_TABS.filter((tab) => chapterSections[tab.id]?.length > 0),
    [chapterSections],
  )
  const useChapterTabs = visibleChapterTabs.length > 1

  useEffect(() => {
    setActiveChapterTab(initialChapterTab)
    setOllamaPreviewView('current')
    setOllamaPreview(null)
    setOllamaPreviewError('')
    setExerciseState({ loading: false, message: '', exercises: [], progress: null })
    setExerciseAnswers(loadChapterExerciseDrafts(courseId, chapter?.id))
    setExerciseResults({})
    setCurrentExerciseIndex(0)
    setValidatingExerciseId('')
    setStudyPathSync(null)
  }, [chapter?.id, chapter?.title, courseId, initialChapterTab])

  useEffect(() => {
    if (!useChapterTabs) return
    const activeTabExists = visibleChapterTabs.some((tab) => tab.id === activeChapterTab)
    if (!activeTabExists) {
      setActiveChapterTab(visibleChapterTabs[0]?.id || 'resume')
    }
  }, [activeChapterTab, useChapterTabs, visibleChapterTabs])

  const activeBlocks = chapterSections[activeChapterTab] || []
  const renderedActiveBlocks = activeChapterTab === 'corrections'
    ? numberChapterCorrections(activeBlocks)
    : activeBlocks
  const canTestOllama = ollamaTestMode && Number(chapter.id) === 197
  const currentExercise = exerciseState.exercises[currentExerciseIndex]
  const answeredExerciseCount = exerciseState.exercises.filter((exercise) => exerciseAnswers[exercise.id]?.trim()).length
  const validatedExerciseCount = Object.keys(exerciseResults).length
  const seriesScore = calculateExerciseSeriesScore(exerciseResults)

  useEffect(() => {
    let cancelled = false
    if (activeChapterTab !== 'training_exams' || !courseId || !chapter?.id) {
      return undefined
    }

    setExerciseState((current) => ({ ...current, loading: true, message: '' }))
    getChapterExercises(courseId, chapter.id)
      .then((data) => {
        if (cancelled) return
        const progress = data.progress || null
        const restoredResults = Object.fromEntries(
          (Array.isArray(progress?.latest_results) ? progress.latest_results : [])
            .filter((item) => item?.question_id)
            .map((item) => [item.question_id, item]),
        )

        setExerciseState({
          loading: false,
          message: '',
          exercises: Array.isArray(data.exercises) ? data.exercises : [],
          progress,
        })
        setExerciseResults(restoredResults)
      })
      .catch((error) => {
        if (cancelled) return
        setExerciseState({
          loading: false,
          message: error?.message || 'Exercices indisponibles pour ce chapitre.',
          exercises: [],
          progress: null,
        })
      })

    return () => {
      cancelled = true
    }
  }, [activeChapterTab, chapter?.id, courseId])

  async function generateOllamaPreview() {
    setIsGeneratingOllamaPreview(true)
    setOllamaPreviewError('')
    setOllamaPreview(null)
    try {
      const preview = await testOllamaVariantPreview()
      if (preview?.validation_status !== 'rejected') {
        const validationErrors = validateOllamaPreviewForDisplay(preview)
        if (validationErrors.length > 0) {
          throw new Error(`Preview Ollama rejetee localement : ${validationErrors.join('; ')}`)
        }
      }
      setOllamaPreview(preview)
      setOllamaPreviewView('ollama')
    } catch {
      setOllamaPreviewError('La génération locale n’a pas satisfait les critères pédagogiques. Le contenu actuel reste inchangé.')
    } finally {
      setIsGeneratingOllamaPreview(false)
    }
  }

  function updateExerciseAnswer(questionId, value) {
    setExerciseAnswers((current) => {
      const nextAnswers = { ...current, [questionId]: value }
      persistChapterExerciseDrafts(courseId, chapter?.id, nextAnswers)
      return nextAnswers
    })
  }

  async function validateCurrentExercise() {
    if (!currentExercise || !courseId || !chapter?.id) return
    const answer = String(exerciseAnswers[currentExercise.id] || '').trim()
    if (!answer) return
    setValidatingExerciseId(currentExercise.id)
    setExerciseState((current) => ({ ...current, message: '' }))
    try {
      const result = await submitChapterExercise(courseId, chapter.id, currentExercise.id, { answer })
      setExerciseResults((current) => ({ ...current, [currentExercise.id]: result }))
      setExerciseState((current) => ({ ...current, progress: result.progress || current.progress }))
      setStudyPathSync(result.study_path_sync || null)
    } catch (error) {
      setExerciseState((current) => ({
        ...current,
        message: error?.message || 'Impossible de valider cette réponse.',
      }))
    } finally {
      setValidatingExerciseId('')
    }
  }

  return (
    <article className="panel-card lesson-panel chapter-lesson">
      <header className="lesson-chapter-header">
        <h2>{chapter.title}</h2>
        <p>{chapter.estimated_duration || chapter.duration || 'Durée non définie'}</p>
        <span className="course-level-badge">
          {chapter.ai_variant_status === 'ai_generated'
            ? chapter.ai_variant_label || `Adapté par IA — Niveau ${learnerLevel}`
            : 'Contenu original du professeur — variante IA indisponible'}
        </span>
        {canTestOllama && (
          <button
            className="outline-button"
            disabled={isGeneratingOllamaPreview}
            onClick={generateOllamaPreview}
            type="button"
          >
            Tester avec Ollama
          </button>
        )}
      </header>

      {canTestOllama && (
        <div className="chapter-section-tabs" aria-label="Comparaison du contenu">
          <button
            aria-selected={ollamaPreviewView === 'current'}
            className={ollamaPreviewView === 'current' ? 'chapter-section-tab active' : 'chapter-section-tab'}
            onClick={() => setOllamaPreviewView('current')}
            role="tab"
            type="button"
          >
            Contenu actuel
          </button>
          <button
            aria-selected={ollamaPreviewView === 'ollama'}
            className={ollamaPreviewView === 'ollama' ? 'chapter-section-tab active' : 'chapter-section-tab'}
            disabled={!ollamaPreview}
            onClick={() => setOllamaPreviewView('ollama')}
            role="tab"
            type="button"
          >
            Preview Ollama
          </button>
        </div>
      )}

      {isGeneratingOllamaPreview && (
        <section className="rich-section">
          <p>Generation locale en cours... cela peut prendre plusieurs minutes</p>
        </section>
      )}

      {ollamaPreviewError && (
        <section className="rich-section">
          <p className="admin-empty">{ollamaPreviewError}</p>
        </section>
      )}

      {useChapterTabs && (
        <nav aria-label="Sections du chapitre" className="chapter-section-tabs">
          {visibleChapterTabs.map((tab) => (
            <button
              aria-selected={activeChapterTab === tab.id}
              className={activeChapterTab === tab.id ? 'chapter-section-tab active' : 'chapter-section-tab'}
              key={tab.id}
              onClick={() => setActiveChapterTab(tab.id)}
              role="tab"
              type="button"
            >
              {tab.label}
              <span>{chapterSections[tab.id].length}</span>
            </button>
          ))}
        </nav>
      )}

      {useChapterTabs && (
        <section className="chapter-section-content" role="tabpanel">
          {activeChapterTab === 'training_exams'
            ? (
              <ChapterExercisesPanel
                answeredCount={answeredExerciseCount}
                answer={currentExercise ? exerciseAnswers[currentExercise.id] || '' : ''}
                currentIndex={currentExerciseIndex}
                exercise={currentExercise}
                fallbackBlocks={renderedActiveBlocks}
                loading={exerciseState.loading}
                message={exerciseState.message}
                onAnswerChange={(value) => currentExercise && updateExerciseAnswer(currentExercise.id, value)}
                onNext={() => setCurrentExerciseIndex((index) => Math.min(exerciseState.exercises.length - 1, index + 1))}
                onPrevious={() => setCurrentExerciseIndex((index) => Math.max(0, index - 1))}
                onValidate={validateCurrentExercise}
                progress={exerciseState.progress}
                result={currentExercise ? exerciseResults[currentExercise.id] : null}
                seriesScore={seriesScore}
                studyPathSync={studyPathSync}
                total={exerciseState.exercises.length}
                validating={validatingExerciseId === currentExercise?.id}
                validatedCount={validatedExerciseCount}
              />
            )
            : activeChapterTab === 'regional_exams'
            ? <ChapterRegionalExams blocks={renderedActiveBlocks} chapterId={chapter.id} level={normalizedLevel} />
            : <StructuredLessonBlocks blocks={renderedActiveBlocks} chapterId={chapter.id} level={normalizedLevel} />}
        </section>
      )}

      {!useChapterTabs && displayBlocks.length > 0 && (
        <StructuredLessonBlocks blocks={displayBlocks} chapterId={chapter.id} level={normalizedLevel} />
      )}

      {blocks.length === 0 && fallbackParagraphs.length > 0 && (
        <section className="rich-section">
          {fallbackParagraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
        </section>
      )}
      {blocks.length === 0 && fallbackParagraphs.length === 0 && <p className="admin-empty">Aucun contenu ajoute pour ce chapitre.</p>}
      {ollamaPreview && (
        <OllamaPreviewPanel
          isActive={ollamaPreviewView === 'ollama'}
          onShowCurrent={() => setOllamaPreviewView('current')}
          preview={ollamaPreview}
        />
      )}
      {hasNext && <button className="primary-button" onClick={onNext} type="button">Chapitre suivant</button>}
    </article>
  )
}

function ChapterExercisesPanel({
  answeredCount,
  answer,
  currentIndex,
  exercise,
  fallbackBlocks,
  loading,
  message,
  onAnswerChange,
  onNext,
  onPrevious,
  onValidate,
  progress,
  result,
  seriesScore,
  studyPathSync,
  total,
  validating,
  validatedCount,
}) {
  if (loading) {
    return <p>Chargement des exercices...</p>
  }

  if (message) {
    return <p className="admin-empty">{message}</p>
  }

  if (!exercise) {
    return fallbackBlocks.length > 0
      ? <StructuredLessonBlocks blocks={fallbackBlocks} />
      : <p className="admin-empty">Aucun exercice interactif disponible pour ce chapitre.</p>
  }

  return (
    <div className="chapter-exercise-workspace">
      <div className="test-progress">
        <span>Question <strong>{currentIndex + 1}</strong> sur {total}</span>
        <div className="progress-track"><span style={{ width: `${total ? Math.round((answeredCount / total) * 100) : 0}%` }} /></div>
        <strong>{validatedCount}/{total} validée(s)</strong>
      </div>

      <article className="question-card quiz-card">
        <p>{exercise.competence || 'Compétence'}</p>
        <h2>Question {currentIndex + 1}</h2>
        <h3>{exercise.question}</h3>
        <p>{formatPoints(exercise.points)}</p>
        <ChapterExerciseInput answer={answer} exercise={exercise} onChange={onAnswerChange} />
        <div className="question-actions">
          <button className="ghost-button" disabled={currentIndex === 0} onClick={onPrevious} type="button">Précédent</button>
          <button className="primary-button" disabled={!String(answer || '').trim() || validating} onClick={onValidate} type="button">
            {validating ? 'Validation...' : 'Valider ma réponse'}
          </button>
          <button className="outline-button" disabled={currentIndex >= total - 1} onClick={onNext} type="button">Question suivante</button>
        </div>
      </article>

      {result && <ChapterExerciseResult result={result} />}

      {studyPathSync && (
        <article className={studyPathSync.item_completed ? 'panel-card correction-card' : 'panel-card'}>
          <div className="panel-title">
            <h2>
              {studyPathSync.item_completed
                ? 'Étape du parcours terminée automatiquement'
                : 'Progression du parcours'}
            </h2>
            <p>{Math.round(Number(studyPathSync.path_progress_percentage || 0))}%</p>
          </div>

          <p>{studyPathSync.message}</p>

          {!studyPathSync.item_completed && (
            <div className="profile-detail-list">
              <div>
                <span>Questions répondues</span>
                <strong>{studyPathSync.validated_questions}/{studyPathSync.total_questions}</strong>
              </div>
              <div>
                <span>Score de maîtrise</span>
                <strong>{Math.round(Number(studyPathSync.mastery_score || 0))}%</strong>
              </div>
              <div>
                <span>Score minimum</span>
                <strong>{studyPathSync.minimum_score}%</strong>
              </div>
            </div>
          )}

          {studyPathSync.path_id && (
            <button
              className="outline-button"
              onClick={() => window.location.assign(`/study-paths/${studyPathSync.path_id}`)}
              type="button"
            >
              Retour à mon parcours
            </button>
          )}
        </article>
      )}

      <article className="panel-card">
        <div className="panel-title">
          <h2>Résumé de la série</h2>
          <p>{Math.round(Number(progress?.mastery_score ?? seriesScore))}%</p>
        </div>
        <div className="profile-detail-list">
          <div><span>Questions validées</span><strong>{validatedCount}/{total}</strong></div>
          <div><span>Score de maîtrise</span><strong>{Math.round(Number(progress?.mastery_score ?? seriesScore))}%</strong></div>
          <div><span>Historique enregistré</span><strong>{progress?.attempts_count || 0} tentative(s)</strong></div>
          <div><span>Meilleur score</span><strong>{progress?.best_score || 0}%</strong></div>
        </div>
      </article>
    </div>
  )
}

function ChapterExerciseInput({ answer, exercise, onChange }) {
  const choices = Array.isArray(exercise.choices) ? exercise.choices : []
  if (choices.length > 0) {
    return (
      <div className="answer-list">
        {choices.map((choice, index) => (
          <button
            className={answer === choice ? 'answer-option selected' : 'answer-option'}
            key={`${exercise.id}-${choice}`}
            onClick={() => onChange(choice)}
            type="button"
          >
            <span />{String.fromCharCode(65 + index)}. {choice}
          </button>
        ))}
      </div>
    )
  }
  const rows = ['response_long', 'production_ecrite'].includes(exercise.type) ? 7 : 4
  return <textarea value={answer} onChange={(event) => onChange(event.target.value)} placeholder="Rédigez votre réponse ici." rows={rows} />
}

function ChapterExerciseResult({ result }) {
  const isPending = result.status === 'pending_teacher_review'
  const statusLabel = isPending
    ? 'Réponse enregistrée'
    : result.correct
      ? 'Réponse correcte'
      : 'Réponse incorrecte'
  return (
    <article className="panel-card correction-card">
      <div className="panel-title">
        <h2>{statusLabel}</h2>
        <p>{formatPoints(result.points_awarded)} / {formatPoints(result.max_points)}</p>
      </div>
      <div className="profile-detail-list">
        <div><span>Réponse donnée</span><strong>{result.answer || result.user_answer || '-'}</strong></div>
        <div><span>Compétence</span><strong>{result.competence || '-'}</strong></div>
        <div><span>Statut</span><strong>{result.status || 'validated'}</strong></div>
      </div>
      {result.correct_answer && <p><strong>Correction attendue :</strong> {result.correct_answer}</p>}
      {result.correction && <p>{result.correction}</p>}
      {result.explanation && <p>{result.explanation}</p>}
      {result.recommendation && <p>{result.recommendation}</p>}
    </article>
  )
}

function calculateExerciseSeriesScore(results) {
  const values = Object.values(results || {})
  const definitive = values.filter((item) => item?.status !== 'pending_teacher_review')
  if (definitive.length === 0) return 0
  const total = definitive.reduce((sum, item) => sum + Number(item.max_points || 1), 0)
  const awarded = definitive.reduce((sum, item) => sum + Number(item.points_awarded || 0), 0)
  return total ? Math.round((awarded / total) * 100) : 0
}

function formatPoints(value) {
  const number = Number(value || 0)
  return Number.isInteger(number) ? `${number} pt${number > 1 ? 's' : ''}` : `${number.toFixed(1)} pts`
}


function OllamaPreviewPanel({ isActive, onShowCurrent, preview }) {
  const content = preview?.content || {}
  const metrics = preview?.metrics || {}
  const isRejected = preview?.validation_status === 'rejected'
  const validationErrors = Array.isArray(preview?.validation_errors)
    ? preview.validation_errors
    : Array.isArray(metrics.validation_errors)
      ? metrics.validation_errors
      : []
  const vocabulary = Array.isArray(content.vocabulary) ? content.vocabulary : []
  const keyPoints = Array.isArray(content.key_points) ? content.key_points : []
  const support = Array.isArray(content.learning_support) ? content.learning_support : []
  const guidedSteps = Array.isArray(content.guided_example?.steps) ? content.guided_example.steps : []
  const totalSeconds = secondsFromNanoseconds(metrics.total_duration)

  return (
    <section className="rich-section" data-testid="ollama-preview">
      <span
        className="course-level-badge"
        style={isRejected ? { background: '#b91c1c', borderColor: '#7f1d1d', color: '#fff' } : undefined}
      >
        {isRejected ? 'Sortie expérimentale Ollama — Rejetée par validation' : 'Previsualisation locale - Ollama qwen3:1.7b'}
      </span>
      <h3>{isActive ? 'Preview Ollama' : 'Preview Ollama disponible'}</h3>
      {isRejected && (
        <>
          <p className="admin-empty">
            Ce contenu est affiché uniquement pour démontrer le fonctionnement et les limites du modèle local. Il n’est pas validé et ne sera pas enregistré.
          </p>
          {validationErrors.length > 0 && (
            <>
              <h4>Problèmes détectés</h4>
              <ul>{validationErrors.map((item) => <li key={item}>{translateOllamaValidationError(item)}</li>)}</ul>
            </>
          )}
        </>
      )}
      <p><strong>Temps total de generation :</strong> {totalSeconds ? `${totalSeconds} s` : '-'}</p>
      <h4>Resume</h4>
      <p>{content.summary}</p>
      <h4>Explication</h4>
      <p>{content.explanation}</p>
      {keyPoints.length > 0 && (
        <>
          <h4>Points cles</h4>
          <ul>{keyPoints.map((item) => <li key={item}>{item}</li>)}</ul>
        </>
      )}
      {vocabulary.length > 0 && (
        <>
          <h4>Vocabulaire</h4>
          <ul>{vocabulary.map((item) => <li key={item.term}><strong>{item.term}</strong> : {item.definition}</li>)}</ul>
        </>
      )}
      {content.guided_example && (
        <>
          <h4>Sequences</h4>
          <p><strong>{content.guided_example.title}</strong></p>
          <p>{content.guided_example.content}</p>
          {guidedSteps.length > 0 && <ul>{guidedSteps.map((step) => <li key={step}>{step}</li>)}</ul>}
        </>
      )}
      {support.length > 0 && (
        <>
          <h4>Aide a l'apprentissage</h4>
          <ul>{support.map((item) => <li key={item}>{item}</li>)}</ul>
        </>
      )}
      <h4>Exercice</h4>
      <p>{content.practice_question?.question || content.practice_question}</p>
      <h4>Reponse attendue</h4>
      <p>{content.expected_answer || content.practice_question?.expected_answer}</p>
      <h4>Correction</h4>
      <p>{content.correction || content.practice_question?.explanation}</p>
      <button className="outline-button" onClick={onShowCurrent} type="button">Revenir au contenu actuel</button>
    </section>
  )
}

function translateOllamaValidationError(error) {
  const normalized = normalizeText(error)
  if (normalized.includes('summary and explanation') || normalized.includes('repeated sentence') || normalized.includes('too repetitive')) {
    return 'répétition entre le résumé et l’explication'
  }
  if (normalized.includes('vocabulary') || normalized.includes('definition') || normalized.includes('literary terms')) {
    return 'définition pédagogique incorrecte'
  }
  if (normalized.includes('grounded') || normalized.includes('source') || normalized.includes('invented proper name')) {
    return 'information potentiellement non fondée sur les sources'
  }
  if (normalized.includes('expected answer') || normalized.includes('correction')) {
    return 'réponse attendue et correction trop similaires'
  }
  if (normalized.includes('contradiction') || normalized.includes('msid') || normalized.includes('chapter 1')) {
    return 'contradiction factuelle détectée'
  }
  if (normalized.includes('english')) {
    return 'présence de formulation anglaise'
  }
  if (normalized.includes('80 words') || normalized.includes('140 words') || normalized.includes('too short')) {
    return 'longueur minimale non respectée'
  }
  return 'critère pédagogique non satisfait'
}

function validateOllamaPreviewForDisplay(preview) {
  const content = preview?.content || {}
  const errors = []
  if (countWords(content.summary) < 80) errors.push('resume trop court')
  if (countWords(content.explanation) < 140) errors.push('explication trop courte')
  if (hasEmptyPreviewField(content)) errors.push('champ vide')
  const serialized = normalizeText(previewTextValues(content).join(' '))
  const englishMarkers = ['pitfall', 'pitfalls', 'method :', 'memory tip', 'key point', 'summary', 'explanation', 'expected answer']
  const foundEnglish = englishMarkers.find((marker) => serialized.includes(marker))
  if (foundEnglish) errors.push(`anglais detecte: ${foundEnglish}`)
  if (serialized.includes('ouverture de la tristesse')) errors.push('expression inventee')
  if (/msid.{0,30}(est|represente|designe|constitue).{0,30}(piece|chambre|salle).{0,45}(maison|dar chouafa)/.test(serialized)) errors.push('definition incorrecte du Msid')
  if (/chapitre 1.{0,60}(fin de l histoire|fin du roman|fin de l oeuvre)/.test(serialized)) errors.push('chapitre 1 presente comme fin')
  errors.push(...validateOllamaVocabulary(content.vocabulary))
  if (isTooSimilar(content.summary, content.explanation, 0.72)) errors.push('resume et explication trop repetitifs')
  if (isTooSimilar(content.expected_answer, content.correction, 0.82)) errors.push('reponse et correction trop repetitives')
  return errors
}

function validateOllamaVocabulary(vocabulary) {
  const entries = Array.isArray(vocabulary) ? vocabulary : []
  const definitions = entries.map((item) => ({
    term: normalizeText(item?.term),
    definition: normalizeText(item?.definition),
  }))
  const hasDefinition = (termPart, definitionParts) => definitions.some(({ term, definition }) => (
    term.includes(termPart) && definitionParts.some((part) => definition.includes(part))
  ))
  const errors = []
  if (!hasDefinition('msid', ['ecole coranique'])) errors.push('definition du Msid manquante ou incorrecte')
  if (!hasDefinition('impasse', ['sans issue', 'rue', 'passage'])) errors.push('definition de impasse manquante ou incorrecte')
  if (!hasDefinition('incipit', ['debut', 'commencement'])) errors.push('definition de incipit manquante')
  if (!hasDefinition('focalisation', ['point de vue', 'percoit', 'personnage'])) errors.push('definition de focalisation interne manquante')
  if (!hasDefinition('imparfait', ['repete', 'repetee', 'habitude'])) errors.push('definition de imparfait iteratif manquante')
  return errors
}

function hasEmptyPreviewField(value) {
  if (typeof value === 'string') return value.trim().length === 0
  if (Array.isArray(value)) return value.length === 0 || value.some(hasEmptyPreviewField)
  if (value && typeof value === 'object') {
    return Object.entries(value).some(([key, item]) => !['blocks', 'source_block_ids', 'expected_elements', 'answer'].includes(key) && hasEmptyPreviewField(item))
  }
  return false
}

function previewTextValues(value) {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(previewTextValues)
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([key]) => !['blocks', 'source_block_ids', 'expected_elements', 'answer'].includes(key))
      .flatMap(([, item]) => previewTextValues(item))
  }
  return []
}

function isTooSimilar(left, right, threshold) {
  const leftText = normalizeText(left)
  const rightText = normalizeText(right)
  if (!leftText || !rightText) return false
  const leftWords = new Set(leftText.split(/\s+/))
  const rightWords = new Set(rightText.split(/\s+/))
  const shared = [...leftWords].filter((word) => rightWords.has(word)).length
  const total = Math.max(leftWords.size, rightWords.size, 1)
  return shared / total > threshold
}

function countWords(value) {
  return String(value || '').trim().split(/\s+/).filter(Boolean).length
}

function secondsFromNanoseconds(value) {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue) || numericValue <= 0) return ''
  return (numericValue / 1000000000).toFixed(1)
}

function classifyChapterBlocks(blocks) {
  const sections = CHAPTER_TABS.reduce((result, tab) => ({ ...result, [tab.id]: [] }), {})
  let currentSection = 'resume'

  blocks.forEach((block) => {
    const sourceId = normalizeBlockType(block.source_block_id || block.id || '')
    const explicitSection = normalizeChapterSection(
      block.section
        || block.metadata?.section
        || block.spec?.section
        || block.data?.section,
    )
    const idSection = inferChapterSectionFromId(sourceId)

    const type = normalizeBlockType(block.type)
    const titleText = normalizeText(block.title)
    const contentText = typeof block.content === 'string' ? normalizeText(block.content) : ''
    const searchText = normalizeText([
      titleText,
      contentText,
      sourceId,
      block.metadata?.exam_type,
      block.spec?.exam_type,
    ])

    const detectedSection = explicitSection
      || idSection
      || inferChapterSectionFromContent(block, type, titleText, searchText)

    if (detectedSection && sections[detectedSection]) {
      currentSection = detectedSection
      sections[detectedSection].push(block)
      return
    }

    if (
      currentSection === 'training_exams'
      && ['heading', 'warning', 'quote', 'exercise', 'paragraph', 'summary', 'methodology', 'key_points'].includes(type)
    ) {
      sections.training_exams.push(block)
      return
    }

    if (
      currentSection === 'regional_exams'
      && ['heading', 'warning', 'quote', 'exercise', 'paragraph', 'summary', 'methodology', 'key_points'].includes(type)
    ) {
      sections.regional_exams.push(block)
      return
    }

    if (currentSection === 'sequences' && !['visual', 'diagram', 'table'].includes(type)) {
      sections.sequences.push(block)
      return
    }

    sections.resume.push(block)
  })

  return sections
}

function inferChapterSectionFromId(sourceId) {
  const id = normalizeBlockType(sourceId)
  if (!id) return ''

  if (/(^|_)correction(_|$)|(^|_)solution(_|$)/.test(id)) return 'corrections'
  if (/(^|_)regional_exam(_|$)|(^|_)regional(_|$)/.test(id)) return 'regional_exams'
  if (/(^|_)training(_|$)|(^|_)exercise(_|$)|(^|_)question(_|$)|(^|_)scale(_|$)/.test(id)) return 'training_exams'
  if (/(^|_)seq(_|$)|(^|_)sequence(_|$)/.test(id)) return 'sequences'
  if (/(^|_)takeaway(_|$)|(^|_)a_retenir(_|$)|(^|_)synthese(_|$)/.test(id)) return 'takeaways'
  if (/(^|_)visual(_|$)|(^|_)diagram(_|$)|(^|_)table(_|$)/.test(id)) return 'schemas'
  if (/(^|_)summary(_|$)|(^|_)resume(_|$)|(^|_)analysis(_|$)|(^|_)method(_|$)|(^|_)reperes(_|$)/.test(id)) return 'resume'

  return ''
}

function inferChapterSectionFromContent(block, type, titleText, searchText) {
  if (
    type === 'correction'
    || type === 'solution'
    || /^correction\b|^corrige\b|^solution\b/.test(titleText)
  ) {
    return 'corrections'
  }

  if (isRegionalExamBlock(block, searchText)) {
    return 'regional_exams'
  }

  if (isTrainingExamStart(block, searchText)) {
    return 'training_exams'
  }

  if (/\bsequence\s*\d*\b|\betape\s*\d*\b|\bpartie\s*\d*\b/.test(titleText)) {
    return 'sequences'
  }

  if (
    (type === 'summary' && /\ba retenir\b|\bsynthese\b|\bbilan\b|\bessentiel\b/.test(searchText))
    || type === 'key_point'
    || /\ba retenir\b|\bsynthese\b|\bbilan\b|\bessentiel\b/.test(titleText)
  ) {
    return 'takeaways'
  }

  if (
    type === 'visual'
    || type === 'diagram'
    || type === 'table'
    || /\bschema\b|\bcarte\b|\bchronologie\b|\breperes?\b|\bdiagramme\b/.test(titleText)
  ) {
    return 'schemas'
  }

  if (/\bbareme\b|\btotal\s*:?\s*\d+\s*points?\b/.test(searchText)) {
    return 'training_exams'
  }

  return ''
}

function normalizeChapterSection(value) {
  const normalized = normalizeBlockType(value)
  const aliases = {
    resume: 'resume',
    summary: 'resume',
    analysis: 'resume',
    analyse: 'resume',
    sequences: 'sequences',
    sequence: 'sequences',
    schemas: 'schemas',
    schema: 'schemas',
    visuals: 'schemas',
    visual: 'schemas',
    training: 'training_exams',
    training_exams: 'training_exams',
    training_exam: 'training_exams',
    entrainement: 'training_exams',
    examen_entrainement: 'training_exams',
    examens_entrainement: 'training_exams',
    regional_exams: 'regional_exams',
    regional_exam: 'regional_exams',
    examens_regionaux: 'regional_exams',
    examen_regional: 'regional_exams',
    corrections: 'corrections',
    correction: 'corrections',
    solutions: 'corrections',
    solution: 'corrections',
    takeaways: 'takeaways',
    takeaway: 'takeaways',
    a_retenir: 'takeaways',
    synthese: 'takeaways',
    bilan: 'takeaways',
  }
  return aliases[normalized] || ''
}

function isTrainingExamStart(block, searchText = '') {
  const type = normalizeBlockType(block.type)
  const sourceId = normalizeBlockType(block.source_block_id || block.id || '')
  const metadata = block.metadata && typeof block.metadata === 'object' ? block.metadata : {}
  const spec = block.spec && typeof block.spec === 'object' ? block.spec : {}
  const explicitType = normalizeBlockType(metadata.exam_type || spec.exam_type || block.exam_type)

  if (/(^|_)training(_|$)|(^|_)exercise(_|$)|(^|_)training_scale(_|$)/.test(sourceId)) {
    return true
  }

  if (['training', 'training_exam', 'examen_entrainement', 'entrainement'].includes(explicitType)) {
    return true
  }

  return (
    (type === 'heading' || type === 'warning')
    && /\bexamen d entrainement\b|\bsujet d entrainement\b|\bentrainement cree\b/.test(searchText)
  )
}

function isRegionalExamBlock(block, searchText = '') {
  const sourceId = normalizeBlockType(block.source_block_id || block.id || '')
  const metadata = block.metadata && typeof block.metadata === 'object' ? block.metadata : {}
  const spec = block.spec && typeof block.spec === 'object' ? block.spec : {}
  const explicitType = normalizeBlockType(metadata.exam_type || spec.exam_type || block.exam_type)
  const isTraining = /\bentrainement\b|\bexercice d application\b|\bnon officiel\b|\bn est pas presente comme un examen regional\b/.test(searchText)

  if (/(^|_)regional_exam(_|$)|(^|_)regional(_|$)/.test(sourceId)) return true
  if (isTraining) return false
  if (['regional', 'regional_exam', 'examen_regional'].includes(explicitType)) return true
  if (metadata.official_verified === true || spec.official_verified === true) return true

  return (
    /\bexamen regional\b|\bacademie regionale\b|\bsession normale\b|\bsession de rattrapage\b/.test(searchText)
    || (
      /\bstatut documentaire\b|\bofficial_verified\b|\bsujet regional republie\b/.test(searchText)
      && /\bproduction ecrite\b|\bpassage\b|\baxe\b/.test(searchText)
    )
  )
}

function numberChapterCorrections(blocks) {
  return blocks.map((block, index) => ({
    ...block,
    title: `Correction ${index + 1}`,
  }))
}

function ChapterRegionalExams({ blocks, chapterId, level }) {
  const examGroups = groupRegionalExamBlocks(blocks)

  if (examGroups.length === 0) {
    return <p className="admin-empty">Aucun examen régional vérifié n’est disponible pour ce chapitre.</p>
  }

  return (
    <div className="regional-exams-list">
      {examGroups.map((exam, index) => (
        <RegionalExamCard
          exam={exam}
          key={exam.key}
          chapterId={`${chapterId}-regional-${index + 1}`}
          level={level}
        />
      ))}
    </div>
  )
}

function groupRegionalExamBlocks(blocks) {
  const groups = new Map()

  blocks.forEach((block, index) => {
    const metadata = getRegionalExamMetadata(block)
    const key = metadata.examId
      || [metadata.academy, metadata.region, metadata.year, metadata.session].filter(Boolean).join('|')
      || `regional-exam-${index + 1}`

    if (!groups.has(key)) {
      groups.set(key, { key, metadata, blocks: [] })
    }

    groups.get(key).blocks.push(cleanRegionalExamDisplayBlock(block))
  })

  return Array.from(groups.values())
}

function cleanRegionalExamDisplayBlock(block) {
  if (typeof block?.content !== 'string') return block

  const cleanedLines = block.content
    .split(/\r?\n/)
    .filter((line) => {
      const normalized = normalizeText(line)
      return !(
        /^examen regional\b/.test(normalized)
        || /^academie\s*\/?\s*region\s*:/.test(normalized)
        || /^annee\s*:/.test(normalized)
        || /^session\s*:/.test(normalized)
      )
    })

  const cleanedContent = cleanedLines.join('\n').trim()
  return cleanedContent ? { ...block, content: cleanedContent } : block
}

function getRegionalExamMetadata(block) {
  const metadata = block.metadata && typeof block.metadata === 'object' ? block.metadata : {}
  const spec = block.spec && typeof block.spec === 'object' ? block.spec : {}
  const value = (key, fallback = '') => metadata[key] ?? spec[key] ?? block[key] ?? fallback
  const rawContent = normalizeDisplayText(block.content)
  const rawTitle = normalizeDisplayText(block.title)
  const searchable = `${rawTitle}\n${rawContent}`

  const extract = (pattern, fallback = '') => {
    const match = searchable.match(pattern)
    return match?.[1]?.trim() || fallback
  }

  const titleMatch = searchable.match(/examen\s+r[ée]gional\s*[—-]\s*([^\n—-]+?)\s*[—-]\s*(\d{4})/i)
  const academyFromText = extract(/acad[ée]mie\s*\/?\s*r[ée]gion\s*:\s*([^\n]+)/i)
  const yearFromText = extract(/ann[ée]e\s*:\s*(\d{4})/i)
  const sessionFromText = extract(/session\s*:\s*([^\n]+)/i)
  const examStatusFromText = extract(/statut\s+(?:du\s+sujet|documentaire)\s*:\s*([^\n]+)/i)
  const correctionStatusFromText = extract(/statut\s+du\s+corrig[ée]\s*:\s*([^\n]+)/i)

  const explicitOfficial = value('official_verified')
  const officialFromText = /official_verified\s*=\s*true/i.test(searchable)
  const explicitlyNotOfficial = /official_verified\s*=\s*false/i.test(searchable)

  const correctionStatus = normalizeDisplayText(value('correction_status'))
    || correctionStatusFromText
    || (explicitlyNotOfficial ? 'indicative' : '')

  return {
    examId: value('exam_id'),
    academy: normalizeDisplayText(value('academy'))
      || academyFromText
      || titleMatch?.[1]?.trim()
      || '',
    region: normalizeDisplayText(value('region'))
      || titleMatch?.[1]?.trim()
      || '',
    year: normalizeDisplayText(value('year'))
      || yearFromText
      || titleMatch?.[2]
      || '',
    session: normalizeDisplayText(value('session'))
      || sessionFromText
      || '',
    examStatus: normalizeDisplayText(value('exam_status'))
      || examStatusFromText
      || '',
    correctionStatus,
    officialVerified: explicitOfficial === true || officialFromText,
    textScore: normalizeDisplayText(value('text_score', '/10')),
    writingScore: normalizeDisplayText(value('writing_score', '/10')),
    totalScore: normalizeDisplayText(value('total_score', '/20')),
    subject_pdf_url: normalizeDisplayText(value('subject_pdf_url')),
    correction_pdf_url: normalizeDisplayText(value('correction_pdf_url')),
    combined_pdf_url: normalizeDisplayText(value('combined_pdf_url')),
    latex_pdf_url: normalizeDisplayText(value('latex_pdf_url')),
  }
}

function RegionalExamCard({ exam, chapterId, level }) {
  const { metadata } = exam
  const titleParts = [
    'Examen régional',
    metadata.academy || metadata.region,
    metadata.year,
  ].filter(Boolean)
  const subjectStatus = metadata.officialVerified
    ? 'Sujet officiel vérifié'
    : metadata.examStatus || 'Sujet régional identifié — vérification documentaire recommandée'
  const correctionStatus = normalizeText(metadata.correctionStatus).includes('indicative')
    ? 'Correction pédagogique indicative'
    : metadata.correctionStatus || 'Statut du corrigé non précisé'

  return (
    <article className="regional-exam-card">
      <header>
        <div>
          <span className={metadata.officialVerified ? 'exam-status-badge verified' : 'exam-status-badge'}>{subjectStatus}</span>
          <h3>{titleParts.join(' — ')}</h3>
          {metadata.session && <p>{metadata.session}</p>}
        </div>
        <strong>{metadata.totalScore}</strong>
      </header>

      <div className="exam-metadata-grid">
        <p><span>Académie / région</span><strong>{metadata.academy || metadata.region || 'Non précisée'}</strong></p>
        <p><span>Année</span><strong>{metadata.year || 'Non précisée'}</strong></p>
        <p><span>Étude de texte</span><strong>{metadata.textScore}</strong></p>
        <p><span>Production écrite</span><strong>{metadata.writingScore}</strong></p>
      </div>

      <p className="exam-correction-status">{correctionStatus}</p>
      <RegionalExamPdfActions metadata={metadata} />
      <StructuredLessonBlocks blocks={exam.blocks} chapterId={chapterId} level={level} />
    </article>
  )
}


function RegionalExamPdfActions({ metadata }) {
  const subjectUrl = resolveDocumentUrl(metadata.subjectPdfUrl || metadata.subject_pdf_url)
  const correctionUrl = resolveDocumentUrl(metadata.correctionPdfUrl || metadata.correction_pdf_url)
  const combinedUrl = resolveDocumentUrl(
    metadata.combinedPdfUrl
      || metadata.combined_pdf_url
      || metadata.latexPdfUrl
      || metadata.latex_pdf_url,
  )

  const actions = [
    subjectUrl ? { label: 'Ouvrir le sujet PDF', url: subjectUrl } : null,
    correctionUrl ? { label: 'Voir la correction PDF', url: correctionUrl } : null,
    combinedUrl ? { label: 'Ouvrir le PDF généré', url: combinedUrl } : null,
  ].filter(Boolean)

  if (actions.length === 0) return null

  const uniqueActions = actions.filter(
    (action, index, list) => list.findIndex((item) => item.url === action.url) === index,
  )

  return (
    <div className="regional-exam-pdf-actions">
      {uniqueActions.map((action) => (
        <a className="outline-button" href={action.url} key={action.url} rel="noreferrer" target="_blank">
          <ExternalLink size={17} />
          {action.label}
        </a>
      ))}
    </div>
  )
}

function resolveDocumentUrl(value) {
  const cleanValue = String(value || '').trim()
  if (!cleanValue) return ''
  if (/^(https?:|blob:|data:)/i.test(cleanValue)) return cleanValue
  return `${API_BASE_URL}${cleanValue.startsWith('/') ? cleanValue : `/${cleanValue}`}`
}


function normalizeRawChapterBlocks(rawBlocks, chapter) {
  if (!Array.isArray(rawBlocks)) return []

  const output = []
  let objectiveItems = []
  let insideObjectives = false

  const flushObjectives = () => {
    const items = objectiveItems.map(cleanLatexDisplayText).filter(Boolean)
    if (items.length > 0) {
      output.push({
        id: `${chapter?.id || 'chapter'}-latex-objectives`,
        type: 'bullet_list',
        title: 'Objectifs',
        content: items,
        generation_method: 'source_latex',
      })
    }
    objectiveItems = []
    insideObjectives = false
  }

  rawBlocks.forEach((block) => {
    const rawContent = typeof block?.content === 'string' ? block.content.trim() : ''

    if (/^\\begin\{(?:objectifbox|objectifsbox)\}$/i.test(rawContent)) {
      if (insideObjectives) flushObjectives()
      insideObjectives = true
      return
    }

    if (/^\\end\{(?:objectifbox|objectifsbox)\}$/i.test(rawContent)) {
      flushObjectives()
      return
    }

    if (insideObjectives) {
      const cleaned = cleanLatexDisplayText(rawContent)
      if (cleaned) objectiveItems.push(cleaned)
      return
    }

    const normalized = normalizeLessonBlock(block)
    if (normalized) output.push(normalized)
  })

  if (insideObjectives) flushObjectives()
  return output
}

function prepareChapterDisplayBlocks(blocks, chapter) {
  const chapterTitle = normalizeComparableText(chapter?.title)
  const chapterNumber = extractChapterNumber(chapterTitle)
  const nonLatexBlocks = blocks.filter((block) => block.generation_method !== 'source_latex')
  const nonLatexTexts = nonLatexBlocks
    .map((block) => normalizeComparableText(block.content || block.title))
    .filter(Boolean)
  const output = []

  blocks.forEach((block) => {
    const blockText = normalizeComparableText(block.content || block.title)
    const blockTitle = normalizeComparableText(block.title)
    const blockChapterNumber = extractChapterNumber(blockText)
    const isHeadingLike = block.type === 'heading' || block.type === 'paragraph'

    if (
      chapterTitle
      && isHeadingLike
      && (
        blockText === chapterTitle
        || (chapterNumber && blockChapterNumber === chapterNumber && /^chapitre\s+\d+\b/.test(blockText))
      )
    ) {
      return
    }

    // Imported LaTeX objectives duplicate the course objectives already displayed
    // in the main Objectifs tab. Keep unique LaTeX pedagogical content only.
    if (
      block.generation_method === 'source_latex'
      && (blockTitle === 'objectifs' || blockText === 'objectifs')
      && nonLatexBlocks.length > 0
    ) {
      return
    }

    if (
      block.generation_method === 'source_latex'
      && blockText
      && nonLatexTexts.some((candidate) => candidate === blockText || candidate.includes(blockText) || blockText.includes(candidate))
    ) {
      return
    }

    output.push(block)
  })

  return deduplicateLessonBlocks(output)
}

function extractChapterNumber(value) {
  const match = String(value || '').match(/^chapitre\s+(\d+)\b/)
  return match ? match[1] : ''
}

function normalizeComparableText(value) {
  return normalizeText(value).replace(/[^a-z0-9]+/g, ' ').trim()
}

export function StructuredLessonBlocks({ blocks, chapterId = 'chapter', level = 'intermediaire' }) {
  const safeBlocks = Array.isArray(blocks) ? blocks.map(normalizeLessonBlock).filter(Boolean) : []
  const sources = collectChapterSources(safeBlocks)
  return (
    <div className="structured-lesson">
      {safeBlocks.map((block, index) => <LessonBlock block={block} key={lessonBlockKey(block, index, chapterId, level)} />)}
      {sources.length > 0 && (
        <details className="lesson-sources-panel">
          <summary>Sources du chapitre</summary>
          {sources.map((source) => (
            <p key={`${source.document}-${source.pageStart}-${source.pageEnd}`}>
              Document : {source.document} · Pages : {source.pageStart}{source.pageEnd && source.pageEnd !== source.pageStart ? `-${source.pageEnd}` : ''}
            </p>
          ))}
        </details>
      )}
    </div>
  )
}

function selectChapterBlocks(chapter, learnerLevel) {
  const structuredContent = chapter?.structured_content
  const directVariants = chapter?.variants

  // Priority is intentionally exclusive: return one source only, never merge lesson streams.
  if (directVariants && typeof directVariants === 'object') {
    const directBlocks = selectVariantBlocks(directVariants, learnerLevel, chapter?.default_level)
    if (directBlocks.length > 0) {
      return directBlocks
    }
  }

  if (Array.isArray(structuredContent)) {
    return structuredContent
  }

  if (!structuredContent || typeof structuredContent !== 'object') {
    return []
  }

  const variants = structuredContent.variants
  if (!variants || typeof variants !== 'object') {
    if (Array.isArray(structuredContent.blocks)) {
      return structuredContent.blocks
    }
    if (Array.isArray(structuredContent.source_blocks)) {
      return structuredContent.source_blocks
    }
    return []
  }

  const variantBlocks = selectVariantBlocks(variants, learnerLevel, structuredContent.default_level)
  if (variantBlocks.length > 0) {
    return variantBlocks
  }

  if (Array.isArray(structuredContent.blocks)) {
    return structuredContent.blocks
  }

  if (Array.isArray(structuredContent.source_blocks)) {
    return structuredContent.source_blocks
  }

  return []
}

function selectVariantBlocks(variants, learnerLevel, defaultLevel) {
  const normalizedLevel = normalizeLevel(learnerLevel || defaultLevel || 'intermediaire')
  const preferredBlocks = variants[normalizedLevel]
  if (Array.isArray(preferredBlocks)) {
    return preferredBlocks
  }

  const normalizedDefaultLevel = normalizeLevel(defaultLevel || 'intermediaire')
  const defaultBlocks = variants[normalizedDefaultLevel] || variants.intermediaire || variants.debutant || variants.avance
  return Array.isArray(defaultBlocks) ? defaultBlocks : []
}

function sanitizeRenderableBlocks(blocks, chapter, normalizedLevel) {
  if (!Array.isArray(blocks) || blocks.length === 0) {
    return []
  }

  if (!isAiGeneratedVariant(blocks)) {
    return blocks.filter((block) => hasRenderableContent(block, chapter))
  }

  const output = []
  output.push(...firstRenderableBlocks(blocks, 'heading', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'paragraph', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'definition', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'example', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'methodology', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'warning', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'key_points', 1, chapter))
  output.push(...numberRenderableBlocks(blocks, 'exercise', 3, chapter, 'Exercice'))
  output.push(...numberRenderableBlocks(blocks, 'correction', Number.POSITIVE_INFINITY, chapter, 'Correction'))
  output.push(...firstRenderableBlocks(blocks, 'summary', 1, chapter))
  output.push(...firstRenderableBlocks(blocks, 'mini_assessment', 1, chapter, normalizedLevel))
  return output
}

function isAiGeneratedVariant(blocks) {
  return blocks.some((block) => String(block.generation_method || '').startsWith('ai_generated'))
}

function hasGeneratedAiVariant(selectedVariant) {
  if (!selectedVariant) return false
  const method = selectedVariant.generation_method
  if (method === 'ai_generated') return true
  if (method !== 'mixed') return false
  return (selectedVariant.chapters || []).some((chapter) => {
    if (chapter?.generation_method === 'ai_generated') return true
    return (chapter?.blocks || []).some((block) => block?.generation_method === 'ai_generated')
  })
}

function firstRenderableBlocks(blocks, blockType, count, chapter, normalizedLevel) {
  const matches = blocks.filter((block) => {
    if (block.type !== blockType || !hasRenderableContent(block, chapter)) return false
    if (blockType === 'mini_assessment') return miniAssessmentMatchesChapter(block, chapter, normalizedLevel)
    return true
  })
  return matches.slice(0, count)
}

function numberRenderableBlocks(blocks, blockType, count, chapter, label) {
  return blocks
    .filter((block) => block.type === blockType && hasRenderableContent(block, chapter))
    .slice(0, count)
    .map((block, index) => ({ ...block, title: `${label} ${index + 1}` }))
}

function hasRenderableContent(block, chapter) {
  if (!block) return false
  if (block.type === 'heading') return Boolean(normalizeDisplayText(block.content || block.title || chapter?.title))
  if (block.type === 'mini_assessment') {
    const content = block.content
    return Boolean(content && typeof content === 'object' && content.answer && content.explanation)
  }
  const content = normalizeDisplayText(block.content)
  if (!content) return false
  if (block.type === 'correction' && /^correction(?:\s+de\s+l[’']exercice)?\s*\d*\s*:?\s*$/i.test(content.trim())) {
    return false
  }
  return true
}

function miniAssessmentMatchesChapter(block, chapter, normalizedLevel) {
  const content = block.content
  if (!content || typeof content !== 'object') return false
  const text = normalizeText(`${content.question || ''} ${content.answer || ''} ${content.explanation || ''} ${normalizedLevel || ''}`)
  const chapterTitle = normalizeText(chapter?.title)
  if (chapterTitle && text.includes(chapterTitle)) return true
  const forbidden = ['methodologie de lexamen regional', 'la boite a merveilles', 'le dernier jour dun condamne', 'le dernier jour d un condamne']
  return !forbidden.some((item) => item !== chapterTitle && text.includes(item))
}

function lessonBlockKey(block, index, chapterId, level) {
  const stablePart = block.id ?? block.position ?? index
  return `${chapterId}-${level}-${stablePart}-${block.type}`
}

function LessonBlock({ block }) {
  const title = cleanLatexDisplayText(block.title)
  const content = block.content

  if (block.type === 'heading') return <h3 className="lesson-block-heading">{title || cleanLatexDisplayText(content)}</h3>
  if (block.type === 'paragraph') return <section className="rich-section"><BlockTitle title={title} /><p>{cleanLatexDisplayText(content)}</p></section>
  if (block.type === 'bullet_list' || block.type === 'numbered_list' || block.type === 'key_points') {
    const ListTag = block.type === 'numbered_list' ? 'ol' : 'ul'
    return <section className="rich-section"><BlockTitle title={title} /><ListTag>{asList(content).map((item, index) => <li key={`${normalizeText(item)}-${index}`}>{cleanLatexDisplayText(item)}</li>)}</ListTag></section>
  }
  if (['definition', 'key_point', 'warning', 'tip', 'example', 'methodology', 'exercise', 'summary', 'quote', 'formula'].includes(block.type)) {
    return <section className={`lesson-block lesson-block-${block.type}`}><BlockTitle title={title} /><p>{cleanLatexDisplayText(content)}</p></section>
  }
  if (block.type === 'solution' || block.type === 'correction') {
    return <details className="lesson-block lesson-block-solution"><summary>{title || 'Correction'}</summary><p>{cleanLatexDisplayText(content)}</p></details>
  }
  if (block.type === 'code') {
    return <section className="lesson-code-block"><BlockTitle title={title} /><pre><code>{content}</code></pre></section>
  }
  if (block.type === 'table') {
    return <section className="rich-section"><BlockTitle title={title} /><LessonTable rows={Array.isArray(content) ? content : []} /></section>
  }
  if (block.type === 'diagram') {
    return <section className="lesson-diagram-block"><BlockTitle title={title} /><MermaidDiagram code={String(content || '')} /></section>
  }
  if (block.type === 'visual') return <VisualLessonBlock block={{ ...block, title }} />
  if (block.type === 'knowledge_check' || block.type === 'mini_assessment') return <KnowledgeCheck block={block} />
  if (block.type === 'image') return <VisualLessonBlock block={{ ...block, title, visual_type: 'image' }} />
  return <section className="rich-section"><BlockTitle title={title} /><p>{typeof content === 'string' ? cleanLatexDisplayText(content) : JSON.stringify(content)}</p></section>
}

function VisualLessonBlock({ block }) {
  const visualSpec = block.spec && typeof block.spec === 'object' && !Array.isArray(block.spec)
    ? block.spec
    : {}
  const contentData = block.content && typeof block.content === 'object' && !Array.isArray(block.content)
    ? block.content
    : {}
  const visualData = { ...visualSpec, ...contentData }
  const title = cleanLatexDisplayText(block.title || visualData.title)
  const visualType = normalizeBlockType(
    block.visual_type
      || block.visualType
      || block.subtype
      || block.kind
      || block.metadata?.visual_type
      || block.metadata?.type
      || block.data?.type
      || visualData.visual_type
      || visualData.type
      || 'visual',
  )
  const mermaidCode = String(
    block.mermaid_code
      || block.mermaidCode
      || block.metadata?.mermaid_code
      || block.data?.mermaid_code
      || visualData.mermaid_code
      || visualData.mermaidCode
      || (visualType === 'mermaid' && typeof block.content === 'string' ? block.content : '')
      || '',
  ).trim()
  const imagePath = String(
    block.file_path
      || block.image_path
      || block.path
      || block.metadata?.file_path
      || block.metadata?.image_path
      || visualData.file_path
      || visualData.image_path
      || visualData.path
      || '',
  ).trim()
  const altText = cleanLatexDisplayText(
    block.alt_text
      || block.alt
      || block.description
      || block.caption
      || block.metadata?.alt_text
      || visualData.alt_text
      || visualData.alt
      || visualData.description
      || visualData.caption
      || '',
  )
  const rendering = cleanLatexDisplayText(
    block.rendering
      || block.metadata?.rendering
      || visualData.rendering
      || '',
  )
  const contentText = typeof block.content === 'string'
    ? cleanLatexDisplayText(block.content)
    : ''
  const usefulContent = normalizeText(contentText) && normalizeText(contentText) !== normalizeText(title)
    ? contentText
    : ''
  const columnsSource = Array.isArray(block.columns)
    ? block.columns
    : Array.isArray(visualData.columns)
      ? visualData.columns
      : []
  const columns = columnsSource.map(cleanLatexDisplayText).filter(Boolean)
  const rows = Array.isArray(block.rows)
    ? block.rows
    : Array.isArray(block.data?.rows)
      ? block.data.rows
      : Array.isArray(visualData.rows)
        ? visualData.rows
        : Array.isArray(visualData.data?.rows)
          ? visualData.data.rows
          : []

  return (
    <figure className={`lesson-visual-block lesson-visual-${visualType}`}>
      <BlockTitle title={title} />

      {mermaidCode && <MermaidDiagram code={mermaidCode} />}

      {!mermaidCode && visualType === 'image' && imagePath && (
        <VisualImage alt={altText || title || 'Illustration pédagogique'} path={imagePath} />
      )}

      {!mermaidCode && rows.length > 0 && <LessonTable rows={rows} />}

      {!mermaidCode && rows.length === 0 && columns.length > 0 && (
        <div className="lesson-visual-columns" role="list">
          {columns.map((column, index) => <span key={`${normalizeText(column)}-${index}`} role="listitem">{column}</span>)}
        </div>
      )}

      {!mermaidCode && visualType !== 'image' && rows.length === 0 && columns.length === 0 && (
        <div className="lesson-visual-placeholder">
          <p>{altText || usefulContent || 'Schéma pédagogique associé à ce chapitre.'}</p>
          {rendering && <small>Format prévu : {rendering.replaceAll('_', ' ')}</small>}
        </div>
      )}

      {usefulContent && mermaidCode && <figcaption>{usefulContent}</figcaption>}
      {!usefulContent && altText && (mermaidCode || visualType === 'image') && <figcaption>{altText}</figcaption>}
    </figure>
  )
}

function VisualImage({ alt, path }) {
  const [failed, setFailed] = useState(false)
  const source = resolveVisualAssetUrl(path)

  if (failed || !source) {
    return (
      <div className="lesson-visual-placeholder">
        <p>{alt || 'Illustration pédagogique non disponible.'}</p>
      </div>
    )
  }

  return <img alt={alt} className="lesson-visual-image" loading="lazy" onError={() => setFailed(true)} src={source} />
}

function resolveVisualAssetUrl(path) {
  const cleanPath = String(path || '').trim()
  if (!cleanPath) return ''
  if (/^(https?:|data:|blob:)/i.test(cleanPath)) return cleanPath
  if (cleanPath.startsWith('/')) return `${API_BASE_URL}${cleanPath}`
  return `${API_BASE_URL}/${cleanPath.replace(/^\.?\//, '')}`
}

function BlockTitle({ title }) {
  return title ? <h4>{title}</h4> : null
}

function LessonTable({ rows }) {
  return (
    <table className="lesson-table">
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={`row-${rowIndex}`}>
            {(Array.isArray(row) ? row : [row]).map((cell, cellIndex) => <td key={`cell-${rowIndex}-${cellIndex}`}>{normalizeDisplayText(cell)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MermaidDiagram({ code }) {
  const [svg, setSvg] = useState('')
  const [error, setError] = useState('')
  const cleanCode = sanitizeMermaidCode(code)

  useEffect(() => {
    let cancelled = false
    if (!cleanCode) {
      setSvg('')
      setError('Schéma indisponible')
      return undefined
    }
    import('mermaid')
      .then(({ default: mermaid }) => {
        mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base' })
        return mermaid.render(`lesson-diagram-${hashText(cleanCode)}`, cleanCode)
      })
      .then(({ svg: renderedSvg }) => {
        if (!cancelled) {
          setSvg(renderedSvg)
          setError('')
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSvg('')
          setError('Schéma Mermaid non valide. Affichage textuel de secours.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [cleanCode])

  if (svg) {
    return <div className="mermaid-rendered" dangerouslySetInnerHTML={{ __html: svg }} />
  }

  if (!cleanCode) {
    return (
      <div className="mermaid-fallback invalid">
        <p>{error || 'Schéma indisponible'}</p>
      </div>
    )
  }

  return (
    <div className="mermaid-fallback invalid">
      <pre>{cleanCode}</pre>
      {error && <p>{error}</p>}
    </div>
  )
}

function KnowledgeCheck({ block }) {
  const data = typeof block.content === 'object' && block.content ? block.content : {}
  const options = Array.isArray(data.options) ? data.options : []
  return (
    <section className="lesson-block lesson-block-knowledge_check">
      <h4>{block.title || data.question || 'Mini-vérification'}</h4>
      {data.question && <p>{data.question}</p>}
      {options.map((option) => <button key={option} type="button">{option}</button>)}
    </section>
  )
}

function collectChapterSources(blocks) {
  const sources = []
  const seen = new Set()
  blocks.forEach((block) => {
    if (!block.generated_from_pdf || !block.source_document_id || !block.source_page_start) return
    const document = publicDocumentName(block.source_document_id)
    const pageStart = block.source_page_start
    const pageEnd = block.source_page_end || pageStart
    const key = `${document}:${pageStart}:${pageEnd}`
    if (seen.has(key)) return
    seen.add(key)
    sources.push({ document, pageStart, pageEnd })
  })
  return sources
}

function publicDocumentName(name) {
  return String(name || '').replace(/^professor_\d+_course_\d+_[0-9a-f]{32}_/i, '')
}

function sanitizeMermaidCode(code) {
  let text = String(code || '')
    .trim()
    .replace(/\u00a0/g, ' ')
    .replace(/[’‘]/g, "'")
    .replace(/[“”]/g, '"')

  const firstLine = text.split(/\r?\n/)[0] || ''
  if (!/^(flowchart|graph|mindmap|timeline|sequenceDiagram|classDiagram|stateDiagram|erDiagram)\b/.test(firstLine)) {
    return ''
  }

  if (/[<>{}]?script|javascript:|click\s+\w+/i.test(text)) {
    return ''
  }

  // Mermaid is more reliable when free-text node labels are quoted.
  // Example: N1[Boîte à Merveilles] -> N1["Boîte à Merveilles"]
  text = text.replace(
    /\b([A-Za-z_][A-Za-z0-9_]*)\[([^\]\r\n"]+)\]/g,
    (_, nodeId, label) => `${nodeId}["${String(label).replace(/"/g, "'").trim()}"]`,
  )

  return text
}

function hashText(value) {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash) + value.charCodeAt(index)
    hash |= 0
  }
  return Math.abs(hash)
}

function InfoLine({ label, value, highlight }) {
  return <p><span>{label}</span><strong className={highlight ? 'red-text' : ''}>{value}</strong></p>
}

function buildCourseContent(course) {
  const chapters = Array.isArray(course?.chapters) ? course.chapters : []
  const examples = Array.isArray(course?.examples)
    ? course.examples.map((item, index) => enrichExample(item, index))
    : []
  const information = course?.information || {}
  const progress = Number(course?.progress || 0)

  return {
    chapters,
    completedChapters: chapters.filter((chapter) => chapter.completed === true).length,
    progress,
    summary: course?.summary || '',
    description: course?.description || '',
    objectives: Array.isArray(course?.objectives) ? course.objectives : [],
    examples,
    skills: Array.isArray(course?.skills) ? course.skills : [],
    summarySections: buildSummarySections(course),
    completedObjectiveCount: Math.ceil(((course?.objectives?.length || 0) * progress) / 100),
    unlockedSkillCount: Math.ceil(((course?.skills?.length || 0) * progress) / 100),
    information: {
      duration: information.duration || course?.duration || '-',
      chapters_count: information.chapter_count ?? information.chapters_count ?? chapters.length,
      language: information.language || course?.language || '-',
      last_update: formatCourseDate(course?.updated_at || course?.content_imported_at || information.last_update || course?.last_update),
    },
  }
}

function loadChapterProgressMap() {
  try {
    const storedProgress = localStorage.getItem(CHAPTER_PROGRESS_STORAGE_KEY)
    return storedProgress ? JSON.parse(storedProgress) : {}
  } catch {
    return {}
  }
}

function saveChapterProgressMap(progressMap) {
  localStorage.setItem(CHAPTER_PROGRESS_STORAGE_KEY, JSON.stringify(progressMap))
}

function persistChapterProgress(courseId, progressRecord, progressMap) {
  saveChapterProgressMap(progressMap)
  updateCourseProgress(courseId, {
    progress: progressRecord.progress,
    chapters: progressRecord.chapters,
  }).catch(() => {})
}

function loadChapterExerciseDrafts(courseId, chapterId) {
  if (!courseId || !chapterId) return {}
  try {
    const storedDrafts = localStorage.getItem(CHAPTER_EXERCISE_DRAFTS_STORAGE_KEY)
    const drafts = storedDrafts ? JSON.parse(storedDrafts) : {}
    return drafts[chapterExerciseDraftKey(courseId, chapterId)] || {}
  } catch {
    return {}
  }
}

function persistChapterExerciseDrafts(courseId, chapterId, answers) {
  if (!courseId || !chapterId) return
  try {
    const storedDrafts = localStorage.getItem(CHAPTER_EXERCISE_DRAFTS_STORAGE_KEY)
    const drafts = storedDrafts ? JSON.parse(storedDrafts) : {}
    drafts[chapterExerciseDraftKey(courseId, chapterId)] = answers
    localStorage.setItem(CHAPTER_EXERCISE_DRAFTS_STORAGE_KEY, JSON.stringify(drafts))
  } catch {
    // Local draft persistence is optional; backend submission remains authoritative.
  }
}

function chapterExerciseDraftKey(courseId, chapterId) {
  return `${courseId}:${chapterId}`
}

function applyLocalChapterProgress(course, savedProgress) {
  if (!course || !Array.isArray(course.chapters) || !Array.isArray(savedProgress?.chapters)) {
    return course
  }

  const chapters = course.chapters.map((chapter, index) => {
    const savedChapter = savedProgress.chapters[index]

    if (!savedChapter || savedChapter.title !== chapter.title) {
      return chapter
    }

    return {
      ...chapter,
      completed: savedChapter.completed === true,
      status: savedChapter.status || chapter.status,
      openable: savedChapter.openable === true,
    }
  })
  const savedProgressValue = Number(savedProgress.progress)

  return {
    ...course,
    progress: Number.isFinite(savedProgressValue) ? savedProgressValue : course.progress,
    chapters,
  }
}

function applySelectedVariant(course, normalizedLevel) {
  if (!course || !course.selected_variant || !Array.isArray(course.selected_variant.chapters)) {
    return course
  }

  const selectedLevel = normalizeLevel(course.selected_variant.level || normalizedLevel)
  const variantByChapter = new Map(
    course.selected_variant.chapters
      .filter((chapterVariant) => isGeneratedChapterVariant(chapterVariant))
      .map((chapterVariant) => [
        normalizeComparableText(chapterVariant.chapter_source_id || chapterVariant.source_chapter_id || ''),
        chapterVariant,
      ])
      .filter(([sourceId]) => sourceId),
  )
  const originalChapters = Array.isArray(course.original_chapters) ? course.original_chapters : course.chapters
  let appliedCount = 0
  const chapters = (Array.isArray(course.chapters) ? course.chapters : []).map((chapter, index) => {
    const originalChapter = originalChapters[index] || chapter
    const variant = variantByChapter.get(normalizeComparableText(getChapterSourceIdentifier(originalChapter)))

    if (!variant) {
      return {
        ...chapter,
        ai_variant_status: 'fallback',
        ai_variant_label: 'Contenu original du professeur — variante IA indisponible',
      }
    }

    const adaptedBlocks = adaptiveVariantToLessonBlocks(variant, originalChapter)
    appliedCount += 1
    return {
      ...chapter,
      ai_variant: variant,
      ai_variant_status: 'ai_generated',
      ai_variant_label: `Adapté par IA — Niveau ${getDisplayLevel(selectedLevel)}`,
      default_level: selectedLevel,
      variants: {
        [selectedLevel]: adaptedBlocks,
      },
      content: variant.explanation || chapter.content,
    }
  })

  return {
    ...course,
    chapters,
    aiVariantApplied: appliedCount > 0,
    aiVariantAppliedCount: appliedCount,
  }
}

function isGeneratedChapterVariant(chapterVariant) {
  if (!chapterVariant || typeof chapterVariant !== 'object') return false
  if (chapterVariant.generation_method === 'ai_generated') return true
  return Array.isArray(chapterVariant.blocks)
    && chapterVariant.blocks.some((block) => block?.generation_method === 'ai_generated')
}

function adaptiveVariantToLessonBlocks(variant, chapter) {
  if (Array.isArray(variant.blocks) && variant.blocks.length > 0) {
    return variant.blocks.map((block, index) => ({
      ...block,
      id: block.id || `${chapter?.id || variant.chapter_source_id}-variant-${index + 1}`,
      level: block.level || variant.level,
      source_chapter_id: block.source_chapter_id || variant.chapter_source_id || chapter?.id,
      generation_method: block.generation_method || variant.generation_method || 'deterministic_fallback',
      section: block.section || inferSectionFromVariantBlock(block),
      original_block_type: block.original_block_type || block.type || 'paragraph',
    }))
  }

  const method = variant.generation_method || 'deterministic_fallback'
  const base = {
    source_chapter_id: variant.chapter_source_id || chapter?.id,
    source_hash: variant.source_hash || variant.traceability?.source_hash || '',
    original_block_type: 'adaptive_variant',
    level: variant.level || 'intermediaire',
    generation_method: method,
  }
  const blocks = [
    { ...base, id: `${chapter?.id || variant.chapter_source_id}-ai-heading`, type: 'heading', title: variant.title || chapter?.title, content: variant.title || chapter?.title, section: 'resume' },
    { ...base, id: `${chapter?.id || variant.chapter_source_id}-ai-summary`, type: 'summary', title: 'Résumé adapté', content: variant.summary, section: 'resume' },
    { ...base, id: `${chapter?.id || variant.chapter_source_id}-ai-explanation`, type: 'paragraph', title: 'Explication détaillée', content: variant.explanation, section: 'resume' },
  ]

  if (Array.isArray(variant.vocabulary)) {
    variant.vocabulary.forEach((item, index) => {
      blocks.push({
        ...base,
        id: `${chapter?.id || variant.chapter_source_id}-ai-vocabulary-${index + 1}`,
        type: 'definition',
        title: item.term || 'Vocabulaire',
        content: item.definition || '',
        section: 'resume',
      })
    })
  }

  if (variant.guided_example) {
    blocks.push({
      ...base,
      id: `${chapter?.id || variant.chapter_source_id}-ai-example`,
      type: 'example',
      title: variant.guided_example.title || 'Exemple guidé',
      content: variant.guided_example.content || '',
      section: 'sequences',
    })
  }

  if (Array.isArray(variant.learning_support) && variant.learning_support.length > 0) {
    blocks.push({
      ...base,
      id: `${chapter?.id || variant.chapter_source_id}-ai-support`,
      type: 'methodology',
      title: "Aide à l'apprentissage",
      content: variant.learning_support.join('\n'),
      section: 'sequences',
    })
  }

  if (variant.practice_question) {
    const practiceInstruction = [
      variant.practice_question.instruction,
      variant.practice_question.difficulty ? `Difficulté : ${variant.practice_question.difficulty}` : '',
      ...(Array.isArray(variant.practice_question.expected_elements)
        ? variant.practice_question.expected_elements.map((item) => `Élément attendu : ${item}`)
        : []),
    ].filter(Boolean)
    blocks.push({
      ...base,
      id: `${chapter?.id || variant.chapter_source_id}-ai-practice`,
      type: 'exercise',
      title: "Question d'entraînement",
      content: [variant.practice_question.question || '', ...practiceInstruction].filter(Boolean).join('\n'),
      section: 'training_exams',
    })
    blocks.push({
      ...base,
      id: `${chapter?.id || variant.chapter_source_id}-ai-practice-correction`,
      type: 'correction',
      title: 'Correction',
      content: `${variant.practice_question.expected_answer || (variant.practice_question.expected_elements || []).join('\n') || ''}\n\n${variant.practice_question.explanation || ''}`.trim(),
      section: 'corrections',
    })
  }

  if (Array.isArray(variant.key_points) && variant.key_points.length > 0) {
    blocks.push({
      ...base,
      id: `${chapter?.id || variant.chapter_source_id}-ai-key-points`,
      type: 'key_points',
      title: 'Points clés',
      content: variant.key_points,
      section: 'takeaways',
    })
  }

  return blocks.filter((block) => block.content || block.title)
}

function getChapterSourceIdentifier(chapter) {
  const structuredContent = Array.isArray(chapter?.structured_content) ? chapter.structured_content : []
  const firstSourceBlock = structuredContent.find((block) => block?.source_chapter_id || block?.chapter_source_id)
  return chapter?.source_chapter_id
    || chapter?.chapter_source_id
    || firstSourceBlock?.source_chapter_id
    || firstSourceBlock?.chapter_source_id
    || chapter?.id
    || chapter?.title
}

function inferSectionFromVariantBlock(block) {
  const type = normalizeBlockType(block?.type)
  if (['visual', 'diagram', 'table', 'image'].includes(type)) return 'schemas'
  if (['exercise', 'mini_assessment', 'knowledge_check'].includes(type)) return 'training_exams'
  if (['correction', 'solution'].includes(type)) return 'corrections'
  if (['key_points', 'summary'].includes(type)) return 'takeaways'
  return 'resume'
}

function advanceChapters(chapters, currentIndex) {
  return chapters.map((chapter, index) => {
    if (index <= currentIndex) {
      return {
        ...chapter,
        completed: true,
        status: 'completed',
        openable: true,
      }
    }

    if (index === currentIndex + 1) {
      return {
        ...chapter,
        completed: false,
        status: 'active',
        openable: true,
      }
    }

    return {
      ...chapter,
      completed: false,
      status: 'locked',
      openable: false,
    }
  })
}

function calculateChapterProgress(completedChapterCount, chapterCount) {
  if (!chapterCount) {
    return 0
  }

  return Math.min(100, Math.round((completedChapterCount / chapterCount) * 100))
}

function buildChapterProgressRecord(chapters, progress) {
  return {
    progress,
    updated_at: new Date().toISOString(),
    chapters: chapters.map((chapter) => ({
      title: chapter.title,
      completed: chapter.completed === true,
      status: chapter.status,
      openable: chapter.openable === true,
    })),
  }
}

function getInitialSelectedChapter(chapters) {
  return (
    chapters.find((chapter) => chapter.openable === true && chapter.completed !== true)
    || chapters.find((chapter) => chapter.openable === true)
    || null
  )
}

function enrichExample(item, index) {
  const title = typeof item === 'string' ? item : item.title
  const description = typeof item === 'string' ? '' : item.description

  return {
    title,
    description,
    fullDescription: description || 'Aucun détail supplémentaire ajouté.',
    explanation: description || 'Exemple fourni par le professeur.',
    expectedResult: 'Comprendre et reformuler ce que montre cet exemple.',
    code: typeof item === 'object' ? item.code : '',
    order: index + 1,
  }
}

function buildSummarySections(course) {
  const objectives = Array.isArray(course?.objectives) ? course.objectives : []
  const skills = Array.isArray(course?.skills) ? course.skills : []
  const chapters = Array.isArray(course?.chapters) ? course.chapters : []
  return {
    keyPoints: objectives.slice(0, 5),
    importantConcepts: chapters.map((chapter) => chapter.title).slice(0, 6),
    takeaways: skills.slice(0, 5),
  }
}

function splitParagraphs(value) {
  return normalizeDisplayText(value)
    .split(/\n{2,}|\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function asList(value) {
  return Array.isArray(value) ? value.map(normalizeDisplayText).filter(Boolean) : splitParagraphs(value)
}

function normalizeText(value) {
  if (value === null || value === undefined) {
    return ''
  }

  if (typeof value === 'string') {
    return value.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  }

  if (Array.isArray(value)) {
    return value.map((item) => normalizeText(item)).filter(Boolean).join(' ')
  }

  if (typeof value === 'object') {
    const candidate = value.content ?? value.text ?? value.title ?? value.label ?? value.name
    return candidate !== undefined ? normalizeText(candidate) : ''
  }

  return String(value).trim().toLowerCase()
}

function normalizeDisplayText(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(normalizeDisplayText).filter(Boolean).join('\n')
  if (typeof value === 'object') {
    const candidate = value.content ?? value.text ?? value.title ?? value.label ?? value.name
    if (candidate !== undefined) return normalizeDisplayText(candidate)
    try {
      return JSON.stringify(value)
    } catch {
      return ''
    }
  }
  return String(value)
}

function normalizeLessonBlock(block) {
  if (!block || typeof block !== 'object') return null

  const rawType = normalizeBlockType(block.type)
  const rawTitle = normalizeDisplayText(block.title ?? block.label ?? block.name)
  const rawContent = block.content ?? block.text ?? block.value ?? block.question
  const latexBlock = normalizeLatexLessonBlock(rawType, rawTitle, rawContent)

  if (latexBlock) {
    return {
      ...block,
      ...latexBlock,
    }
  }

  const content = normalizeBlockContent(rawType, rawContent)
  const title = cleanLatexDisplayText(rawTitle)

  if (!hasNormalizedBlockPayload(rawType, title, content, block)) return null

  return {
    ...block,
    type: rawType,
    title,
    content,
  }
}

function normalizeBlockType(type) {
  const cleanType = normalizeText(type).replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
  return cleanType || 'paragraph'
}

function normalizeBlockContent(type, content) {
  if (type === 'table' && Array.isArray(content)) return content
  if ((type === 'knowledge_check' || type === 'mini_assessment') && content && typeof content === 'object' && !Array.isArray(content)) return content
  if (type === 'key_points' && Array.isArray(content)) return content.map((item) => cleanLatexDisplayText(item)).filter(Boolean)
  if (type === 'visual' && content && typeof content === 'object') return content
  if (type === 'diagram' || type === 'code') return normalizeDisplayText(content)
  return cleanLatexDisplayText(content)
}

function hasNormalizedBlockPayload(type, title, content, block) {
  if (title) return true
  if (Array.isArray(content)) return content.length > 0
  if (content && typeof content === 'object') return Object.keys(content).length > 0
  if (normalizeDisplayText(content).trim()) return true

  if (type === 'visual' || type === 'image') {
    const spec = block.spec && typeof block.spec === 'object' ? block.spec : {}
    return Boolean(
      block.mermaid_code
      || block.mermaidCode
      || block.file_path
      || block.image_path
      || block.path
      || block.alt_text
      || block.alt
      || block.description
      || block.columns?.length
      || block.rows?.length
      || spec.mermaid_code
      || spec.mermaidCode
      || spec.file_path
      || spec.image_path
      || spec.path
      || spec.alt_text
      || spec.alt
      || spec.description
      || spec.columns?.length
      || spec.rows?.length,
    )
  }

  return false
}

function normalizeLatexLessonBlock(type, title, content) {
  if (typeof content !== 'string' || !content.includes('\\')) return null
  if (type === 'diagram' || type === 'code' || type === 'visual') return null

  const environment = extractLatexEnvironment(content)
  if (!environment) {
    const cleanedContent = cleanLatexDisplayText(content)
    return cleanedContent
      ? { type, title: cleanLatexDisplayText(title), content: cleanedContent }
      : null
  }

  const environmentName = normalizeText(environment.name).replace(/[^a-z0-9]/g, '')
  const cleanedBody = cleanLatexDisplayText(environment.body)
  const items = splitLatexItems(environment.body)

  if (environmentName === 'objectifbox' || environmentName === 'objectifsbox') {
    return {
      type: 'bullet_list',
      title: cleanLatexDisplayText(title) || 'Objectifs',
      content: items.length > 0 ? items : splitParagraphs(cleanedBody),
    }
  }

  const environmentTypes = {
    definitionbox: ['definition', 'Définition'],
    exemplebox: ['example', 'Exemple'],
    examplebox: ['example', 'Exemple'],
    methodbox: ['methodology', 'Méthode'],
    methodebox: ['methodology', 'Méthode'],
    methodologybox: ['methodology', 'Méthode'],
    warningbox: ['warning', 'Attention'],
    attentionbox: ['warning', 'Attention'],
    summarybox: ['summary', 'Résumé'],
    resumebox: ['summary', 'Résumé'],
    keypointbox: ['key_points', 'Points clés'],
    pointsclesbox: ['key_points', 'Points clés'],
  }
  const mapped = environmentTypes[environmentName]

  if (mapped) {
    const [mappedType, defaultTitle] = mapped
    return {
      type: mappedType,
      title: cleanLatexDisplayText(title) || defaultTitle,
      content: mappedType === 'key_points' && items.length > 0 ? items : cleanedBody,
    }
  }

  return cleanedBody
    ? { type, title: cleanLatexDisplayText(title), content: cleanedBody }
    : null
}

function extractLatexEnvironment(value) {
  const match = String(value || '').match(/\\begin\{([^}]+)\}([\s\S]*?)\\end\{\1\}/i)
  if (!match) return null
  return {
    name: match[1],
    body: match[2],
  }
}

function splitLatexItems(value) {
  const source = String(value || '')
    .replace(/\\item(?:\s*\[[^\]]*\])?/g, '\n')
    .replace(/\\\\/g, '\n')

  return cleanLatexDisplayText(source)
    .split(/\n{2,}|\r?\n/)
    .map((item) => item.replace(/^[-•]\s*/, '').trim())
    .filter(Boolean)
}

function cleanLatexDisplayText(value) {
  if (value === null || value === undefined) return ''
  if (typeof value !== 'string') return normalizeDisplayText(value)

  let text = value
    .replace(/%.*$/gm, '')
    .replace(/\\begin\{[^}]+\}/g, '\n')
    .replace(/\\end\{[^}]+\}/g, '\n')
    .replace(/\\item(?:\s*\[[^\]]*\])?/g, '\n')
    .replace(/\\\\/g, '\n')

  const wrappingCommands = [
    'textbf',
    'textit',
    'emph',
    'underline',
    'section',
    'subsection',
    'subsubsection',
    'paragraph',
    'chapter',
    'caption',
    'title',
  ]

  wrappingCommands.forEach((command) => {
    const pattern = new RegExp(`\\\\${command}\\*?\\{([^{}]*)\\}`, 'g')
    text = text.replace(pattern, '$1')
  })

  text = text
    .replace(/\\(?:label|ref|pageref|cite)\{[^}]*\}/g, '')
    .replace(/\\(?:vspace|hspace)\*?\{[^}]*\}/g, ' ')
    .replace(/\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?/g, '')
    .replace(/\\([%&#_$])/g, '$1')
    .replace(/[{}]/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim()

  return text
}

function deduplicateLessonBlocks(blocks) {
  const seen = new Set()

  return blocks.filter((block) => {
    const contentSignature = typeof block.content === 'object'
      ? safeJsonStringify(block.content)
      : normalizeText(block.content)
    const signature = [
      block.type,
      normalizeText(block.title),
      contentSignature,
      normalizeText(block.mermaid_code || block.mermaidCode || block.spec?.mermaid_code || block.spec?.mermaidCode),
      normalizeText(block.file_path || block.image_path || block.path || block.spec?.file_path || block.spec?.image_path || block.spec?.path),
    ].join('|')

    if (seen.has(signature)) return false
    seen.add(signature)
    return true
  })
}

function safeJsonStringify(value) {
  try {
    return JSON.stringify(value)
  } catch {
    return ''
  }
}

function formatCourseDate(value) {
  if (!value || value === '-') return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' })
}

function resolvePdfUrl(pdfUrl) {
  if (/^https?:\/\//i.test(pdfUrl)) {
    return pdfUrl
  }

  return `${API_BASE_URL}${pdfUrl.startsWith('/') ? pdfUrl : `/${pdfUrl}`}`
}

function resolveLearnerLevel(diagnosticResult, userProfile, course) {
  return diagnosticResult?.level
    || userProfile?.level
    || userProfile?.current_level
    || userProfile?.diagnostic_level
    || course?.level
    || course?.difficulty_level?.name
    || 'intermediaire'
}

function normalizeLevel(level) {
  const normalized = String(level || '')
    .replace(/\u00c3\u00a9/g, 'e')
    .replace(/\u00c3\u00a8/g, 'e')
    .replace(/\u00c3\u00a0/g, 'a')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

  if (normalized.includes('debut')) return 'debutant'
  if (normalized.includes('avance') || normalized.includes('avanc')) return 'avance'
  if (normalized.includes('inter')) return 'intermediaire'
  if (normalized.includes('adapt')) return 'intermediaire'
  return 'intermediaire'
}

function getDisplayLevel(level) {
  const normalizedLevel = normalizeLevel(level)
  if (normalizedLevel === 'avance') return 'Avancé'
  if (normalizedLevel === 'intermediaire') return 'Intermédiaire'
  return 'Débutant'
}

export default CourseDetailPage
