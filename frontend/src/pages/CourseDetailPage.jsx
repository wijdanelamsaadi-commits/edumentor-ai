import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, BookOpen, CheckCircle2, Download, FileText, Lock, Play, Target } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { API_BASE_URL, fetchCourseById, updateCourseProgress } from '../services/api.js'
import { addNotification } from '../services/notifications.js'

const TABS = [
  { id: 'content', label: 'Contenu', icon: BookOpen },
  { id: 'summary', label: 'Resume', icon: FileText },
  { id: 'examples', label: 'Exemples', icon: CheckCircle2 },
  { id: 'objectives', label: 'Objectifs', icon: Target },
]

const CHAPTER_PROGRESS_STORAGE_KEY = 'edumentor:chapterProgress'

function CourseDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [course, setCourse] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [errorStatus, setErrorStatus] = useState(null)
  const [diagnosticResult, setDiagnosticResult] = useState(null)
  const [activeTab, setActiveTab] = useState('content')
  const [selectedChapter, setSelectedChapter] = useState(null)
  const [selectedExample, setSelectedExample] = useState(null)
  const [notice, setNotice] = useState('')
  const [chapterProgressMap, setChapterProgressMap] = useState({})

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
  }, [id])

  const courseWithLocalProgress = useMemo(
    () => applyLocalChapterProgress(course, chapterProgressMap[course?.id]),
    [course, chapterProgressMap],
  )
  const learnerLevel = getDisplayLevel(diagnosticResult?.level || courseWithLocalProgress?.level)
  const courseContent = useMemo(() => buildCourseContent(courseWithLocalProgress), [courseWithLocalProgress])

  useEffect(() => {
    if (courseContent.chapters.length === 0) {
      return
    }

    if (!selectedChapter) {
      setSelectedChapter(getInitialSelectedChapter(courseContent.chapters))
      return
    }

    const syncedChapter = courseContent.chapters.find((chapter) => chapter.title === selectedChapter.title)
    if (syncedChapter && syncedChapter !== selectedChapter) {
      setSelectedChapter(syncedChapter)
    }
  }, [courseContent.chapters, selectedChapter])

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
            <span className="course-big-icon"><BookOpen size={64} /><strong>{courseWithLocalProgress.tag || String(courseWithLocalProgress.id).padStart(2, '0')}</strong></span>
            <div>
              <h1>{courseWithLocalProgress.title}</h1>
              <span className="course-level-badge">Adapte a votre niveau : {learnerLevel}</span>
              <p>{courseWithLocalProgress.summary}</p>
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
            courseContent={courseContent}
            notice={notice}
            onSelectExample={setSelectedExample}
            onSelectChapter={(chapter) => {
              setSelectedChapter(chapter)
              setNotice('')
            }}
            onSelectNextChapter={() => {
              const currentIndex = courseContent.chapters.findIndex((chapter) => chapter.title === selectedChapter?.title)

              if (!courseWithLocalProgress || currentIndex === -1) {
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
                  [courseWithLocalProgress.id]: progressRecord,
                }
                persistChapterProgress(courseWithLocalProgress.id, progressRecord, nextMap)
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
                  message: `Votre progression dans ${courseWithLocalProgress.title} est maintenant de 100%.`,
                })
                setNotice('Cours terminé')
                addNotification({
                  type: 'progress',
                  title: 'Cours terminé',
                  message: `Vous avez terminé le cours ${courseWithLocalProgress.title}.`,
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
                message: `Votre progression dans ${courseWithLocalProgress.title} est maintenant de ${nextProgress}%.`,
              })
            }}
            selectedExample={selectedExample}
            selectedChapter={selectedChapter}
          />
        </div>
        <aside className="detail-side">
          <article className="panel-card course-info">
            <h2>Informations du cours</h2>
            <InfoLine label="Niveau" value={learnerLevel} highlight />
            <InfoLine label="Duree estimee" value={courseContent.information.duration} />
            <InfoLine label="Chapitres" value={courseContent.information.chapters_count} />
            <InfoLine label="Langue" value={courseContent.information.language} />
            <InfoLine label="Derniere mise a jour" value={courseContent.information.last_update} />
          </article>
          <article className="panel-card center-card">
            <button className="primary-button quiz-cta" onClick={() => navigate(`/quiz/${courseWithLocalProgress.id}`)} type="button"><FileText size={24} />Commencer le quiz</button>
            <p>Testez vos connaissances sur ce cours</p>
          </article>
          <button
            className="download-button"
            onClick={() => {
              if (!courseWithLocalProgress.pdf_url) {
                setNotice('Support PDF indisponible')
                setActiveTab('content')
                return
              }

              window.open(resolvePdfUrl(courseWithLocalProgress.pdf_url), '_blank', 'noopener,noreferrer')
              addNotification({
                type: 'pdf',
                title: 'Support PDF téléchargé',
                message: `Le support PDF du cours ${courseWithLocalProgress.title} a été ouvert.`,
              })
            }}
            type="button"
          >
            <Download size={22} />Telecharger le support PDF
          </button>
          <article className="quote-card">"<p>L'IA ne remplacera pas les humains. Mais les humains qui utilisent l'IA remplaceront ceux qui ne le font pas.</p><span>- Andrew Ng</span></article>
        </aside>
      </div>
    </section>
  )
}

