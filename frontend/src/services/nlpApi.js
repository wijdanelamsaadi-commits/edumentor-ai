import { authenticatedRequest } from './api.js'

function buildQuery(params = {}) {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.set(key, value)
    }
  })
  const query = searchParams.toString()
  return query ? `?${query}` : ''
}

function postJson(path, data) {
  return authenticatedRequest(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(normalizeNlpResponse)
}

function normalizeNlpResponse(response) {
  if (!response || typeof response !== 'object') {
    return { ok: false, data: {}, warnings: ['Réponse NLP vide.'] }
  }

  if ('ok' in response && 'data' in response) {
    return {
      ok: response.ok !== false,
      data: response.data || {},
      warnings: Array.isArray(response.warnings) ? response.warnings : [],
    }
  }

  return { ok: true, data: response, warnings: [] }
}

export function formatNlpError(error, fallback = 'Le service NLP est indisponible.') {
  if (!error) return fallback
  if (typeof error.message === 'string' && error.message.trim()) return error.message
  if (typeof error.detail === 'string' && error.detail.trim()) return error.detail
  return fallback
}

export function getNlpModelsStatus() {
  return authenticatedRequest('/api/nlp/models/status').then(normalizeNlpResponse)
}

export function getNlpUnits(filters = {}) {
  return authenticatedRequest(`/api/nlp/units${buildQuery(filters)}`).then(normalizeNlpResponse)
}

export function predictLevel(text) {
  return postJson('/api/nlp/level', { text })
}

export function predictContentType(payload) {
  return postJson('/api/nlp/content-type', payload)
}

export function adaptPedagogicalText(payload) {
  return postJson('/api/nlp/adapt', payload)
}

export function generateQuestionCorrection(payload) {
  return postJson('/api/nlp/qa/generate', payload)
}

export function correctQuestion(payload) {
  return postJson('/api/nlp/qa/correct', payload)
}

export function analyzeFigure(text) {
  return postJson('/api/nlp/figures', { text })
}

export function classifyExamCompetence(text) {
  return postJson('/api/nlp/exam-competence', { text })
}

export function analyzeAllNlp(payload) {
  return postJson('/api/nlp/analyze-all', payload)
}

export const fetchNlpModelsStatus = getNlpModelsStatus
export const predictPedagogicalLevel = predictLevel
export const analyzeFigureOfSpeech = analyzeFigure
export const classifyRegionalExamCompetence = classifyExamCompetence
export const analyzePedagogicalContent = analyzeAllNlp