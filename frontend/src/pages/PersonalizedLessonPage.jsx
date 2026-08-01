import { ArrowLeft, Bot, CheckCircle2, FileText } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  API_BASE_URL,
  completePersonalizedLesson,
  getPersonalizedLesson,
  submitPersonalizedLessonKnowledgeCheck,
} from '../services/api.js'
import { StructuredLessonBlocks } from './CourseDetailPage.jsx'

function PersonalizedLessonPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [lesson, setLesson] = useState(null)
  const [message, setMessage] = useState('')
  const [selectedAnswer, setSelectedAnswer] = useState('')
  const [checkResult, setCheckResult] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let ignore = false
    getPersonalizedLesson(id)
      .then((data) => {
        if (!ignore) setLesson(data)
      })
      .catch((err) => {
        if (!ignore) setMessage(err.message || 'Mini-cours indisponible.')
      })
    return () => {
      ignore = true
    }
  }, [id])

  const knowledgeCheck = useMemo(() => {
    const blocks = Array.isArray(lesson?.structured_content) ? lesson.structured_content : []
    return blocks.find((block) => block.type === 'knowledge_check')?.content || null
  }, [lesson])

  async function markCompleted() {
    try {
      setLoading(true)
      const updated = await completePersonalizedLesson(id)
      setLesson(updated)
      setMessage('Mini-cours marque comme termine.')
    } catch (err) {
      setMessage(err.message || 'Impossible de terminer ce mini-cours.')
    } finally {
      setLoading(false)
    }
  }

  async function submitCheck() {
    if (!selectedAnswer) {
      setMessage('Selectionnez une reponse avant de valider.')
      return
    }
    try {
      const result = await submitPersonalizedLessonKnowledgeCheck(id, selectedAnswer)
      setCheckResult(result)
      setMessage(result.correct ? 'Bonne reponse.' : 'Reponse a revoir.')
    } catch (err) {
      setMessage(err.message || 'Correction indisponible.')
    }
  }

  if (!lesson) {
    return <section className="page-section dashboard-page"><article className="panel-card"><p>{message || 'Chargement...'}</p></article></section>
  }

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{lesson.title}</h1>
          <p>{lesson.course_title} - {lesson.chapter_title || lesson.skill_name || 'Remediation personnalisee'}</p>
        </div>
        <Link className="outline-button" to={`/remediation/${lesson.remediation_plan_id}`}><ArrowLeft size={16} /> Retour</Link>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <article className="continue-card">
        <div>
          <h2>Objectif du mini-cours</h2>
          <p>{lesson.objective}</p>
          <p>{lesson.reason}</p>
        </div>
        <div className="admin-actions">
          <button className="outline-button" onClick={() => navigate(`/chatbot?course_id=${lesson.course_id}&chapter_id=${lesson.chapter_id || ''}&skill_id=${lesson.skill_id || ''}&remediation_plan_id=${lesson.remediation_plan_id}&personalized_lesson_id=${lesson.id}`)} type="button">
            <Bot size={16} /> Poser une question au chatbot
          </button>
          <button className="primary-button" disabled={loading || lesson.status === 'completed'} onClick={markCompleted} type="button">
            <CheckCircle2 size={16} /> {lesson.status === 'completed' ? 'Termine' : 'Marquer comme termine'}
          </button>
        </div>
      </article>

      <article className="panel-card lesson-panel chapter-lesson">
        <StructuredLessonBlocks blocks={Array.isArray(lesson.structured_content) ? lesson.structured_content.filter((block) => block.type !== 'knowledge_check') : []} />
      </article>

      {knowledgeCheck && (
        <article className="panel-card">
          <div className="panel-title">
            <h2>Question de verification</h2>
            <p>Correction cote backend</p>
          </div>
          <p>{knowledgeCheck.question}</p>
          <div className="quiz-options">
            {(knowledgeCheck.options || []).map((option) => (
              <button className={selectedAnswer === option ? 'selected' : ''} key={option} onClick={() => setSelectedAnswer(option)} type="button">
                {option}
              </button>
            ))}
          </div>
          <button className="primary-button" onClick={submitCheck} type="button">Valider ma reponse</button>
          {checkResult && (
            <p className={checkResult.correct ? 'success-text' : 'error-text'}>
              {checkResult.correct ? '+10 XP - ' : ''}{checkResult.explanation}
            </p>
          )}
        </article>
      )}

      <article className="panel-card">
        <div className="panel-title">
          <h2>Sources regroupees</h2>
          <p>{lesson.sources?.length || 0}</p>
        </div>
        {(lesson.sources || []).length ? lesson.sources.map((source) => (
          <div className="history-item" key={source.id}>
            <span><FileText size={18} /></span>
            <div>
              <strong>{source.file_name || source.source_type}</strong>
              <p>{source.source_type} - page {source.page_start || '-'}</p>
              {source.excerpt && <small>{source.excerpt}</small>}
            </div>
            {source.file_name && <a className="outline-button" href={sourceUrl(source)} rel="noreferrer" target="_blank">Ouvrir</a>}
          </div>
        )) : <p className="admin-empty">Aucune source documentaire publique associee.</p>}
      </article>
    </section>
  )
}

function sourceUrl(source) {
  const pageAnchor = source.page_start ? `#page=${source.page_start}` : ''
  return `${API_BASE_URL}/docs/courses/${encodeURIComponent(source.file_name)}${pageAnchor}`
}

export default PersonalizedLessonPage
