import { onAuthStateChanged } from 'firebase/auth'
import { auth } from './firebase.js'

export const API_BASE_URL = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8135'

const inflightProtectedGets = new Map()

let initialAuthResolved = false
const initialAuthPromise = createInitialAuthPromise()

function createInitialAuthPromise() {
  if (typeof auth.authStateReady === 'function') {
    return auth.authStateReady().then(() => {
      initialAuthResolved = true
      return auth.currentUser
    })
  }

  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      initialAuthResolved = true
      unsubscribe()
      resolve(firebaseUser)
    })
  })
}

onAuthStateChanged(auth, (firebaseUser) => {
  if (!firebaseUser) {
    inflightProtectedGets.clear()
  }
})

export async function waitForAuthReady() {
  if (initialAuthResolved) {
    return auth.currentUser
  }
  return initialAuthPromise
}

export function getCurrentFirebaseUser() {
  return auth.currentUser
}

export async function getCurrentFirebaseToken(forceRefresh = false) {
  await waitForAuthReady()
  const firebaseUser = auth.currentUser
  if (!firebaseUser) {
    throw createApiError(401, 'Utilisateur non connecté')
  }
  return firebaseUser.getIdToken(forceRefresh)
}

export async function publicRequest(path, options = {}) {
  return sendRequest(path, options)
}

export async function authenticatedRequest(path, options = {}) {
  await waitForAuthReady()

  if (!auth.currentUser) {
    throw createApiError(401, 'Utilisateur non connecté')
  }

  const method = (options.method || 'GET').toUpperCase()
  const cacheKey = method === 'GET' ? `${auth.currentUser.uid}:${method}:${path}` : ''

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

async function optionalAuthenticatedRequest(path, options = {}) {
  await waitForAuthReady()
  if (!auth.currentUser) {
    return publicRequest(path, options).then(parseResponse)
  }
  return authenticatedRequest(path, options)
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
  return getCurrentFirebaseToken(forceRefresh)
}

function createApiError(status, message) {
  const error = new Error(formatApiErrorMessage(message))
  error.status = status
  error.detail = message
  return error
}

function formatApiErrorMessage(message) {
  if (typeof message === 'string') return message
  if (typeof message === 'number') return String(message)
  if (Array.isArray(message)) {
    return message
      .map((item) => {
        if (item && typeof item === 'object') {
          const location = Array.isArray(item.loc) ? item.loc.join('.') : ''
          return location ? `${location} : ${item.msg || 'champ invalide'}` : item.msg || JSON.stringify(item)
        }
        return String(item)
      })
      .join('\n')
  }
  if (message && typeof message === 'object') {
    if (typeof message.message === 'string') return message.message
    if (message.detail !== undefined) return formatApiErrorMessage(message.detail)
    return JSON.stringify(message)
  }
  return ''
}

export function fetchSubjects() {
  return publicRequest('/api/subjects').then(parseResponse)
}

export function fetchEducationLevels() {
  return publicRequest('/api/education-levels').then(parseResponse)
}

export function fetchDifficultyLevels() {
  return publicRequest('/api/difficulty-levels').then(parseResponse)
}

export function fetchCourses(params = {}) {
  const query = buildQuery(params)
  return optionalAuthenticatedRequest(`/api/courses${query}`)
}

export function fetchCourseById(courseId) {
  return optionalAuthenticatedRequest(`/api/courses/${courseId}`)
}

export function testOllamaVariantPreview() {
  return publicRequest('/api/ai/test-ollama-variant', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      course_id: 23,
      chapter_id: 197,
      level: 'debutant',
    }),
  }).then(parseResponse)
}

export function fetchDashboard() {
  return publicRequest('/api/dashboard').then(parseResponse)
}

export function fetchDiagnosticQuestions(params = {}) {
  const query = buildQuery(params)
  return optionalAuthenticatedRequest(`/api/diagnostic/questions${query}`)
}

export function fetchDiagnosticAvailability(params = {}) {
  const query = buildQuery(params)
  return optionalAuthenticatedRequest(`/api/diagnostic/availability${query}`)
}

