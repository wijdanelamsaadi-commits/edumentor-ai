import { useEffect, useMemo, useState } from 'react'
import { Award, BarChart3, BookOpen, CheckCircle2, ClipboardList, Download, Flame, Lock, Star, Target, Trophy } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'
import { useUserData } from '../hooks/useUserData.js'
import { fetchCourses } from '../services/api.js'
import { buildCertificateEligibility, generateCertificatePdf } from '../services/certificate.js'

const PASSING_QUIZ_SCORE = 60

function ProfilePage() {
  const navigate = useNavigate()
  const { currentUser, userProfile } = useAuth()
  const { diagnosticResult, progress, quizResults } = useUserData()
  const [courses, setCourses] = useState([])
  const localData = useMemo(() => ({
    diagnosticResult,
    quizResults,
    chapterProgress: progress,
  }), [diagnosticResult, progress, quizResults])

  useEffect(() => {
    let isMounted = true

    fetchCourses()
      .then((data) => {
        if (isMounted) {
          setCourses(Array.isArray(data) ? data : [])
        }
      })
      .catch(() => {
        if (isMounted) {
          setCourses([])
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  const courseStats = useMemo(
    () => buildCourseStats(courses, localData.chapterProgress),
    [courses, localData.chapterProgress],
  )
  const quizRows = useMemo(
    () => buildQuizRows(courses, localData.quizResults),
    [courses, localData.quizResults],
  )
  const activities = useMemo(
    () => buildActivities(courses, localData),
    [courses, localData],
  )
  const badges = useMemo(
    () => buildBadges(courseStats, quizRows),
    [courseStats, quizRows],
  )
  const certificate = useMemo(
    () => buildCertificateEligibility({ courses, progress: localData.chapterProgress, quizResults: localData.quizResults }),
    [courses, localData.chapterProgress, localData.quizResults],
  )

  const hasData = Boolean(localData.diagnosticResult) || quizRows.length > 0 || courseStats.hasProgress
  const diagnosticScore = Number.isFinite(localData.diagnosticResult?.score) ? `${localData.diagnosticResult.score}%` : '--'
  const currentLevel = localData.diagnosticResult?.level || 'Non defini'
  const passedQuizCount = quizRows.filter((quiz) => quiz.score >= PASSING_QUIZ_SCORE).length
  const learnerName = userProfile?.full_name || currentUser?.displayName || currentUser?.email?.split('@')[0] || 'Apprenant EduMentor'
  const learnerEmail = userProfile?.email || currentUser?.email || ''

  async function downloadCertificate() {
    if (!certificate.isEligible) return
    await generateCertificatePdf({
      email: learnerEmail,
      finalScore: certificate.finalScore,
      fullName: learnerName,
      level: currentLevel,
    })
  }

  return (
    <section className="page-section profile-page">
      <div className="page-heading">
        <h1>Progression</h1>
        <p>Suivez vos performances, vos badges et votre historique d'apprentissage.</p>
      </div>

      {!hasData && (
        <article className="progress-banner">
          <span><BarChart3 size={30} /></span>
          <div>
            <strong>Aucune donnee de progression disponible</strong>
            <p>Passez le test diagnostique ou terminez un quiz pour alimenter votre profil.</p>
          </div>
          <button className="outline-button" onClick={() => navigate('/diagnostic')} type="button">Passer le test</button>
        </article>
      )}

      <div className="dashboard-stats">
        <article className="metric-card metric-wide">
          <span className="soft-icon"><BarChart3 size={42} /></span>
          <div>
            <p>Niveau actuel</p>
            <h2>{currentLevel}</h2>
            <strong>{localData.diagnosticResult ? 'Niveau obtenu au dernier test' : 'Test diagnostique non encore passe'}</strong>
          </div>
        </article>
        <article className="metric-card">
          <p>Score diagnostique</p>
          <h2>{diagnosticScore}</h2>
          <div className="progress-track"><span style={{ width: `${localData.diagnosticResult?.score || 0}%` }} /></div>
          <strong>{localData.diagnosticResult ? formatDate(localData.diagnosticResult.date) : 'Aucune donnee'}</strong>
        </article>
        <article className="metric-card">
          <p>Progression globale</p>
          <h2>{courseStats.globalProgress}%</h2>
          <div className="progress-track"><span style={{ width: `${courseStats.globalProgress}%` }} /></div>
          <strong>{courseStats.completedCourses} cours termines</strong>
        </article>
      </div>

      <div className="dashboard-stats">
        <article className="metric-card">
          <p>Cours termines</p>
          <h2>{courseStats.completedCourses}</h2>
          <strong>{courseStats.completedCourses > 0 ? 'Progression validee' : 'Aucun cours termine'}</strong>
        </article>
        <article className="metric-card">
          <p>Cours en cours</p>
          <h2>{courseStats.startedCourses}</h2>
          <strong>{courseStats.startedCourses > 0 ? 'A continuer' : 'Aucun cours en cours'}</strong>
        </article>
        <article className="metric-card">
          <p>Quiz realises</p>
          <h2>{quizRows.length}</h2>
          <strong>{passedQuizCount} quiz reussis</strong>
        </article>
      </div>

      <article className="panel-card certificate-panel">
        <div className="panel-title">
          <div>
            <h2>Certificat EduMentor AI</h2>
            <p>Disponible apres validation complete du parcours et reussite du quiz final.</p>
          </div>
          <span className={certificate.isEligible ? 'admin-pill' : 'admin-pill muted'}>
            {certificate.isEligible ? 'Disponible' : 'Verrouille'}
          </span>
        </div>
        <div className="certificate-content">
          <span className="soft-icon"><Award size={44} /></span>
          <div>
            <strong>{certificate.completedCourses} / {certificate.totalCourses || courses.length || 8} cours termines</strong>
            <p>
              Quiz final : {certificate.finalCourse?.title || 'Cours final'} - score {certificate.finalScore}%.
              Le certificat est active a partir de 70%.
            </p>
            {!certificate.allCoursesCompleted && <p>Terminez tous les cours pour debloquer cette etape.</p>}
            {certificate.allCoursesCompleted && !certificate.finalQuizPassed && <p>Reussissez le quiz final avec au moins 70%.</p>}
          </div>
          <button className="primary-button" disabled={!certificate.isEligible} onClick={downloadCertificate} type="button">
            <Download size={18} />
            Telecharger mon certificat
          </button>
        </div>
      </article>

      <div className="dashboard-grid">
        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Scores des quiz par cours</h2>
            <button type="button">Voir tout</button>
          </div>
          {quizRows.length > 0 ? quizRows.map((quiz) => (
            <div className="history-item" key={quiz.courseId}>
              <span><ClipboardList size={22} /></span>
              <div>
                <strong>{quiz.title}</strong>
                <p>Score obtenu : {quiz.score}% - {quiz.correct} / {quiz.total}</p>
              </div>
              <time>{formatDate(quiz.date)}<br />{formatTime(quiz.date)}</time>
            </div>
          )) : (
            <EmptyLine title="Aucun quiz termine" text="Commencez un quiz depuis le detail d'un cours." />
          )}
        </article>

        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Historique des activites</h2>
            <button type="button">Voir tout</button>
          </div>
          {activities.length > 0 ? activities.map((activity) => (
            <div className="history-item" key={`${activity.title}-${activity.date}-${activity.text}`}>
              <span><activity.Icon size={22} /></span>
              <div>
                <strong>{activity.title}</strong>
                <p>{activity.text}</p>
              </div>
              <time>{formatDate(activity.date)}<br />{formatTime(activity.date)}</time>
            </div>
          )) : (
            <EmptyLine title="Aucune activite recente" text="Votre historique apparaitra ici apres un test, un cours ou un quiz." />
          )}
        </article>
      </div>

      <article className="panel-card badges-panel">
        <div className="panel-title">
          <div>
            <h2>Badges</h2>
            <p>Debloquez des badges en atteignant vos objectifs et en restant regulier dans votre apprentissage.</p>
          </div>
          <button type="button">Voir tous les badges</button>
        </div>
        <div className="badge-grid">
          {badges.map(([Icon, title, text]) => (
            <div className="badge-card" key={title}>
              <span><Icon size={54} /></span>
              <strong>{title}</strong>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </article>
    </section>
  )
}

function EmptyLine({ title, text }) {
  return (
    <div className="history-item">
      <span><CheckCircle2 size={22} /></span>
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
      <time>--<br />--</time>
    </div>
  )
}

function buildCourseStats(courses, chapterProgress) {
  const progressRows = courses.map((course) => {
    const savedProgress = chapterProgress?.[course.id]
    return {
      course,
      progress: Number(savedProgress?.progress || 0),
      activeChapter: getActiveChapter(savedProgress),
      updated_at: savedProgress?.updated_at || null,
    }
  })
  const totalCourses = courses.length || 8
  const totalProgress = progressRows.reduce((sum, row) => sum + row.progress, 0)

  return {
    completedCourses: progressRows.filter((row) => row.progress >= 100).length,
    globalProgress: Math.round(totalProgress / totalCourses),
    hasProgress: progressRows.some((row) => row.progress > 0),
    progressRows,
    startedCourses: progressRows.filter((row) => row.progress > 0 && row.progress < 100).length,
  }
}

function buildQuizRows(courses, quizResults) {
  return Object.entries(quizResults || {})
    .map(([courseId, result]) => {
      const course = courses.find((item) => item.id === Number(courseId))
      if (!course) return null

      return {
        courseId,
        correct: result.correct ?? 0,
        date: result.date,
        score: Number(result.score || 0),
        title: course.title,
        total: result.total ?? 10,
      }
    })
    .filter(Boolean)
    .sort((first, second) => new Date(second.date || 0) - new Date(first.date || 0))
}

function buildActivities(courses, localData) {
  const activities = []

  Object.entries(localData.chapterProgress || {}).forEach(([courseId, progress]) => {
    const course = courses.find((item) => item.id === Number(courseId))
    if (!course || !progress?.updated_at) return
    const activeChapter = getActiveChapter(progress)
    const numericProgress = Number(progress.progress || 0)

    activities.push({
      Icon: numericProgress >= 100 ? CheckCircle2 : BookOpen,
      date: progress.updated_at,
      text: activeChapter ? `Chapitre actif : ${activeChapter.title}` : `Progression : ${numericProgress}%`,
      title: `${numericProgress >= 100 ? 'Cours termine' : 'Cours consulte'} : ${course.title}`,
    })
  })

  buildQuizRows(courses, localData.quizResults).forEach((quiz) => {
    activities.push({
      Icon: ClipboardList,
      date: quiz.date,
      text: `Score obtenu : ${quiz.score}%`,
      title: `Quiz ${quiz.score >= PASSING_QUIZ_SCORE ? 'reussi' : 'a revoir'} : ${quiz.title}`,
    })
  })

  if (localData.diagnosticResult?.date) {
    activities.push({
      Icon: BarChart3,
      date: localData.diagnosticResult.date,
      text: `Niveau obtenu : ${localData.diagnosticResult.level} - Score : ${localData.diagnosticResult.score}%`,
      title: 'Test diagnostique complete',
    })
  }

  return activities
    .filter((activity) => activity.date)
    .sort((first, second) => new Date(second.date) - new Date(first.date))
    .slice(0, 6)
}

function buildBadges(courseStats, quizRows) {
  const passedQuizCount = quizRows.filter((quiz) => quiz.score >= PASSING_QUIZ_SCORE).length
  const highQuizCount = quizRows.filter((quiz) => quiz.score >= 80).length
  const excellentQuizCount = quizRows.filter((quiz) => quiz.score >= 90).length

  return [
    [Star, 'Premier pas', courseStats.hasProgress ? 'Debloque' : 'Commencer 1 cours'],
    [BookOpen, 'Apprenant regulier', courseStats.startedCourses >= 3 ? 'Debloque' : 'Commencer 3 cours'],
    [Target, 'Quiz Master', highQuizCount >= 3 ? 'Debloque' : 'Obtenir 80%+ dans 3 quiz'],
    [Flame, 'Perseverant', courseStats.globalProgress >= 50 ? 'Debloque' : 'Atteindre 50% de progression globale'],
    [Trophy, 'Excellent', excellentQuizCount >= 2 ? 'Debloque' : 'Obtenir 90%+ dans 2 quiz'],
    [passedQuizCount >= 1 ? CheckCircle2 : Lock, 'Quiz valide', passedQuizCount >= 1 ? 'Debloque' : 'Reussir 1 quiz'],
  ]
}

function getActiveChapter(progress) {
  if (!Array.isArray(progress?.chapters)) {
    return null
  }

  return (
    progress.chapters.find((chapter) => chapter.openable === true && chapter.completed !== true)
    || [...progress.chapters].reverse().find((chapter) => chapter.completed === true)
    || null
  )
}

function formatDate(dateValue) {
  const date = new Date(dateValue)

  if (Number.isNaN(date.getTime())) {
    return '--'
  }

  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date)
}

function formatTime(dateValue) {
  const date = new Date(dateValue)

  if (Number.isNaN(date.getTime())) {
    return '--'
  }

  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export default ProfilePage
