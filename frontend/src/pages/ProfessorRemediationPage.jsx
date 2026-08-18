import { CheckCircle2, Eye } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { getProfessorRemediationLessons } from '../services/api.js'

const SECTIONS = [
  { key: 'generated', label: 'Generees' },
  { key: 'assigned', label: 'Assignees' },
  { key: 'active', label: 'En cours' },
  { key: 'completed', label: 'Termines' },
  { key: 'reevaluate', label: 'A reevaluer' },
]

function ProfessorRemediationPage() {
  const [lessons, setLessons] = useState([])
  const [selectedLesson, setSelectedLesson] = useState(null)
  const [message, setMessage] = useState('')

  useEffect(() => {
    refresh()
  }, [])

  function refresh() {
    getProfessorRemediationLessons()
      .then(setLessons)
      .catch((err) => setMessage(err.message || 'Mini-cours indisponibles.'))
  }

  const groupedLessons = useMemo(() => ({
    generated: lessons.filter((lesson) => ['draft', 'ready'].includes(lesson.status)),
    assigned: lessons.filter((lesson) => lesson.status === 'approved'),
    active: lessons.filter((lesson) => !['draft', 'ready', 'approved', 'completed', 'archived'].includes(lesson.status)),
    completed: lessons.filter((lesson) => lesson.status === 'completed'),
    reevaluate: lessons.filter((lesson) => lesson.plan_status === 'to_reevaluate'),
  }), [lessons])

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Remediation</h1>
          <p>Suivi automatique des mini-cours personnalises et de l'evolution des competences.</p>
        </div>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}
      {SECTIONS.map((section) => (
        <article className="panel-card" key={section.key}>
          <div className="panel-title"><h2>{section.label}</h2><p>{groupedLessons[section.key].length}</p></div>
          {groupedLessons[section.key].length ? groupedLessons[section.key].map((lesson) => (
            <div className="history-item" key={lesson.id}>
              <span>{lesson.status === 'completed' ? <CheckCircle2 size={18} /> : lesson.id}</span>
              <div>
                <strong>{lesson.title}</strong>
                <p>{lesson.student_name} - {lesson.course_title} - {lesson.skill_name || lesson.chapter_title || 'Notion ciblee'}</p>
                <small>{lesson.reason}</small>
                <p>
                  Avant : {formatScore(lesson.initial_score)} - Apres : {formatScore(lesson.after_score)}
                  {Number.isFinite(Number(lesson.evolution_points)) ? ` - Evolution : ${Number(lesson.evolution_points) >= 0 ? '+' : ''}${Math.round(Number(lesson.evolution_points))} pts` : ''}
                </p>
              </div>
              <button className="outline-button" onClick={() => setSelectedLesson(lesson)} type="button"><Eye size={16} /> Consulter</button>
            </div>
          )) : <p className="admin-empty">Aucun mini-cours dans cette section.</p>}
        </article>
      ))}
      {selectedLesson && (
        <article className="panel-card">
          <div className="panel-title"><h2>{selectedLesson.title}</h2><p>Lecture seule</p></div>
          <p><strong>Etudiant :</strong> {selectedLesson.student_name}</p>
          <p><strong>Competence :</strong> {selectedLesson.skill_name || selectedLesson.chapter_title || 'Notion ciblee'}</p>
          <p><strong>Statut :</strong> {selectedLesson.status}</p>
          <p>{selectedLesson.objective}</p>
          {(selectedLesson.structured_content || []).map((block, index) => (
            <div className="history-item" key={`${selectedLesson.id}-${block.type}-${index}`}>
              <span>{index + 1}</span>
              <div>
                <strong>{block.title || block.type}</strong>
                <p>{formatBlockContent(block.content)}</p>
              </div>
            </div>
          ))}
          <div className="admin-actions">
            <button className="outline-button" onClick={() => setSelectedLesson(null)} type="button">Fermer</button>
          </div>
        </article>
      )}
    </section>
  )
}

function formatScore(value) {
  return Number.isFinite(Number(value)) ? `${Math.round(Number(value))}%` : 'En attente'
}

function formatBlockContent(content) {
  if (Array.isArray(content)) return content.join(' - ')
  if (content && typeof content === 'object') return content.question || content.explanation || JSON.stringify(content)
  return content || ''
}

export default ProfessorRemediationPage
