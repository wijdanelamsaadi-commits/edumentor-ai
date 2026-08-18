import { useEffect, useMemo, useState } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import { AdminLoading, AdminMessage } from '../components/admin/AdminShared.jsx'
import {
  createAdminDiagnosticQuestion,
  fetchAdminCourses,
  deleteAdminDiagnosticQuestion,
  fetchAdminDiagnosticQuestions,
  fetchAdminDifficultyLevels,
  fetchAdminEducationLevels,
  fetchAdminSubjects,
  updateAdminDiagnosticQuestion,
} from '../services/api.js'

const EMPTY_QUESTION = {
  subject_id: '',
  education_level_id: '',
  difficulty_level_id: '',
  topic: '',
  question: '',
  choices: ['', '', '', ''],
  correct_answer: '',
  explanation: '',
  active: true,
}

function AdminDiagnosticPage() {
  const [questions, setQuestions] = useState([])
  const [subjects, setSubjects] = useState([])
  const [educationLevels, setEducationLevels] = useState([])
  const [difficultyLevels, setDifficultyLevels] = useState([])
  const [courses, setCourses] = useState([])
  const [selectedSubjectId, setSelectedSubjectId] = useState('all')
  const [selectedEducationLevelId, setSelectedEducationLevelId] = useState('all')
  const [selectedCourseId, setSelectedCourseId] = useState('all')
  const [selectedDifficultyId, setSelectedDifficultyId] = useState('all')
  const [selectedStatus, setSelectedStatus] = useState('all')
  const [selectedMethod, setSelectedMethod] = useState('all')
  const [draft, setDraft] = useState(EMPTY_QUESTION)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let isMounted = true

    async function loadInitialData() {
      setLoading(true)
      setMessage('')
      try {
        const [subjectRows, educationRows, difficultyRows, courseRows, questionRows] = await Promise.all([
          fetchAdminSubjects(),
          fetchAdminEducationLevels(),
          fetchAdminDifficultyLevels(),
          fetchAdminCourses(),
          fetchAdminDiagnosticQuestions(),
        ])
        if (!isMounted) return
        setSubjects(Array.isArray(subjectRows) ? subjectRows : [])
        setEducationLevels(Array.isArray(educationRows) ? educationRows : [])
        setDifficultyLevels(Array.isArray(difficultyRows) ? difficultyRows : [])
        setCourses(Array.isArray(courseRows) ? courseRows : [])
        setQuestions(Array.isArray(questionRows) ? questionRows : [])
      } catch (error) {
        if (isMounted) {
          setMessage(error.message || 'Impossible de charger la banque de questions.')
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    loadInitialData()
    return () => {
      isMounted = false
    }
  }, [])

  async function loadQuestions(overrides = {}) {
    const filters = {
      subject_id: selectedSubjectId,
      education_level_id: selectedEducationLevelId,
      source_course_id: selectedCourseId,
      difficulty_level_id: selectedDifficultyId,
      active: selectedStatus,
      generation_method: selectedMethod,
      ...overrides,
    }
    const data = await fetchAdminDiagnosticQuestions(filters)
    setQuestions(Array.isArray(data) ? data : [])
  }

  async function changeSubjectFilter(value) {
    setSelectedSubjectId(value)
    try {
      await loadQuestions({ subject_id: value })
    } catch (error) {
      setMessage(error.message || 'Filtrage impossible.')
    }
  }

  async function changeFilter(setter, key, value) {
    setter(value)
    try {
      await loadQuestions({ [key]: value })
    } catch (error) {
      setMessage(error.message || 'Filtrage impossible.')
    }
  }

  function resetForm() {
    setEditingId(null)
    setDraft({
      ...EMPTY_QUESTION,
      subject_id: subjects[0]?.id || '',
      difficulty_level_id: difficultyLevels[0]?.id || '',
    })
  }

  function editQuestion(question) {
    setEditingId(question.id)
    setDraft({
      subject_id: question.subject_id || '',
      education_level_id: question.education_level_id || '',
      difficulty_level_id: question.difficulty_level_id || '',
      topic: question.topic || '',
      question: question.question || '',
      choices: normalizeChoices(question.choices),
      correct_answer: question.correct_answer || '',
      explanation: question.explanation || '',
      active: question.active !== false,
    })
  }

  async function saveQuestion(event) {
    event.preventDefault()
    try {
      const payload = {
        ...draft,
        subject_id: Number(draft.subject_id),
        education_level_id: draft.education_level_id ? Number(draft.education_level_id) : null,
        difficulty_level_id: Number(draft.difficulty_level_id),
        choices: draft.choices.filter((choice) => choice.trim()),
      }
      if (editingId) {
        await updateAdminDiagnosticQuestion(editingId, payload)
        setMessage('Question modifiee avec succes.')
      } else {
        await createAdminDiagnosticQuestion(payload)
        setMessage('Question ajoutee avec succes.')
      }
      resetForm()
      await loadQuestions()
    } catch (error) {
      setMessage(error.message || 'Enregistrement impossible.')
    }
  }

  async function toggleQuestion(question) {
    try {
      await updateAdminDiagnosticQuestion(question.id, { ...question, active: !question.active })
      await loadQuestions()
      setMessage(question.active ? 'Question desactivee.' : 'Question activee.')
    } catch (error) {
      setMessage(error.message || 'Changement de statut impossible.')
    }
  }

  async function removeQuestion(question) {
    if (!window.confirm('Desactiver cette question ?')) return
    try {
      await deleteAdminDiagnosticQuestion(question.id)
      await loadQuestions()
      setMessage('Question desactivee.')
    } catch (error) {
      setMessage(error.message || 'Desactivation impossible.')
    }
  }

  const counts = useMemo(() => {
    return questions.reduce((accumulator, question) => {
      const key = question.subject?.name || 'Sans matiere'
      accumulator[key] = (accumulator[key] || 0) + 1
      return accumulator
    }, {})
  }, [questions])

  if (loading) return <AdminLoading text="Chargement de la banque diagnostic..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Test de positionnement</h1>
        <p>Gestion globale des questions par matiere, niveau et difficulte.</p>
      </div>

      <AdminMessage message={message} />

      <div className="dashboard-stats">
        <article className="metric-card metric-wide">
          <p>Questions actives</p>
          <h2>{questions.filter((question) => question.active).length}</h2>
          <strong>{questions.length} questions chargees</strong>
        </article>
        {Object.entries(counts).slice(0, 2).map(([subject, count]) => (
          <article className="metric-card" key={subject}>
            <p>{subject}</p>
            <h2>{count}</h2>
            <strong>questions</strong>
          </article>
        ))}
      </div>

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Banque de questions</h2>
            <p>Filtrer, modifier, activer ou desactiver les questions de positionnement.</p>
          </div>
          <button className="outline-button" onClick={resetForm} type="button"><Plus size={18} /> Nouvelle question</button>
        </div>

        <div className="admin-form-row">
          <label className="admin-filter">
            Matiere
            <select value={selectedSubjectId} onChange={(event) => changeSubjectFilter(event.target.value)}>
              <option value="all">Toutes les matieres</option>
              {subjects.map((subject) => (
                <option key={subject.id} value={subject.id}>{subject.name}</option>
              ))}
            </select>
          </label>
          <label className="admin-filter">
            Niveau
            <select value={selectedEducationLevelId} onChange={(event) => changeFilter(setSelectedEducationLevelId, 'education_level_id', event.target.value)}>
              <option value="all">Tous les niveaux</option>
              {educationLevels.map((level) => (
                <option key={level.id} value={level.id}>{level.name}</option>
              ))}
            </select>
          </label>
          <label className="admin-filter">
            Cours source
            <select value={selectedCourseId} onChange={(event) => changeFilter(setSelectedCourseId, 'source_course_id', event.target.value)}>
              <option value="all">Tous les cours</option>
              {courses.map((course) => (
                <option key={course.id} value={course.id}>{course.title}</option>
              ))}
            </select>
          </label>
          <label className="admin-filter">
            Difficulte
            <select value={selectedDifficultyId} onChange={(event) => changeFilter(setSelectedDifficultyId, 'difficulty_level_id', event.target.value)}>
              <option value="all">Toutes</option>
              {difficultyLevels.map((level) => (
                <option key={level.id} value={level.id}>{level.name}</option>
              ))}
            </select>
          </label>
          <label className="admin-filter">
            Statut
            <select value={selectedStatus} onChange={(event) => changeFilter(setSelectedStatus, 'active', event.target.value)}>
              <option value="all">Tous</option>
              <option value="true">Actives</option>
              <option value="false">Inactives</option>
            </select>
          </label>
          <label className="admin-filter">
            Methode
            <select value={selectedMethod} onChange={(event) => changeFilter(setSelectedMethod, 'generation_method', event.target.value)}>
              <option value="all">Toutes</option>
              <option value="deterministic_fallback">Import automatique</option>
              <option value="automatic_import">Automatique</option>
            </select>
          </label>
        </div>

        <div className="admin-course-grid">
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Question</th>
                  <th>Matiere</th>
                  <th>Difficulte</th>
                  <th>Theme</th>
                  <th>Statut</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {questions.map((question) => (
                  <tr key={question.id}>
                    <td><strong>{question.question}</strong><span>{question.explanation || '--'}</span></td>
                    <td>{question.subject?.name || '--'}</td>
                    <td>{question.difficulty_level?.name || '--'}</td>
                    <td>{question.topic || '--'}</td>
                    <td><em className={question.active ? 'admin-pill' : 'admin-pill muted'}>{question.active ? 'active' : 'inactive'}</em></td>
                    <td>
                      <div className="admin-actions">
                        <button onClick={() => editQuestion(question)} type="button">Modifier</button>
                        <button onClick={() => toggleQuestion(question)} type="button">{question.active ? 'Desactiver' : 'Activer'}</button>
                        <button onClick={() => removeQuestion(question)} type="button"><Trash2 size={16} /> Supprimer</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {questions.length === 0 && <p className="admin-empty">Aucune question disponible.</p>}
          </div>

          <form className="admin-course-form" onSubmit={saveQuestion}>
            <h3>{editingId ? 'Modifier la question' : 'Ajouter une question'}</h3>
            <div className="admin-form-row">
              <label>Matiere<select required value={draft.subject_id} onChange={(event) => setDraft((current) => ({ ...current, subject_id: event.target.value }))}>
                <option value="">Choisir</option>
                {subjects.map((subject) => <option key={subject.id} value={subject.id}>{subject.name}</option>)}
              </select></label>
              <label>Niveau d'etudes<select value={draft.education_level_id} onChange={(event) => setDraft((current) => ({ ...current, education_level_id: event.target.value }))}>
                <option value="">Tous</option>
                {educationLevels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
              </select></label>
              <label>Difficulte<select required value={draft.difficulty_level_id} onChange={(event) => setDraft((current) => ({ ...current, difficulty_level_id: event.target.value }))}>
                <option value="">Choisir</option>
                {difficultyLevels.map((level) => <option key={level.id} value={level.id}>{level.name}</option>)}
              </select></label>
            </div>
            <label>Theme<input value={draft.topic} onChange={(event) => setDraft((current) => ({ ...current, topic: event.target.value }))} /></label>
            <label>Question<textarea required value={draft.question} onChange={(event) => setDraft((current) => ({ ...current, question: event.target.value }))} /></label>
            {draft.choices.map((choice, index) => (
              <label key={`choice-${index}`}>Choix {index + 1}<input value={choice} onChange={(event) => updateChoice(index, event.target.value, setDraft)} /></label>
            ))}
            <label>Bonne reponse<select required value={draft.correct_answer} onChange={(event) => setDraft((current) => ({ ...current, correct_answer: event.target.value }))}>
              <option value="">Choisir</option>
              {draft.choices.filter((choice) => choice.trim()).map((choice) => <option key={choice} value={choice}>{choice}</option>)}
            </select></label>
            <label>Explication<textarea value={draft.explanation} onChange={(event) => setDraft((current) => ({ ...current, explanation: event.target.value }))} /></label>
            <label className="terms-row">
              <input checked={draft.active} onChange={(event) => setDraft((current) => ({ ...current, active: event.target.checked }))} type="checkbox" />
              Question active
            </label>
            <div className="admin-actions">
              <button className="primary-button" type="submit"><Save size={18} /> Enregistrer</button>
              <button className="outline-button" onClick={resetForm} type="button">Annuler</button>
            </div>
          </form>
        </div>
      </article>
    </section>
  )
}

function normalizeChoices(choices) {
  const normalized = Array.isArray(choices) ? choices.slice(0, 4) : []
  while (normalized.length < 4) {
    normalized.push('')
  }
  return normalized
}

function updateChoice(index, value, setDraft) {
  setDraft((current) => {
    const choices = [...current.choices]
    choices[index] = value
    return {
      ...current,
      choices,
      correct_answer: current.correct_answer === current.choices[index] ? value : current.correct_answer,
    }
  })
}

export default AdminDiagnosticPage
