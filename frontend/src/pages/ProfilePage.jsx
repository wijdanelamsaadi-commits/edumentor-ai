import { useEffect, useMemo, useState } from 'react'
import { BarChart3, BookOpen, Calendar, CheckCircle2, ClipboardList, Flame, Lock, Mail, PenLine, Star, Target, Trophy } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import avatarUrl from '../assets/learner-avatar.jpg'
import { useLearning } from '../hooks/useLearning.js'

function ProfilePage() {
  const navigate = useNavigate()
  const { courses, learner } = useLearning()
  const [localData, setLocalData] = useState({
    diagnosticResult: null,
    quizResults: {},
    courseProgress: {},
  })

  useEffect(() => {
    setLocalData({
      diagnosticResult: readLocalStorage('diagnosticResult', null),
      quizResults: readLocalStorage('edumentor:quizResults', readLocalStorage('quizResults', {})),
      courseProgress: readLocalStorage('edumentor:courseProgress', readLocalStorage('courseProgress', {})),
    })
  }, [])

  const courseStats = useMemo(
    () => buildCourseStats(courses, localData.courseProgress),
    [courses, localData.courseProgress],
  )
  const quizRows = useMemo(
    () => buildQuizRows(courses, localData.quizResults),
    [courses, localData.quizResults],
  )
  const activities = useMemo(
    () => buildActivities(courses, localData),
    [courses, localData],
  )

  const hasData = Boolean(localData.diagnosticResult) || quizRows.length > 0 || courseStats.hasProgress
  const diagnosticScore = Number.isFinite(localData.diagnosticResult?.score) ? `${localData.diagnosticResult.score}%` : '--'
  const currentLevel = localData.diagnosticResult?.level || 'Non défini'

  const badges = [
    [Star, 'Premier pas', courseStats.completedCourses >= 1 ? 'Débloqué' : 'Terminer 1 cours'],
    [BookOpen, 'Apprenant régulier', courseStats.completedCourses >= 5 ? 'Débloqué' : 'Terminer 5 cours'],
    [Target, 'Quiz Master', quizRows.filter((quiz) => quiz.score >= 80).length >= 3 ? 'Débloqué' : 'Obtenir 80%+ dans 3 quiz'],
    [Flame, 'Persévérant', courseStats.inProgressCourses >= 3 ? 'Débloqué' : 'Apprendre 10h au total'],
    [Trophy, 'Excellent', quizRows.filter((quiz) => quiz.score >= 90).length >= 5 ? 'Débloqué' : 'Obtenir 90%+ dans 5 quiz'],
    [Lock, 'Expert IA', `Terminer 20 cours ${courseStats.completedCourses} / 20`],
  ]

  return (
    <section className="page-section profile-page">
      <div className="page-heading">
        <h1>Profil & Progression</h1>
        <p>Gérez votre profil et suivez vos performances.</p>
      </div>

      {!hasData && (
        <article className="progress-banner">
          <span><BarChart3 size={30} /></span>
          <div>
            <strong>Aucune donnée de progression disponible</strong>
            <p>Passez le test diagnostique ou terminez un quiz pour alimenter votre profil.</p>
          </div>
          <button className="outline-button" onClick={() => navigate('/diagnostic')} type="button">Passer le test</button>
        </article>
      )}

      <article className="panel-card profile-hero">
        <h2>Profil</h2>
        <div className="profile-info">
          <img src={avatarUrl} alt="" />
          <div>
            <h2>{learner.name}</h2>
            <p>Apprenante en IA</p>
            <span><Mail size={18} />{learner.email}</span>
            <span><Calendar size={18} />Membre depuis mai 2024</span>
            <button className="outline-button" type="button"><PenLine size={18} />Modifier mon profil</button>
          </div>
        </div>
      </article>

      <div className="dashboard-stats">
        <article className="metric-card metric-wide">
          <span className="soft-icon"><BarChart3 size={42} /></span>
          <div>
            <p>Niveau actuel</p>
            <h2>{currentLevel}</h2>
            <strong>{localData.diagnosticResult ? 'Niveau obtenu au dernier test' : 'Test diagnostique non encore passé'}</strong>
          </div>
        </article>
        <article className="metric-card">
          <p>Score diagnostique</p>
          <h2>{diagnosticScore}</h2>
          <div className="progress-track"><span style={{ width: `${localData.diagnosticResult?.score || 0}%` }} /></div>
          <strong>{localData.diagnosticResult ? formatDate(localData.diagnosticResult.date) : 'Aucune donnée'}</strong>
        </article>
        <article className="metric-card">
          <p>Progression globale</p>
          <h2>{courseStats.globalProgress}%</h2>
          <div className="progress-track"><span style={{ width: `${courseStats.globalProgress}%` }} /></div>
          <strong>{courseStats.completedCourses} cours terminés</strong>
        </article>
      </div>

      <div className="dashboard-stats">
        <article className="metric-card">
          <p>Cours terminés</p>
          <h2>{courseStats.completedCourses}</h2>
          <strong>{courseStats.completedCourses > 0 ? 'Progression validée' : 'Aucun cours terminé'}</strong>
        </article>
        <article className="metric-card">
          <p>Cours en cours</p>
          <h2>{courseStats.inProgressCourses}</h2>
          <strong>{courseStats.inProgressCourses > 0 ? 'À continuer' : 'Aucun cours en cours'}</strong>
        </article>
        <article className="metric-card">
          <p>Quiz réalisés</p>
          <h2>{quizRows.length}</h2>
          <strong>{quizRows.length > 0 ? 'Scores sauvegardés' : 'Aucun score enregistré'}</strong>
        </article>
      </div>

      <div className="dashboard-grid">
        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Scores des quiz par cours</h2>
            <button type="button">Voir tout →</button>
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
            <EmptyLine title="Aucun quiz terminé" text="Commencez un quiz depuis le détail d'un cours." />
          )}
        </article>

        <article className="panel-card history-panel">
          <div className="panel-title">
            <h2>Historique des activités</h2>
            <button type="button">Voir tout →</button>
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
            <EmptyLine title="Aucune activité récente" text="Votre historique apparaîtra ici après un test ou un quiz." />
          )}
        </article>
      </div>

      <article className="panel-card badges-panel">
        <div className="panel-title">
          <div>
            <h2>Badges</h2>
            <p>Débloquez des badges en atteignant vos objectifs et en restant régulier dans votre apprentissage.</p>
          </div>
          <button type="button">Voir tous les badges →</button>
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

