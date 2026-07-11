import { onAuthStateChanged } from 'firebase/auth'
import { auth } from './firebase.js'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8135'

const inflightProtectedGets = new Map()

let initialAuthResolved = false
const initialAuthPromise = new Promise((resolve) => {
  const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
    initialAuthResolved = true
    unsubscribe()
    resolve(firebaseUser)
  })
})

export async function publicRequest(path, options = {}) {
  return sendRequest(path, options)
}

export async function authenticatedRequest(path, options = {}) {
  await waitForInitialAuth()

  if (!auth.currentUser) {
    throw createApiError(401, 'Utilisateur non connecté')
  }

  const method = (options.method || 'GET').toUpperCase()
  const cacheKey = method === 'GET' ? `${method}:${path}` : ''

  if (cacheKey && inflightProtectedGets.has(cacheKey)) {
    return inflightProtectedGets.get(cacheKey)
  }

  const promise = sendAuthenticatedRequest(path, options)
    .finally(() => {
      if (cacheKey) {
        inflightProtectedGets.delete(cacheKey)
      }
    })

  if (cacheKey) {
    inflightProtectedGets.set(cacheKey, promise)
  }

  return promise
}

async function waitForInitialAuth() {
  if (initialAuthResolved) {
    return auth.currentUser
  }

  return initialAuthPromise
}

async function sendAuthenticatedRequest(path, options = {}) {
  const token = await getFirebaseToken(false)
  let response = await sendRequest(path, options, token)

  if (response.status === 401) {
    const freshToken = await getFirebaseToken(true)
    response = await sendRequest(path, options, freshToken)
  }

  return parseResponse(response)
}

async function sendRequest(path, options = {}, token = '') {
  const headers = new Headers(options.headers || {})

  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  return fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  })
}

async function parseResponse(response) {
  if (!response.ok) {
    let detail = `API request failed: ${response.status}`
    try {
      const body = await response.json()
      detail = body?.detail || detail
    } catch {
      // Keep the generic message when the body is not JSON.
    }
    throw createApiError(response.status, detail)
  }

  if (response.status === 204) {
    return null
  }

  return response.json()
}

async function getFirebaseToken(forceRefresh) {
  const firebaseUser = auth.currentUser
  if (!firebaseUser) {
    throw createApiError(401, 'Utilisateur non connecté')
  }

  return firebaseUser.getIdToken(forceRefresh)
}

function createApiError(status, message) {
  const error = new Error(message)
  error.status = status
  return error
}

export function fetchCourses() {
  return publicRequest('/api/courses').then(parseResponse)
}

export function fetchCourseById(courseId) {
  return publicRequest(`/api/courses/${courseId}`).then(parseResponse)
}

export function fetchDashboard() {
  return publicRequest('/api/dashboard').then(parseResponse)
}

export function fetchDiagnosticQuestions() {
  return publicRequest('/api/diagnostic/questions').then(parseResponse)
}

export function submitDiagnosticAnswers(answers) {
  return publicRequest('/api/diagnostic/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answers }),
  }).then(parseResponse)
}

export function getUserProfile() {
  return authenticatedRequest('/api/profile')
}

export function updateUserProfile(data) {
  return authenticatedRequest('/api/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getDiagnosticResult() {
  return authenticatedRequest('/api/diagnostic/result')
}

export function saveDiagnosticResult(data) {
  return authenticatedRequest('/api/diagnostic/result', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getProgress() {
  return authenticatedRequest('/api/progress')
}

export function saveProgress(data) {
  return authenticatedRequest('/api/progress', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateCourseProgress(courseId, data) {
  return authenticatedRequest(`/api/progress/${courseId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function fetchQuiz(courseId) {
  return publicRequest(`/api/quiz/${courseId}`).then(parseResponse)
}

export function submitQuiz(courseId, answers) {
  return publicRequest(`/api/quiz/${courseId}/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answers }),
  }).then(parseResponse)
}

export function getQuizResults() {
  return authenticatedRequest('/api/quiz-results')
}

export function saveQuizResult(data) {
  return authenticatedRequest('/api/quiz-results', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getNotifications() {
  return authenticatedRequest('/api/notifications')
}

export function createNotification(data) {
  return authenticatedRequest('/api/notifications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function markNotificationRead(id) {
  return authenticatedRequest(`/api/notifications/${id}/read`, {
    method: 'PUT',
  })
}

export function deleteNotification(id) {
  return authenticatedRequest(`/api/notifications/${id}`, {
    method: 'DELETE',
  })
}

export function sendChatMessage(message, level, context = []) {
  return publicRequest('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, level, context }),
  }).then(parseResponse)
}

export function fetchAdminOverview() {
  return authenticatedRequest('/api/admin/stats/overview')
}

export function fetchAdminUsersStats() {
  return authenticatedRequest('/api/admin/stats/users')
}

export function fetchAdminCoursesStats() {
  return authenticatedRequest('/api/admin/stats/courses')
}

export function fetchAdminQuizzesStats() {
  return authenticatedRequest('/api/admin/stats/quizzes')
}

export function fetchAdminChatbotStats() {
  return authenticatedRequest('/api/admin/stats/chatbot')
}

export function fetchAdminRagStatus() {
  return authenticatedRequest('/api/admin/rag/status')
}

export function reindexAdminRag() {
  return authenticatedRequest('/api/admin/rag/reindex', {
    method: 'POST',
  })
}

export function fetchAdminAuditLogs(params = {}) {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.set(key, value)
    }
  })
  const query = searchParams.toString()
  return authenticatedRequest(`/api/admin/audit-logs${query ? `?${query}` : ''}`)
}

export function fetchAdminUsers() {
  return authenticatedRequest('/api/admin/users')
}

export function fetchAdminUser(userId) {
  return authenticatedRequest(`/api/admin/users/${userId}`)
}

export function updateAdminUserRole(userId, role) {
  return authenticatedRequest(`/api/admin/users/${userId}/role`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
}

export function updateAdminUserStatus(userId, status) {
  return authenticatedRequest(`/api/admin/users/${userId}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
}

export function deleteAdminUser(userId) {
  return authenticatedRequest(`/api/admin/users/${userId}`, {
    method: 'DELETE',
  })
}

export function fetchAdminCourses() {
  return authenticatedRequest('/api/admin/courses')
}

export function fetchAdminCourse(courseId) {
  return authenticatedRequest(`/api/admin/courses/${courseId}`)
}

export function createAdminCourse(data) {
  return authenticatedRequest('/api/admin/courses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateAdminCourse(courseId, data) {
  return authenticatedRequest(`/api/admin/courses/${courseId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteAdminCourse(courseId) {
  return authenticatedRequest(`/api/admin/courses/${courseId}`, {
    method: 'DELETE',
  })
}

export function uploadAdminCoursePdf(courseId, file, replace = false) {
  const body = new FormData()
  body.append('file', file)
  return authenticatedRequest(`/api/admin/courses/${courseId}/pdf`, {
    method: replace ? 'PUT' : 'POST',
    body,
  })
}

export function deleteAdminCoursePdf(courseId) {
  return authenticatedRequest(`/api/admin/courses/${courseId}/pdf`, {
    method: 'DELETE',
  })
}
