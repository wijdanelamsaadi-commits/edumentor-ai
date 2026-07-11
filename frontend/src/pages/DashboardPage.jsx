import { useEffect, useMemo, useState } from 'react'
import { BarChart3, BookOpen, Calendar, CheckCircle2, Star } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useUserData } from '../hooks/useUserData.js'
import { fetchCourses } from '../services/api.js'

const PASSING_QUIZ_SCORE = 60

function DashboardPage() {
  const navigate = useNavigate()
  const { diagnosticResult, progress, quizResults } = useUserData()
  const [courses, setCourses] = useState([])
  const localData = useMemo(() => ({
    chapterProgress: progress,
    quizResults,
  }), [progress, quizResults])

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

  const dashboardData = useMemo(
    () => buildDashboardData(courses, localData, diagnosticResult),
    [courses, localData, diagnosticResult],
  )
  const learnerName = diagnosticResult?.name || 'Wijdane'
  const displayLevel = diagnosticResult?.level || 'Test diagnostique non encore passe'
  const displayScore = Number.isFinite(diagnosticResult?.score) ? `${diagnosticResult.score}%` : '--'
  const displayDate = diagnosticResult?.date ? formatDate(diagnosticResult.date) : 'Aucun test'
  const recommendations = useMemo(
    () => buildRecommendations(courses, localData, diagnosticResult, dashboardData),
    [courses, localData, diagnosticResult, dashboardData],
  )
  const activities = useMemo(
    () => buildActivities(courses, localData, diagnosticResult),
    [courses, localData, diagnosticResult],
  )

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Bonjour, {learnerName}</h1>
        <p>Prete a continuer votre apprentissage aujourd'hui ?</p>
      </div>

      <div className="dashboard-stats">
        <article className="metric-card metric-wide">
          <span className="soft-icon"><BarChart3 size={42} /></span>
          <div>
            <p>Niveau actuel</p>
            <h2>{displayLevel}</h2>
            {diagnosticResult ? (
              <strong>Score diagnostique : {displayScore} - {displayDate}</strong>
            ) : (
              <button className="outline-button" onClick={() => navigate('/diagnostic')} type="button">Passer le test</button>
            )}
          </div>
        </article>
        <article className="metric-card">
          <p>Progression globale</p>
          <h2>{dashboardData.globalProgress}%</h2>
          <div className="progress-track"><span style={{ width: `${dashboardData.globalProgress}%` }} /></div>
          <strong>{dashboardData.completedCourses} cours termines sur {courses.length || 8}</strong>
        </article>
        <article className="metric-card">
          <span className="soft-icon"><Calendar size={42} /></span>
          <p>Quiz reussis</p>
          <h2>{dashboardData.passedQuizCount}</h2>
          <strong>{dashboardData.quizCount} quiz enregistres</strong>
        </article>
      </div>

      <div className="dashboard-grid">
        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Historique</h2>
            <button type="button">Voir tout</button>
          </div>
          {activities.length > 0 ? activities.map(({ title, text, day, time, Icon }) => (
            <div className="history-item" key={`${title}-${text}-${day}-${time}`}>
              <span><Icon size={22} /></span>
              <div>
                <strong>{title}</strong>
                <p>{text}</p>
              </div>
              <time>{day}<br />{time}</time>
            </div>
          )) : (
            <div className="history-item">
              <span><BookOpen size={22} /></span>
              <div>
                <strong>Aucune activite recente</strong>
                <p>Ouvrez un cours ou terminez un quiz pour alimenter votre historique.</p>
              </div>
              <time>--<br /></time>
            </div>
          )}
        </article>

        <article className="panel-card recommend-panel">
          <div className="panel-title">
            <h2>Recommande pour vous</h2>
            <button type="button">Voir tout</button>
          </div>
          {recommendations.map((item) => (
            <RecommendedItem
              action={item.action}
              icon={item.icon}
              key={item.title}
              onClick={() => navigate(item.path)}
              subtitle={item.subtitle}
              title={item.title}
            />
          ))}
        </article>
      </div>

      {dashboardData.lastCourse ? (
        <article className="continue-card">
          <span><BookOpen size={44} /></span>
          <div>
            <h2>Continuer le dernier chapitre</h2>
            <h3>{dashboardData.lastCourse.title}</h3>
            <p>{dashboardData.lastChapter ? `Dernier chapitre actif : ${dashboardData.lastChapter.title}` : dashboardData.lastCourse.summary}</p>
            <div className="inline-progress">
              <div className="progress-track"><span style={{ width: `${dashboardData.lastCourse.progress}%` }} /></div>
              <strong>{dashboardData.lastCourse.progress}%</strong>
            </div>
          </div>
          <button className="primary-button" onClick={() => navigate(`/courses/${dashboardData.lastCourse.id}`)}>Continuer</button>
        </article>
      ) : (
        <article className="continue-card">
          <span><BookOpen size={44} /></span>
          <div>
            <h2>Aucun cours consulte</h2>
            <h3>Commencez votre parcours EduMentor AI</h3>
            <p>Choisissez un cours pour creer votre premiere progression.</p>
            <div className="inline-progress">
              <div className="progress-track"><span style={{ width: '0%' }} /></div>
              <strong>0%</strong>
            </div>
          </div>
          <button className="primary-button" onClick={() => navigate('/courses')}>Mes cours</button>
        </article>
      )}
    </section>
  )
}