function readLocalStorage(key, fallback) {
  try {
    const storedValue = localStorage.getItem(key)
    return storedValue ? JSON.parse(storedValue) : fallback
  } catch {
    return fallback
  }
}

function buildCourseStats(courses, courseProgress) {
  const progressValues = courses.map((course) => Number(courseProgress[course.id] ?? 0))
  const completedCourses = progressValues.filter((progress) => progress >= 100).length
  const inProgressCourses = progressValues.filter((progress) => progress > 0 && progress < 100).length
  const globalProgress = progressValues.length
    ? Math.round(progressValues.reduce((sum, progress) => sum + progress, 0) / progressValues.length)
    : 0

  return {
    completedCourses,
    globalProgress,
    hasProgress: progressValues.some((progress) => progress > 0),
    inProgressCourses,
  }
}

function buildQuizRows(courses, quizResults) {
  return Object.entries(quizResults || {})
    .map(([courseId, result]) => {
      const course = courses.find((item) => item.id === Number(courseId))

      return {
        courseId,
        correct: result.correct ?? 0,
        date: result.date,
        score: result.score ?? 0,
        title: course?.title || `Cours ${courseId}`,
        total: result.total ?? 10,
      }
    })
    .sort((first, second) => new Date(second.date || 0) - new Date(first.date || 0))
}

function buildActivities(courses, localData) {
  const activities = []

  if (localData.diagnosticResult) {
    activities.push({
      Icon: BarChart3,
      date: localData.diagnosticResult.date,
      text: `Niveau obtenu : ${localData.diagnosticResult.level} - Score : ${localData.diagnosticResult.score}%`,
      title: 'Test diagnostique complété',
    })
  }

  buildQuizRows(courses, localData.quizResults).forEach((quiz) => {
    activities.push({
      Icon: ClipboardList,
      date: quiz.date,
      text: `Score obtenu : ${quiz.score}%`,
      title: `Quiz terminé : ${quiz.title}`,
    })
  })

  Object.entries(localData.courseProgress || {}).forEach(([courseId, progress]) => {
    const numericProgress = Number(progress)
    if (numericProgress <= 0) return

    const course = courses.find((item) => item.id === Number(courseId))
    activities.push({
      Icon: numericProgress >= 100 ? CheckCircle2 : BookOpen,
      date: new Date().toISOString(),
      text: `Progression : ${numericProgress}%`,
      title: `${numericProgress >= 100 ? 'Cours terminé' : 'Cours en cours'} : ${course?.title || `Cours ${courseId}`}`,
    })
  })

  return activities
    .sort((first, second) => new Date(second.date || 0) - new Date(first.date || 0))
    .slice(0, 6)
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
