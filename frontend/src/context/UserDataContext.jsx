import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../hooks/useAuth.js'
import {
  getDiagnosticResult,
  getNotifications,
  getProgress,
  getQuizResults,
} from '../services/api.js'
import { UserDataContext } from './userDataContext.js'

const DIAGNOSTIC_STORAGE_KEY = 'diagnosticResult'
const CHAPTER_PROGRESS_STORAGE_KEY = 'edumentor:chapterProgress'
const QUIZ_RESULTS_STORAGE_KEY = 'edumentor:quizResults'
const NOTIFICATIONS_STORAGE_KEY = 'edumentor:notifications'

const EMPTY_DATA = {
  diagnosticResult: null,
  notifications: [],
  profile: null,
  progress: {},
  quizResults: {},
}

export function UserDataProvider({ children }) {
  const { authReady, currentUser } = useAuth()
  const requestSequence = useRef(0)
  const [data, setData] = useState(EMPTY_DATA)
  const [loading, setLoading] = useState(false)

  const refreshUserData = useCallback(async () => {
    if (!currentUser) {
      return
    }

    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    setLoading(true)

    const localData = readLocalData()
    setData(localData)

    const [diagnosticResponse, progressResponse, quizResponse, notificationsResponse] = await Promise.allSettled([
      getDiagnosticResult(),
      getProgress(),
      getQuizResults(),
      getNotifications(),
    ])

    if (sequence !== requestSequence.current) {
      return
    }

    const backendData = {
      profile: localData.profile,
      diagnosticResult: diagnosticResponse.status === 'fulfilled'
        ? normalizeBackendDiagnostic(diagnosticResponse.value)
        : localData.diagnosticResult,
      progress: progressResponse.status === 'fulfilled'
        ? normalizeBackendProgress(progressResponse.value)
        : localData.progress,
      quizResults: quizResponse.status === 'fulfilled'
        ? normalizeBackendQuizResults(quizResponse.value)
        : localData.quizResults,
      notifications: notificationsResponse.status === 'fulfilled'
        ? normalizeBackendNotifications(notificationsResponse.value)
        : localData.notifications,
    }

    writeLocalData(backendData)
    setData(backendData)
    setLoading(false)
  }, [currentUser])

  useEffect(() => {
    if (!authReady) {
      return
    }

    if (!currentUser) {
      requestSequence.current += 1
      setData(EMPTY_DATA)
      setLoading(false)
      return
    }

    refreshUserData()
  }, [authReady, currentUser, refreshUserData])

  const value = useMemo(() => ({
    ...data,
    loading,
    refreshUserData,
  }), [data, loading, refreshUserData])

  return (
    <UserDataContext.Provider value={value}>
      {children}
    </UserDataContext.Provider>
  )
}

function readLocalData() {
  return {
    profile: readLocalStorage('edumentor:userProfile', null),
    diagnosticResult: readLocalStorage(DIAGNOSTIC_STORAGE_KEY, null),
    progress: readLocalStorage(CHAPTER_PROGRESS_STORAGE_KEY, {}),
    quizResults: readLocalStorage(QUIZ_RESULTS_STORAGE_KEY, {}),
    notifications: readLocalStorage(NOTIFICATIONS_STORAGE_KEY, []),
  }
}

function writeLocalData(data) {
  if (data.profile) {
    localStorage.setItem('edumentor:userProfile', JSON.stringify(data.profile))
  }
  if (data.diagnosticResult) {
    localStorage.setItem(DIAGNOSTIC_STORAGE_KEY, JSON.stringify(data.diagnosticResult))
  }
  localStorage.setItem(CHAPTER_PROGRESS_STORAGE_KEY, JSON.stringify(data.progress || {}))
  localStorage.setItem(QUIZ_RESULTS_STORAGE_KEY, JSON.stringify(data.quizResults || {}))
  localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(data.notifications || []))
}

function normalizeBackendDiagnostic(result) {
  if (!result) {
    return null
  }

  return {
    score: result.score,
    level: result.level,
    total: result.total,
    correct_count: result.correct_count,
    corrections: result.corrections,
    date: result.created_at || result.date,
  }
}

function normalizeBackendProgress(progressRows) {
  if (!Array.isArray(progressRows)) {
    return {}
  }

  return progressRows.reduce((progressMap, row) => {
    progressMap[row.course_id] = {
      progress: row.progress,
      updated_at: row.updated_at,
      chapters: Array.isArray(row.chapters) ? row.chapters : [],
    }
    return progressMap
  }, {})
}

function normalizeBackendQuizResults(results) {
  if (!Array.isArray(results)) {
    return {}
  }

  return results
    .sort((first, second) => new Date(second.created_at || 0) - new Date(first.created_at || 0))
    .reduce((resultMap, result) => {
      if (resultMap[result.course_id]) {
        return resultMap
      }

      resultMap[result.course_id] = {
        score: result.score,
        correct: result.correct,
        total: result.total,
        answers: result.answers,
        corrections: result.corrections,
        recommendation: result.recommendation,
        date: result.created_at,
      }
      return resultMap
    }, {})
}

function normalizeBackendNotifications(notifications) {
  if (!Array.isArray(notifications)) {
    return []
  }

  return notifications
    .map((notification) => ({
      id: notification.id,
      type: notification.type,
      title: notification.title,
      message: notification.message,
      date: notification.created_at || notification.date || new Date().toISOString(),
      read: notification.read === true,
    }))
    .sort((first, second) => new Date(second.date) - new Date(first.date))
}

function readLocalStorage(key, fallback) {
  try {
    const storedValue = localStorage.getItem(key)
    return storedValue ? JSON.parse(storedValue) : fallback
  } catch {
    return fallback
  }
}
