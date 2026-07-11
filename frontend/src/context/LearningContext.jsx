import { useEffect, useMemo, useState } from 'react'
import { useLocalStorageState } from '../hooks/useLocalStorageState.js'
import {
  fetchCourses,
  saveQuizResult as saveBackendQuizResult,
  sendChatMessage,
} from '../services/api.js'
import { courses as fallbackCourses, diagnosticQuestions, learner, quizQuestions, recommendations } from '../services/mockData.js'
import { addNotification } from '../services/notifications.js'
import { LearningContext } from './learningContext.js'

export function LearningProvider({ children }) {
  const [courses, setCourses] = useState(fallbackCourses)
  const [diagnosticAnswers, setDiagnosticAnswers] = useLocalStorageState('edumentor:diagnosticAnswers', {})
  const [diagnosticLevel, setDiagnosticLevel] = useLocalStorageState('edumentor:diagnosticLevel', 'Intermediaire')
  const [quizAnswers, setQuizAnswers] = useLocalStorageState('edumentor:quizAnswers', {})
  const [quizResults, setQuizResults] = useLocalStorageState('edumentor:quizResults', {})
  const [courseProgress, setCourseProgress] = useLocalStorageState('edumentor:courseProgress', {})
  const [messages, setMessages] = useLocalStorageState('edumentor:messages', [
    {
      role: 'assistant',
      text: 'Bonjour ! Je suis EduMentor AI. Pose-moi une question sur ton cours ou demande un exercice adapte.',
      sources: [],
    },
  ])

  useEffect(() => {
    setMessages((current) => current.filter((message) => !isLegacySimulatedMessage(message)))
  }, [setMessages])

  useEffect(() => {
    let isMounted = true

    fetchCourses()
      .then((data) => {
        if (isMounted && Array.isArray(data) && data.length > 0) {
          setCourses(data)
        }
      })
      .catch(() => {
        if (isMounted) {
          setCourses(fallbackCourses)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  const quizScore = useMemo(() => {
    const correct = quizQuestions.filter((item, index) => quizAnswers[index] === item.answer).length
    return Math.round((correct / quizQuestions.length) * 100)
  }, [quizAnswers])

  const coursesWithProgress = useMemo(
    () => courses.map((course) => ({
      ...course,
      progress: courseProgress[course.id] ?? course.progress,
    })),
    [courseProgress, courses],
  )

  const averageProgress = useMemo(
    () => Math.round(coursesWithProgress.reduce((sum, course) => sum + course.progress, 0) / coursesWithProgress.length),
    [coursesWithProgress],
  )

  function calculateDiagnostic() {
    const advancedSignals = Object.values(diagnosticAnswers).filter((answer) =>
      ['Un cas reel complexe', 'Des projets autonomes'].includes(answer),
    ).length
    const beginnerSignals = Object.values(diagnosticAnswers).filter((answer) =>
      ['Une definition simple', 'Des bases pas a pas'].includes(answer),
    ).length

    if (advancedSignals >= 2) setDiagnosticLevel('Avance')
    else if (beginnerSignals >= 2) setDiagnosticLevel('Debutant')
    else setDiagnosticLevel('Intermediaire')
  }

  async function sendMessage(message, learnerLevel = diagnosticLevel) {
    if (!message.trim()) return

    const isFirstChatUse = !messages.some((item) => item.role === 'user')
    const userMessage = {
      role: 'user',
      text: message.trim(),
      time: new Date().toISOString(),
    }

    setMessages((current) => [...current, userMessage])

    try {
      const data = await sendChatMessage(message.trim(), learnerLevel)
      const assistantMessage = {
        role: 'assistant',
        text: data.answer,
        mode: data.mode,
        sources: data.sources || [],
        time: new Date().toISOString(),
      }

      setMessages((current) => [...current, assistantMessage])
      if (isFirstChatUse) {
        addNotification({
          type: 'chatbot',
          title: 'Première utilisation du chatbot',
          message: 'Votre assistant IA est maintenant prêt à vous accompagner.',
        })
      }
      addNotification({
        type: 'chatbot',
        title: 'Nouvelle réponse pédagogique générée',
        message: 'Le chatbot a généré une réponse adaptée à votre niveau.',
      })
    } catch {
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          text: "Impossible de contacter le service RAG pour le moment.",
          mode: 'error',
          sources: [],
          time: new Date().toISOString(),
        },
      ])
    }
  }

  function saveQuizResult(courseId, result) {
    const numericCourseId = Number(courseId)
    const nextProgress = Math.max(courseProgress[numericCourseId] ?? 0, result.score >= 60 ? 100 : 75)
    const course = courses.find((item) => item.id === numericCourseId)
    const courseTitle = course?.title || `cours ${numericCourseId}`
    const savedResult = {
      ...result,
      date: new Date().toISOString(),
    }

    setQuizResults((current) => ({
      ...current,
      [numericCourseId]: savedResult,
    }))
    saveBackendQuizResult({
      course_id: numericCourseId,
      score: result.score,
      correct: result.correct,
      total: result.total,
      answers: result.answers,
      corrections: result.corrections,
      recommendation: result.recommendation,
    }).catch(() => {})

    setCourseProgress((current) => ({
      ...current,
      [numericCourseId]: nextProgress,
    }))

    addNotification({
      type: 'quiz',
      title: 'Quiz terminé',
      message: `Vous avez terminé le quiz du cours ${courseTitle}.`,
    })
    addNotification({
      type: 'quiz',
      title: 'Nouveau score obtenu',
      message: `Votre score est de ${result.score}% pour ${courseTitle}.`,
    })
    if (result.score >= 60) {
      addNotification({
        type: 'quiz',
        title: 'Quiz réussi',
        message: `Bravo, vous avez validé le quiz du cours ${courseTitle}.`,
      })
    }
  }

  const value = {
    averageProgress,
    calculateDiagnostic,
    courses: coursesWithProgress,
    courseProgress,
    diagnosticAnswers,
    diagnosticLevel,
    diagnosticQuestions,
    learner,
    messages,
    quizAnswers,
    quizQuestions,
    quizResults,
    quizScore,
    recommendations,
    saveQuizResult,
    sendMessage,
    setCourseProgress,
    setDiagnosticAnswers,
    setQuizAnswers,
  }

  return <LearningContext.Provider value={value}>{children}</LearningContext.Provider>
}

function isLegacySimulatedMessage(message) {
  if (message.role !== 'assistant') return false

  const text = String(message.text || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

  return (
    text.includes('simulee') ||
    text.includes('niveau utilisé :') ||
    text.includes('niveau utilis') ||
    text.includes('je te conseille de commencer par un exemple concret')
  )
}