export function submitDiagnosticAnswers(payload) {
  return authenticatedRequest('/api/diagnostic/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
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

export function getDiagnosticResult(subjectId = null) {
  const query = subjectId ? `?subject_id=${encodeURIComponent(subjectId)}` : ''
  return authenticatedRequest(`/api/diagnostic/result${query}`)
}

export function getDiagnosticResults() {
  return authenticatedRequest('/api/diagnostic/results')
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

export function sendChatMessage(message, level, context = [], options = {}) {
  return publicRequest('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, level, context, ...options }),
  }).then(parseResponse)
}

export function fetchRagStatus() {
  return publicRequest('/api/rag/status').then(parseResponse)
}

export function fetchCourseRagStatus(courseId) {
  return publicRequest(`/api/rag/courses/${courseId}/status`).then(parseResponse)
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

export function fetchAdminRagDocuments(params = {}) {
  const query = buildQuery(params)
  return authenticatedRequest(`/api/admin/rag/documents${query}`)
}

export function fetchAdminRagJobs() {
  return authenticatedRequest('/api/admin/rag/jobs')
}

export function indexAdminRagDocument(documentId) {
  return authenticatedRequest(`/api/admin/rag/documents/${documentId}/index`, { method: 'POST' })
}

export function reindexAdminRagDocument(documentId) {
  return authenticatedRequest(`/api/admin/rag/documents/${documentId}/reindex`, { method: 'POST' })
}

export function deleteAdminRagDocumentIndex(documentId) {
  return authenticatedRequest(`/api/admin/rag/documents/${documentId}/index`, { method: 'DELETE' })
}

export function reindexAdminRagCourse(courseId) {
  return authenticatedRequest(`/api/admin/rag/courses/${courseId}/reindex`, { method: 'POST' })
}

export function reindexAdminRagSubject(subjectId) {
  return authenticatedRequest(`/api/admin/rag/subjects/${subjectId}/reindex`, { method: 'POST' })
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

export function assignAdminCourseProfessor(courseId, professorId) {
  return authenticatedRequest(`/api/admin/courses/${courseId}/professor`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ professor_id: professorId || null }),
  })
}

export function fetchProfessorDashboard() {
  return authenticatedRequest('/api/professor/dashboard')
}

export const getProfessorDashboard = fetchProfessorDashboard

export function getProfessorCourses(params = {}) {
  const query = buildQuery(params)
  return authenticatedRequest(`/api/professor/courses${query}`)
}

export function createProfessorCourse(data) {
  const payload = { ...data }
  delete payload.professor_id
  return authenticatedRequest('/api/professor/courses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getProfessorCourse(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}`)
}

export function updateProfessorCourse(courseId, data) {
  const payload = { ...data }
  delete payload.professor_id
  return authenticatedRequest(`/api/professor/courses/${courseId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function publishProfessorCourse(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/publish`, { method: 'POST' })
}

export function unpublishProfessorCourse(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/unpublish`, { method: 'POST' })
}

export function archiveProfessorCourse(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/archive`, { method: 'POST' })
}

export function deleteProfessorCourse(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}`, { method: 'DELETE' })
}

export function uploadProfessorCoursePdf(courseId, file) {
  const body = new FormData()
  body.append('file', file)
  return authenticatedRequest(`/api/professor/courses/${courseId}/document`, {
    method: 'POST',
    body,
  })
}

export function deleteProfessorCoursePdf(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/document`, { method: 'DELETE' })
}

export function getProfessorChapters(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/chapters`)
}

export function createProfessorChapter(courseId, data) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/chapters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateProfessorChapter(courseId, chapterId, data) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/chapters/${chapterId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteProfessorChapter(courseId, chapterId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/chapters/${chapterId}`, { method: 'DELETE' })
}

export function reorderProfessorChapters(courseId, chapterIds) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/chapters/reorder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chapter_ids: chapterIds }),
  })
}

export function replaceProfessorObjectives(courseId, items) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/objectives`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
}

export function replaceProfessorSkills(courseId, items) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/skills`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
}

export function replaceProfessorExamples(courseId, items) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/examples`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
}

export function getProfessorQuizzes(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/quizzes`)
}

