import { CheckCircle2, Edit3 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { approveProfessorPersonalizedLesson, getProfessorRemediationLessons, updateProfessorPersonalizedLesson } from '../services/api.js'

const SECTIONS = [
  { key: 'ready', label: 'A verifier' },
  { key: 'approved', label: 'Approuves' },
  { key: 'active', label: 'En cours' },
  { key: 'completed', label: 'Termines' },
]

function ProfessorRemediationPage() {
  const [lessons, setLessons] = useState([])
  const [selectedLesson, setSelectedLesson] = useState(null)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    refresh()
  }, [])

  function refresh() {
    getProfessorRemediationLessons()
      .then(setLessons)
      .catch((err) => setMessage(err.message || 'Mini-cours indisponibles.'))
  }

  const groupedLessons = useMemo(() => ({
    ready: lessons.filter((lesson) => ['draft', 'ready'].includes(lesson.status)),
    approved: lessons.filter((lesson) => lesson.status === 'approved'),
    active: lessons.filter((lesson) => !['draft', 'ready', 'approved', 'completed', 'archived'].includes(lesson.status)),
    completed: lessons.filter((lesson) => lesson.status === 'completed'),
  }), [lessons])

  async function approveLesson(lesson) {
    try {
      setSaving(true)
      await approveProfessorPersonalizedLesson(lesson.id)
      setMessage('Mini-cours approuve.')
      refresh()
    } catch (err) {
      setMessage(err.message || 'Approbation impossible.')
    } finally {
      setSaving(false)
    }
  }

  async function saveLesson() {
    if (!selectedLesson) return
    try {
      setSaving(true)
      await updateProfessorPersonalizedLesson(selectedLesson.id, {
        title: selectedLesson.title,
        objective: selectedLesson.objective,
        structured_content: selectedLesson.structured_content,
      })
      setMessage('Mini-cours mis a jour.')
      setSelectedLesson(null)
      refresh()
    } catch (err) {
      setMessage(err.message || 'Modification impossible.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>Remediation</h1>
          <p>Suivi et validation des mini-cours personnalises.</p>
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
              </div>
              <button className="outline-button" onClick={() => setSelectedLesson(lesson)} type="button"><Edit3 size={16} /> Modifier</button>
              {['draft', 'ready'].includes(lesson.status) && (
                <button className="primary-button" disabled={saving} onClick={() => approveLesson(lesson)} type="button">Approuver</button>
              )}
            </div>
          )) : <p className="admin-empty">Aucun mini-cours dans cette section.</p>}
        </article>
      ))}
      {selectedLesson && (
        <article className="panel-card">
          <div className="panel-title"><h2>Modifier le mini-cours</h2><p>Validation professeur</p></div>
          <label>
            Titre
            <input value={selectedLesson.title} onChange={(event) => setSelectedLesson({ ...selectedLesson, title: event.target.value })} />
          </label>
          <label>
            Objectif
            <textarea value={selectedLesson.objective} onChange={(event) => setSelectedLesson({ ...selectedLesson, objective: event.target.value })} />
          </label>
          <label>
            Contenu structure JSON
            <textarea
              rows={10}
              value={JSON.stringify(selectedLesson.structured_content || [], null, 2)}
              onChange={(event) => {
                try {
                  setSelectedLesson({ ...selectedLesson, structured_content: JSON.parse(event.target.value) })
                } catch {
                  setMessage('JSON invalide.')
                }
              }}
            />
          </label>
          <div className="admin-actions">
            <button className="outline-button" onClick={() => setSelectedLesson(null)} type="button">Annuler</button>
            <button className="primary-button" disabled={saving} onClick={saveLesson} type="button">Sauvegarder</button>
          </div>
        </article>
      )}
    </section>
  )
}

export default ProfessorRemediationPage