function buildDashboardData(courses, localData, diagnosticResult) {
  const progressRows = courses.map((course) => {
    const savedProgress = localData.chapterProgress?.[course.id]
    const progress = Number(savedProgress?.progress || 0)
    const activeChapter = getActiveChapter(savedProgress)

    return {
      ...course,
      progress,
      activeChapter,
      updated_at: savedProgress?.updated_at || null,
    }
  })
  const totalCourses = courses.length || 8
  const totalProgress = progressRows.reduce((sum, course) => sum + course.progress, 0)
  const lastCourse = progressRows
    .filter((course) => course.updated_at)
    .sort((first, second) => new Date(second.updated_at) - new Date(first.updated_at))[0] || null
  const quizRows = buildQuizRows(courses, localData.quizResults)

  return {
    completedCourses: progressRows.filter((course) => course.progress >= 100).length,
    globalProgress: Math.round(totalProgress / totalCourses),
    lastChapter: lastCourse?.activeChapter || null,
    lastCourse,
    passedQuizCount: quizRows.filter((quiz) => quiz.score >= PASSING_QUIZ_SCORE).length,
    quizCount: quizRows.length,
    progressRows,
    diagnosticLevel: normalizeLevel(diagnosticResult?.level),
  }
}

function buildRecommendations(courses, localData, diagnosticResult, dashboardData) {
  if (!diagnosticResult) {
    return [{
      icon: BarChart3,
      title: 'Test diagnostique non encore passe',
      subtitle: 'Passez le test pour personnaliser votre parcours',
      action: 'Passer le test',
      path: '/diagnostic',
    }]
  }

  const level = dashboardData.diagnosticLevel
  const progressByCourse = dashboardData.progressRows.reduce((accumulator, course) => ({
    ...accumulator,
    [course.id]: course.progress,
  }), {})
  const quizRows = buildQuizRows(courses, localData.quizResults)
  const weakQuiz = quizRows.find((quiz) => quiz.score < PASSING_QUIZ_SCORE)

  if (weakQuiz) {
    return [{
      icon: CheckCircle2,
      title: `Revoir ${weakQuiz.course.title}`,
      subtitle: `Dernier score quiz : ${weakQuiz.score}%. Reprenez le cours avant de retenter le quiz.`,
      action: 'Revoir',
      path: `/courses/${weakQuiz.course.id}`,
    }]
  }

  const inProgress = courses
    .map((course) => ({ ...course, progress: Number(progressByCourse[course.id] || 0) }))
    .filter((course) => course.progress > 0 && course.progress < 100)
    .sort((first, second) => second.progress - first.progress)

  if (inProgress.length > 0) {
    return inProgress.slice(0, 2).map((course) => ({
      icon: BookOpen,
      title: course.title,
      subtitle: `Continuez le chapitre actif - progression ${course.progress}%.`,
      action: 'Continuer',
      path: `/courses/${course.id}`,
    }))
  }

  const levelCourses = courses.filter((course) => normalizeLevel(course.level) === level)
  const recommendedCourses = levelCourses.length > 0 ? levelCourses : courses

  return recommendedCourses.slice(0, 2).map((course) => ({
    icon: Star,
    title: course.title,
    subtitle: course.summary,
    action: 'Commencer',
    path: `/courses/${course.id}`,
  }))
}

function buildActivities(courses, localData, diagnosticResult) {
  const activities = []

  Object.entries(localData.chapterProgress || {}).forEach(([courseId, progress]) => {
    const course = courses.find((item) => item.id === Number(courseId))
    if (!course || !progress?.updated_at) return
    const activeChapter = getActiveChapter(progress)
    activities.push({
      Icon: BookOpen,
      title: `Cours consulte : ${course.title}`,
      text: activeChapter ? `Chapitre actif : ${activeChapter.title}` : `Progression : ${progress.progress || 0}%`,
      timestamp: progress.updated_at,
    })
  })

  buildQuizRows(courses, localData.quizResults).forEach((quiz) => {
    activities.push({
      Icon: CheckCircle2,
      title: `Quiz ${quiz.score >= PASSING_QUIZ_SCORE ? 'reussi' : 'a revoir'} : ${quiz.course.title}`,
      text: `Score obtenu : ${quiz.score}%`,
      timestamp: quiz.date,
    })
  })

  if (diagnosticResult?.date) {
    activities.push({
      Icon: BarChart3,
      title: 'Test diagnostique complete',
      text: `Niveau obtenu : ${diagnosticResult.level} - Score : ${diagnosticResult.score}%`,
      timestamp: diagnosticResult.date,
    })
  }

  return activities
    .filter((activity) => activity.timestamp)
    .sort((first, second) => new Date(second.timestamp) - new Date(first.timestamp))
    .slice(0, 4)
    .map((activity) => ({
      ...activity,
      day: formatDate(activity.timestamp),
      time: formatTime(activity.timestamp),
    }))
}

function buildQuizRows(courses, quizResults) {
  return Object.entries(quizResults || {})
    .map(([courseId, result]) => {
      const course = courses.find((item) => item.id === Number(courseId))
      if (!course) return null

      return {
        course,
        score: Number(result.score || 0),
        date: result.date,
      }
    })
    .filter(Boolean)
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

function normalizeLevel(level) {
  const normalized = String(level || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

  if (normalized.includes('debut')) return 'debutant'
  if (normalized.includes('avance') || normalized.includes('avanc')) return 'avance'
  return normalized.includes('inter') ? 'intermediaire' : ''
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

function RecommendedItem({ icon: Icon, title, subtitle, action, onClick }) {
  return (
    <div className="recommended-item">
      <span className="soft-icon"><Icon size={34} /></span>
      <div>
        <strong>{title}</strong>
        <p>{subtitle}</p>
      </div>
      <button className="outline-button" onClick={onClick}>{action}</button>
    </div>
  )
}

export default DashboardPage