export function createProfessorQuiz(courseId, data) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/quizzes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getProfessorQuiz(quizId) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}`)
}

export function updateProfessorQuiz(quizId, data) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteProfessorQuiz(quizId) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}`, { method: 'DELETE' })
}

export function createProfessorQuizQuestion(quizId, data) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}/questions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateProfessorQuizQuestion(quizId, questionId, data) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}/questions/${questionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteProfessorQuizQuestion(quizId, questionId) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}/questions/${questionId}`, { method: 'DELETE' })
}

export function manageProfessorQuizQuestions(quizId, questionIds) {
  return authenticatedRequest(`/api/professor/quizzes/${quizId}/questions/reorder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question_ids: questionIds }),
  })
}

export function getProfessorCourseStudents(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/students`)
}

export function getProfessorCourseAnalytics(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/analytics`)
}

export function getProfessorAnalytics() {
  return authenticatedRequest('/api/professor/analytics')
}

export function getProfessorStudyPaths(params = {}) {
  const query = buildQuery(params)
  return authenticatedRequest(`/api/professor/study-paths${query}`)
}

export function getProfessorStudyPath(pathId) {
  return authenticatedRequest(`/api/professor/study-paths/${pathId}`)
}

export function updateProfessorStudyPathItem(pathId, itemId, data) {
  return authenticatedRequest(`/api/professor/study-paths/${pathId}/items/${itemId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getProfessorClassrooms() {
  return authenticatedRequest('/api/professor/classrooms')
}

export function createProfessorClassroom(data) {
  return authenticatedRequest('/api/professor/classrooms', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getProfessorClassroom(classroomId) {
  return authenticatedRequest(`/api/professor/classrooms/${classroomId}`)
}

export function updateProfessorClassroom(classroomId, data) {
  return authenticatedRequest(`/api/professor/classrooms/${classroomId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function addProfessorClassroomStudent(classroomId, data) {
  return authenticatedRequest(`/api/professor/classrooms/${classroomId}/students`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function removeProfessorClassroomStudent(classroomId, studentId) {
  return authenticatedRequest(`/api/professor/classrooms/${classroomId}/students/${studentId}`, {
    method: 'DELETE',
  })
}

export function getStudentClassrooms() {
  return authenticatedRequest('/api/student/classrooms')
}

export function getStudentAdaptiveDashboard() {
  return authenticatedRequest('/api/student/dashboard')
}

export function getStudyPaths() {
  return authenticatedRequest('/api/study-paths')
}

export function getStudyPath(pathId) {
  return authenticatedRequest(`/api/study-paths/${pathId}`)
}

export function startStudyPathItem(pathId, itemId) {
  return authenticatedRequest(`/api/study-paths/${pathId}/items/${itemId}/start`, { method: 'POST' })
}

export function completeStudyPathItem(pathId, itemId) {
  return authenticatedRequest(`/api/study-paths/${pathId}/items/${itemId}/complete`, { method: 'POST' })
}

export function skipStudyPathItem(pathId, itemId) {
  return authenticatedRequest(`/api/study-paths/${pathId}/items/${itemId}/skip`, { method: 'POST' })
}

export function refreshStudyPath(pathId) {
  return authenticatedRequest(`/api/study-paths/${pathId}/refresh`, { method: 'POST' })
}

export function getProfessorAssessments() {
  return authenticatedRequest('/api/professor/assessments')
}

export function createProfessorAssessment(data) {
  return authenticatedRequest('/api/professor/assessments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getProfessorAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}`)
}

export function updateProfessorAssessment(assessmentId, data) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteProfessorAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}`, { method: 'DELETE' })
}

export function publishProfessorAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}/publish`, { method: 'POST' })
}

export function closeProfessorAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}/close`, { method: 'POST' })
}

export function proposeProfessorAssessmentQuestions(assessmentId, data) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}/propose-questions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getProfessorAssessmentResults(assessmentId) {
  return authenticatedRequest(`/api/professor/assessments/${assessmentId}/results`)
}

export function getStudentAssessments() {
  return authenticatedRequest('/api/assessments')
}

export function getStudentAssessment(assessmentId) {
  return authenticatedRequest(`/api/assessments/${assessmentId}`)
}

export function submitStudentAssessment(assessmentId, data) {
  return authenticatedRequest(`/api/assessments/${assessmentId}/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getAssessmentResult(attemptId) {
  return authenticatedRequest(`/api/assessment-results/${attemptId}`)
}

export function getDetailedAssessmentResult(attemptId) {
  return authenticatedRequest(`/api/assessment-results/${attemptId}/detailed`)
}

export function getRemediationPlan(planId) {
  return authenticatedRequest(`/api/remediation/${planId}`)
}

export function getRemediationPlans() {
  return authenticatedRequest('/api/remediation')
}

export function completeRemediationItem(planId, itemId) {
  return authenticatedRequest(`/api/remediation/${planId}/items/${itemId}/complete`, { method: 'PUT' })
}

export function generateRemediationLessons(planId, data = {}) {
  return authenticatedRequest(`/api/remediation/${planId}/lessons/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getRemediationLessons(planId) {
  return authenticatedRequest(`/api/remediation/${planId}/lessons`)
}

export function getPersonalizedLesson(lessonId) {
  return authenticatedRequest(`/api/personalized-lessons/${lessonId}`)
}

export function completePersonalizedLesson(lessonId) {
  return authenticatedRequest(`/api/personalized-lessons/${lessonId}/complete`, { method: 'PUT' })
}

export function submitPersonalizedLessonKnowledgeCheck(lessonId, answer) {
  return authenticatedRequest(`/api/personalized-lessons/${lessonId}/knowledge-check/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer }),
  })
}