function ContentPanel({
  activeTab,
  courseContent,
  notice,
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
        <section className="rich-section">
          <h3>Points cles</h3>
          <ul>
            {courseContent.summarySections.keyPoints.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
        <section className="rich-section">
          <h3>Notions importantes</h3>
          <ul>
            {courseContent.summarySections.importantConcepts.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
        <section className="rich-section">
          <h3>A retenir</h3>
          <ul>
            {courseContent.summarySections.takeaways.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      </article>
    )
  }

  if (activeTab === 'examples') {
    return (
      <article className="panel-card examples-panel">
        <h2>Exemples</h2>
        <div className="example-grid">
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
        </div>
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
        </article>
        <article className="panel-card objectives-panel">
          <h2>Competences acquises</h2>
          {courseContent.skills.map((item, index) => (
            <p className={index < courseContent.unlockedSkillCount ? 'skill-unlocked' : 'skill-locked'} key={item}>
              {index < courseContent.unlockedSkillCount ? <CheckCircle2 size={20} /> : <Lock size={20} />}
              {item}
            </p>
          ))}
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
        <ChapterLesson chapter={selectedChapter} onNext={onSelectNextChapter} />
      )}
    </>
  )
}

function ChapterLesson({ chapter, onNext }) {
  const lesson = chapter.lesson

  return (
    <article className="panel-card lesson-panel chapter-lesson">
      <h2>{chapter.title}</h2>
      <section className="rich-section">
        <h3>Introduction</h3>
        {lesson.introduction.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </section>
      <section className="rich-section">
        <h3>Explication detaillee</h3>
        {lesson.explanation.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </section>
      <section className="rich-section">
        <h3>Exemple concret</h3>
        <p>{lesson.concreteExample}</p>
      </section>
      <section className="rich-section">
        <h3>Exemple EduMentor AI</h3>
        <p>{lesson.edumentorExample}</p>
      </section>
      <section className="rich-section">
        <h3>Conseils</h3>
        <ul>
          {lesson.tips.map((tip) => <li key={tip}>{tip}</li>)}
        </ul>
      </section>
      <section className="rich-section">
        <h3>Resume du chapitre</h3>
        <ul>
          {lesson.summary.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>
      <section className="rich-section">
        <h3>Mini exercice</h3>
        <p>{lesson.exercise}</p>
      </section>
      <button className="primary-button" onClick={onNext} type="button">Chapitre suivant</button>
    </article>
  )
}

function InfoLine({ label, value, highlight }) {
  return <p><span>{label}</span><strong className={highlight ? 'red-text' : ''}>{value}</strong></p>
}

function buildCourseContent(course) {
  const chapters = Array.isArray(course?.chapters) ? course.chapters : []
  const courseProfile = getCourseProfile(course)
  const examples = Array.isArray(course?.examples)
    ? course.examples.map((item, index) => enrichExample(item, index, courseProfile))
    : []
  const information = course?.information || {}
  const progress = Number(course?.progress || 0)

  return {
    chapters: chapters.map((chapter, index) => ({
      ...chapter,
      lesson: buildChapterLesson(chapter, index, courseProfile),
    })),
    completedChapters: chapters.filter((chapter) => chapter.completed === true).length,
    progress,
    summary: course?.summary || '',
    description: course?.description || '',
    objectives: Array.isArray(course?.objectives) ? course.objectives : [],
    examples,
    skills: Array.isArray(course?.skills) ? course.skills : [],
    summarySections: buildSummarySections(courseProfile),
    completedObjectiveCount: Math.max(1, Math.ceil(((course?.objectives?.length || 0) * progress) / 100)),
    unlockedSkillCount: Math.max(1, Math.ceil(((course?.skills?.length || 0) * progress) / 100)),
    information: {
      duration: information.duration || course?.duration || '-',
      chapters_count: information.chapter_count ?? information.chapters_count ?? chapters.length,
      language: information.language || course?.language || 'Francais',
      last_update: information.last_update || course?.last_update || '-',
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

function getCourseProfile(course) {
  const title = course?.title || 'ce cours'
  const normalizedTitle = normalizeLevel(course?.level) === 'avance' ? 'avance' : normalizeLevel(course?.level)
  const isRag = title.toLowerCase().includes('rag')
  const isMachineLearning = title.toLowerCase().includes('machine')
  const isIntroductionIa = title.toLowerCase().includes('introduction')

  if (isRag) {
    return {
      title,
      level: normalizedTitle,
      domain: 'RAG',
      learnerPromise: 'savoir construire une reponse fondee sur des documents pedagogiques et accompagnee de sources',
      mainConcepts: ['documents PDF', 'extraction de texte', 'chunks', 'embeddings', 'recherche semantique', 'sources'],
      platformUse: 'le chatbot EduMentor AI cherche dans les PDF du cours, selectionne les passages pertinents, puis reformule une reponse claire avec les sources.',
      codeTopic: 'rag',
    }
  }

  if (isMachineLearning) {
    return {
      title,
      level: normalizedTitle,
      domain: 'Machine Learning',
      learnerPromise: 'comprendre comment un modele apprend a partir de donnees et comment evaluer ses predictions',
      mainConcepts: ['donnees', 'features', 'labels', 'entrainement', 'prediction', 'evaluation'],
      platformUse: 'EduMentor AI peut utiliser les scores et l historique pour recommander un parcours adapte a chaque apprenant.',
      codeTopic: 'ml',
    }
  }

  if (isIntroductionIa) {
    return {
      title,
      level: normalizedTitle,
      domain: 'Introduction IA',
      learnerPromise: 'comprendre les bases de l intelligence artificielle et ses usages pedagogiques',
      mainConcepts: ['donnees', 'algorithmes', 'modele', 'prediction', 'automatisation', 'limites'],
      platformUse: 'EduMentor AI utilise ces principes pour diagnostiquer le niveau, recommander des cours et guider l apprenant.',
      codeTopic: 'general',
    }
  }

  return {
    title,
    level: normalizedTitle,
    domain: title,
    learnerPromise: 'relier les notions du cours a une situation professionnelle concrete',
    mainConcepts: ['contexte', 'methode', 'application', 'evaluation', 'limites'],
    platformUse: 'EduMentor AI transforme cette notion en activites, exemples et recommandations personnalisees.',
    codeTopic: 'general',
  }
}

function buildChapterLesson(chapter, index, profile) {
  const chapterTitle = chapter.title
  const concepts = profile.mainConcepts.join(', ')

  return {
    introduction: [
      `Ce chapitre vous installe dans une situation concrete : comprendre ${chapterTitle.toLowerCase()} pour progresser dans ${profile.domain}. L objectif n est pas seulement de lire une definition, mais de savoir reconnaitre quand cette notion intervient dans un vrai parcours e-learning.`,
      `A la fin du chapitre, vous devez pouvoir expliquer le role de cette etape, identifier les elements importants et relier la notion au fonctionnement global d EduMentor AI. Le chapitre est pense comme une sequence courte mais complete, avec un exemple, des conseils et un exercice d application.`,
    ],
    explanation: [
      `${chapterTitle} s inscrit dans un enchainement logique : on part d un besoin pedagogique, on le transforme en donnees ou en activite, puis on verifie que le resultat aide vraiment l apprenant. Dans ce cours, les notions centrales sont ${concepts}. Elles servent de repere pour comprendre ce que le systeme fait, pourquoi il le fait et comment evaluer la qualite du resultat.`,
      `Pour travailler correctement cette partie, il faut distinguer le principe, la mise en oeuvre et la verification. Le principe explique l idee generale. La mise en oeuvre decrit les etapes pratiques. La verification permet de savoir si la solution est fiable, utile et adaptee au niveau de l etudiant. Cette separation est essentielle dans une plateforme comme EduMentor AI, car une fonctionnalite pedagogique doit rester claire pour l apprenant et robuste cote technique.`,
      `Dans un contexte professionnel, ce chapitre aide aussi a documenter le raisonnement. Une bonne plateforme e-learning ne se contente pas d afficher du contenu : elle structure la progression, donne des exemples, mesure l avancement et propose une action suivante. C est cette logique de parcours qui rapproche EduMentor AI d une experience de type Coursera ou OpenClassrooms.`,
    ],
    concreteExample: `Imaginez un apprenant qui bloque sur "${chapterTitle}". Au lieu de lui donner une phrase courte, la plateforme lui propose une explication progressive, un exemple, un mini exercice et une verification de comprehension. L apprenant peut revenir au chapitre, comparer avec les exemples et avancer seulement quand la notion est plus claire.`,
    edumentorExample: `Dans EduMentor AI, cette notion est utilisee pour personnaliser le parcours : ${profile.platformUse} Le chapitre devient donc une brique d apprentissage active, pas une simple page statique.`,
    tips: [
      'Commencez par reformuler la notion avec vos propres mots avant de lire les details.',
      'Reliez toujours le chapitre a un cas d usage concret de la plateforme.',
      'Verifiez ce qui est acquis, ce qui reste flou et quelle action doit suivre.',
      index === 0 ? 'Pour le premier chapitre, concentrez-vous sur la vision globale avant les details.' : 'Comparez ce chapitre avec le precedent pour comprendre la progression.',
    ],
    summary: [
      `${chapterTitle} joue un role precis dans le parcours ${profile.domain}.`,
      'La comprehension doit aller du principe vers l application.',
      'Un bon contenu pedagogique combine explication, exemple, exercice et feedback.',
      'La notion devient utile quand elle aide a prendre une decision ou a progresser.',
    ],
    exercise: `Redigez en 5 lignes une explication de "${chapterTitle}" pour un apprenant de votre niveau. Ajoutez ensuite un exemple EduMentor AI et une question de verification que vous pourriez poser dans un quiz.`,
  }
}

function enrichExample(item, index, profile) {
  const title = typeof item === 'string' ? item : item.title
  const description = typeof item === 'string' ? 'Exemple fourni par le backend pour illustrer ce cours.' : item.description
  const code = buildExampleCode(profile.codeTopic, title)

  return {
    title,
    description,
    fullDescription: `Cet exemple montre comment transformer une notion de ${profile.domain} en situation d apprentissage observable. L objectif est de partir d un probleme simple, d appliquer la methode du cours, puis d interpreter le resultat obtenu.`,
    explanation: `Dans EduMentor AI, l exemple "${title}" peut etre utilise pour guider l apprenant pas a pas. Le systeme presente le contexte, demande une action, affiche un resultat attendu et relie l activite a la progression du cours.`,
    expectedResult: `L apprenant doit etre capable d expliquer la logique de l exemple, de reproduire les etapes principales et de dire pourquoi ce resultat est utile dans son parcours.`,
    code,
    order: index + 1,
  }
}

function buildExampleCode(topic, title) {
  if (topic === 'rag') {
    return `query = "${title}"\nchunks = search_documents(query, limit=3)\nanswer = build_answer_from_sources(chunks)\nprint(answer.sources)`
  }

  if (topic === 'ml') {
    return `score = 82\nlevel = "avance" if score >= 80 else "intermediaire"\nrecommendation = f"Proposer un cours de niveau {level}"`
  }

  if (topic === 'python') {
    return `notes = [14, 16, 12, 18]\naverage = sum(notes) / len(notes)\nprint(f"Moyenne: {average}")`
  }

  return ''
}

function buildSummarySections(profile) {
  return {
    keyPoints: [
      `${profile.domain} doit etre compris comme un parcours progressif, pas comme une liste de definitions.`,
      `L objectif principal est de ${profile.learnerPromise}.`,
      'Chaque chapitre doit relier theorie, exemple, exercice et progression.',
      'La valeur pedagogique vient de la clarte du feedback donne a l apprenant.',
    ],
    importantConcepts: profile.mainConcepts.map((concept) => `Maitriser la notion de ${concept} et savoir l expliquer dans un cas concret.`),
    takeaways: [
      'Un bon cours aide l apprenant a comprendre, pratiquer et verifier ses acquis.',
      'Les exemples doivent etre directement relies a un usage de la plateforme.',
      'La progression permet de transformer le contenu en parcours personnalise.',
      'Les competences acquises doivent evoluer avec l avancement reel.',
    ],
  }
}

function resolvePdfUrl(pdfUrl) {
  if (/^https?:\/\//i.test(pdfUrl)) {
    return pdfUrl
  }

  return `${API_BASE_URL}${pdfUrl.startsWith('/') ? pdfUrl : `/${pdfUrl}`}`
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
  return normalized.includes('inter') ? 'intermediaire' : 'debutant'
}

function getDisplayLevel(level) {
  const normalizedLevel = normalizeLevel(level)
  if (normalizedLevel === 'avance') return 'Avance'
  if (normalizedLevel === 'intermediaire') return 'Intermediaire'
  return 'Debutant'
}

export default CourseDetailPage
