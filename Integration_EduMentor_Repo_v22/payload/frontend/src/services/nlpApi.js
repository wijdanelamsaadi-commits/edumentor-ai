import { authenticatedRequest } from './api.js'

function postJson(path, data) {
  return authenticatedRequest(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export function fetchNlpModelsStatus() {
  return authenticatedRequest('/api/nlp/models/status')
}

export function predictPedagogicalLevel(text) {
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

export function analyzeFigureOfSpeech(text) {
  return postJson('/api/nlp/figures', { text })
}

export function classifyRegionalExamCompetence(text) {
  return postJson('/api/nlp/exam-competence', { text })
}

export function analyzePedagogicalContent(payload) {
  return postJson('/api/nlp/analyze-all', payload)
}