export function createPersonalizedAssessment(planId, data = {}) {
  return authenticatedRequest(`/api/remediation/${planId}/personalized-assessment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function compareAssessmentResults(initialAttemptId, personalizedAttemptId) {
  return authenticatedRequest(`/api/assessment-results/compare/${initialAttemptId}/${personalizedAttemptId}`)
}

export function compareRemediationPlan(planId) {
  return authenticatedRequest(`/api/remediation/${planId}/comparison`)
}

export function compareRemediationPlanDetailed(planId) {
  return authenticatedRequest(`/api/remediation/${planId}/comparison/detailed`)
}

export function getProfessorPersonalizedAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/personalized-assessments/${assessmentId}`)
}

export function addProfessorPersonalizedAssessmentQuestion(assessmentId, data) {
  return authenticatedRequest(`/api/professor/personalized-assessments/${assessmentId}/questions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateProfessorPersonalizedAssessmentQuestion(assessmentId, questionId, data) {
  return authenticatedRequest(`/api/professor/personalized-assessments/${assessmentId}/questions/${questionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteProfessorPersonalizedAssessmentQuestion(assessmentId, questionId) {
  return authenticatedRequest(`/api/professor/personalized-assessments/${assessmentId}/questions/${questionId}`, { method: 'DELETE' })
}

export function approveProfessorPersonalizedAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/personalized-assessments/${assessmentId}/approve`, { method: 'POST' })
}

export function publishProfessorPersonalizedAssessment(assessmentId) {
  return authenticatedRequest(`/api/professor/personalized-assessments/${assessmentId}/publish`, { method: 'POST' })
}

export function getProfessorRemediationLessons(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  })
  const suffix = query.toString() ? `?${query}` : ''
  return authenticatedRequest(`/api/professor/remediation/lessons${suffix}`)
}

export function getProfessorPersonalizedLesson(lessonId) {
  return authenticatedRequest(`/api/professor/personalized-lessons/${lessonId}`)
}

export function updateProfessorPersonalizedLesson(lessonId, data) {
  return authenticatedRequest(`/api/professor/personalized-lessons/${lessonId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function approveProfessorPersonalizedLesson(lessonId) {
  return authenticatedRequest(`/api/professor/personalized-lessons/${lessonId}/approve`, { method: 'PUT' })
}

export function importProfessorCourseContentFromPdf(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/content/import-from-pdf`, {
    method: 'POST',
  })
}

export function getProfessorCourseImportStatus(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/content/import-status`)
}

export function indexProfessorCourseRag(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/rag/index`, { method: 'POST' })
}

export function reindexProfessorCourseRag(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/rag/reindex`, { method: 'POST' })
}

export function getProfessorCourseRagStatus(courseId) {
  return authenticatedRequest(`/api/professor/courses/${courseId}/rag/status`)
}

export function getProfessorRagJobs() {
  return authenticatedRequest('/api/professor/rag/jobs')
}

export function importProfessorCoursePackage({ jsonFile, latexFile, classroomId, autoAssign = true }) {
  const formData = new FormData()
  formData.append('json_file', jsonFile)
  if (latexFile) formData.append('latex_file', latexFile)
  formData.append('classroom_id', classroomId)
  formData.append('auto_assign', String(autoAssign))
  return authenticatedRequest('/api/professor/courses/automatic-import', {
    method: 'POST',
    body: formData,
  })
}

export function getProfessorCoursePackageImportStatus(jobId) {
  return authenticatedRequest(`/api/professor/courses/automatic-import/${jobId}`)
}

export function getParentDashboard() {
  return authenticatedRequest('/api/parent/dashboard')
}

export function getParentStudent(studentId) {
  return authenticatedRequest(`/api/parent/students/${studentId}`)
}

export function getParentNotificationPreferences() {
  return authenticatedRequest('/api/parent/notification-preferences')
}

export function updateParentNotificationPreferences(data) {
  return authenticatedRequest('/api/parent/notification-preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getParentNotifications() {
  return authenticatedRequest('/api/parent/notifications')
}

export function getRegionalExamPreparation() {
  return authenticatedRequest('/api/regional-exam-preparation')
}

export function getRegionalExams(filters = {}) {
  const query = buildQuery(filters)
  return authenticatedRequest(`/api/regional-exams${query}`)
}

export function getRegionalExam(examId) {
  return authenticatedRequest(`/api/regional-exams/${examId}`)
}

export function startRegionalExam(examId) {
  return authenticatedRequest(`/api/regional-exams/${examId}/start`, { method: 'POST' })
}

export function submitRegionalExam(examId, data) {
  return authenticatedRequest(`/api/regional-exams/${examId}/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getRegionalExamAttempts(examId) {
  return authenticatedRequest(`/api/regional-exams/${examId}/attempts`)
}

export function getRegionalExamAttempt(attemptId) {
  return authenticatedRequest(`/api/regional-exam-attempts/${attemptId}`)
}

export function createAdminParentStudentLink(data) {
  return authenticatedRequest('/api/admin/parents/links', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function getAdminParentStudentLinks() {
  return authenticatedRequest('/api/admin/parents/links')
}

export function getAdminParentNotifications() {
  return authenticatedRequest('/api/admin/parents/notifications')
}

export function retryAdminParentNotificationDelivery(deliveryId) {
  return authenticatedRequest(`/api/admin/parents/notifications/deliveries/${deliveryId}/retry`, { method: 'POST' })
}

export function fetchAdminSubjects() {
  return authenticatedRequest('/api/admin/subjects')
}

export function createAdminSubject(data) {
  return authenticatedRequest('/api/admin/subjects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateAdminSubject(id, data) {
  return authenticatedRequest(`/api/admin/subjects/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteAdminSubject(id) {
  return authenticatedRequest(`/api/admin/subjects/${id}`, {
    method: 'DELETE',
  })
}

export function fetchAdminEducationLevels() {
  return authenticatedRequest('/api/admin/education-levels')
}

export function fetchAdminDifficultyLevels() {
  return authenticatedRequest('/api/admin/difficulty-levels')
}

export function fetchAdminDiagnosticQuestions(params = {}) {
  const query = buildQuery(params)
  return authenticatedRequest(`/api/admin/diagnostic/questions${query}`)
}

export function createAdminDiagnosticQuestion(data) {
  return authenticatedRequest('/api/admin/diagnostic/questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function updateAdminDiagnosticQuestion(id, data) {
  return authenticatedRequest(`/api/admin/diagnostic/questions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function deleteAdminDiagnosticQuestion(id) {
  return authenticatedRequest(`/api/admin/diagnostic/questions/${id}`, {
    method: 'DELETE',
  })
}

function buildQuery(params = {}) {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '' && value !== 'all') {
      searchParams.set(key, value)
    }
  })
  const query = searchParams.toString()
  return query ? `?${query}` : ''
}
