import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { FileText, Save, Upload } from 'lucide-react'
import {
  createProfessorChapter,
  createProfessorCourse,
  deleteProfessorChapter,
  deleteProfessorCoursePdf,
  fetchDifficultyLevels,
  fetchEducationLevels,
  fetchSubjects,
  getProfessorCourse,
  getProfessorCourseImportStatus,
  getProfessorCourseRagStatus,
  importProfessorCourseContentFromPdf,
  indexProfessorCourseRag,
  publishProfessorCourse,
  replaceProfessorExamples,
  replaceProfessorObjectives,
  replaceProfessorSkills,
  reindexProfessorCourseRag,
  unpublishProfessorCourse,
  updateProfessorChapter,
  updateProfessorCourse,
  uploadProfessorCoursePdf,
} from '../services/api.js'

const emptyDraft = {
  title: '',
  summary: '',
  description: '',
  subject_id: '',
  education_level_id: '',
  difficulty_level_id: '',
  estimated_duration: '',
  prerequisites: '',
}

function ProfessorCourseEditorPage({ mode = 'edit' }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const isNew = !id
  const [course, setCourse] = useState(null)
  const [draft, setDraft] = useState(emptyDraft)
  const [chapterDraft, setChapterDraft] = useState({ title: '', content: '', estimated_duration: '20 min', status: 'locked', openable: false })
  const [subjects, setSubjects] = useState([])
  const [educationLevels, setEducationLevels] = useState([])
  const [difficultyLevels, setDifficultyLevels] = useState([])
  const [objectivesText, setObjectivesText] = useState('')
  const [skillsText, setSkillsText] = useState('')
  const [examplesText, setExamplesText] = useState('')
  const [message, setMessage] = useState('')
  const [importStatus, setImportStatus] = useState(null)
  const [ragStatus, setRagStatus] = useState(null)
  const [loading, setLoading] = useState(!isNew)

  useEffect(() => {
    Promise.all([fetchSubjects(), fetchEducationLevels(), fetchDifficultyLevels()])
      .then(([subjectData, levelData, difficultyData]) => {
        setSubjects(subjectData)
        setEducationLevels(levelData)
        setDifficultyLevels(difficultyData)
        if (isNew && subjectData[0]) {
          setDraft((prev) => ({ ...prev, subject_id: subjectData[0].id }))
        }
      })
      .catch(() => setMessage('Impossible de charger les référentiels.'))
  }, [isNew])

  useEffect(() => {
    if (isNew) return
    let ignore = false
    setLoading(true)
    getProfessorCourse(id)
      .then((data) => {
        if (ignore) return
        setCourse(data)
        setDraft({
          title: data.title || '',
          summary: data.summary || '',
          description: data.description || '',
          subject_id: data.subject_id || '',
          education_level_id: data.education_level_id || '',
          difficulty_level_id: data.difficulty_level_id || '',
          estimated_duration: data.estimated_duration || data.duration || '',
          prerequisites: data.prerequisites || '',
        })
        setObjectivesText((data.objectives || []).join('\n'))
        setSkillsText((data.skills || []).join('\n'))
        setExamplesText((data.examples || []).map((item) => `${item.title} | ${item.description}`).join('\n'))
        setImportStatus({ status: data.content_import_status, error: data.content_import_error, imported_at: data.content_imported_at })
        getProfessorCourseRagStatus(data.id).then(setRagStatus).catch(() => setRagStatus(null))
      })
      .catch((err) => setMessage(err.message || 'Impossible de charger ce cours.'))
      .finally(() => setLoading(false))
    return () => {
      ignore = true
    }
  }, [id, isNew])

  const validation = useMemo(() => ({
    info: Boolean(draft.title.trim() && draft.subject_id && (draft.summary.trim() || draft.description.trim())),
    chapters: Boolean(course?.chapters?.length),
  }), [draft, course])

  async function saveInfo() {
    try {
      const payload = { ...draft, duration: draft.estimated_duration }
      const saved = isNew ? await createProfessorCourse(payload) : await updateProfessorCourse(id, payload)
      setCourse(saved)
      setMessage('Cours sauvegardé.')
      if (isNew) navigate(`/professor/courses/${saved.id}/edit`, { replace: true })
    } catch (err) {
      setMessage(err.message || 'Sauvegarde impossible.')
    }
  }

  async function saveLists() {
    if (!course) return
    try {
      await replaceProfessorObjectives(course.id, toLines(objectivesText))
      await replaceProfessorSkills(course.id, toLines(skillsText))
      await replaceProfessorExamples(course.id, parseExamples(examplesText))
      const fresh = await getProfessorCourse(course.id)
      setCourse(fresh)
      setMessage('Objectifs, compétences et exemples sauvegardés.')
    } catch (err) {
      setMessage(err.message || 'Sauvegarde du contenu impossible.')
    }
  }

  async function saveChapter() {
    if (!course) return
    try {
      await createProfessorChapter(course.id, chapterDraft)
      const fresh = await getProfessorCourse(course.id)
      setCourse(fresh)
      setChapterDraft({ title: '', content: '', estimated_duration: '20 min', status: 'locked', openable: false })
      setMessage('Chapitre ajouté.')
    } catch (err) {
      setMessage(err.message || 'Ajout du chapitre impossible.')
    }
  }

  async function updateChapter(chapter, changes) {
    try {
      await updateProfessorChapter(course.id, chapter.id, { ...chapter, ...changes })
      const fresh = await getProfessorCourse(course.id)
      setCourse(fresh)
    } catch (err) {
      setMessage(err.message || 'Modification du chapitre impossible.')
    }
  }

  async function removeChapter(chapterId) {
    if (!window.confirm('Supprimer ce chapitre ?')) return
    try {
      await deleteProfessorChapter(course.id, chapterId)
      const fresh = await getProfessorCourse(course.id)
      setCourse(fresh)
    } catch (err) {
      setMessage(err.message || 'Suppression du chapitre impossible.')
    }
  }

  async function handlePdfChange(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !course) return
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setMessage('Seuls les fichiers PDF sont acceptés.')
      return
    }
    try {
      await uploadProfessorCoursePdf(course.id, file)
      const fresh = await getProfessorCourse(course.id)
      setCourse(fresh)
      setMessage('Support PDF téléversé.')
    } catch (err) {
      setMessage(err.message || 'Upload PDF impossible.')
    }
  }

  async function removePdf() {
    if (!course || !window.confirm('Supprimer le support PDF ?')) return
    try {
      await deleteProfessorCoursePdf(course.id)
      const fresh = await getProfessorCourse(course.id)
      setCourse(fresh)
      setMessage('Support PDF supprimé.')
    } catch (err) {
      setMessage(err.message || 'Suppression PDF impossible.')
    }
  }

  async function buildContentFromPdf() {
    if (!course) return
    try {
      setMessage('Construction du contenu à partir du PDF en cours...')
      const result = await importProfessorCourseContentFromPdf(course.id)
      const status = await getProfessorCourseImportStatus(course.id)
      const fresh = await getProfessorCourse(course.id)
      setImportStatus(status)
      setCourse(fresh)
      setObjectivesText((fresh.objectives || []).join('\n'))
      setSkillsText((fresh.skills || []).join('\n'))
      setExamplesText((fresh.examples || []).map((item) => `${item.title} | ${item.description}`).join('\n'))
      setMessage(`Contenu généré en brouillon : ${result.chapters?.length || 0} chapitres prêts à vérifier.`)
    } catch (err) {
      setMessage(err.message || "Construction du contenu impossible.")
    }
  }

  async function runRagIndex(action) {
    if (!course) return
    try {
      const job = action === 'reindex' ? await reindexProfessorCourseRag(course.id) : await indexProfessorCourseRag(course.id)
      setMessage(`Indexation RAG demandée : job ${job.id || ''}`)
      const status = await getProfessorCourseRagStatus(course.id)
      setRagStatus(status)
    } catch (err) {
      setMessage(err.message || 'Indexation RAG impossible.')
    }
  }

  async function togglePublication() {
    try {
      const fresh = course.published ? await unpublishProfessorCourse(course.id) : await publishProfessorCourse(course.id)
      setCourse(fresh)
      setMessage(course.published ? 'Cours dépublié.' : 'Cours publié.')
    } catch (err) {
      setMessage(err.message || 'Publication impossible.')
    }
  }

  if (loading) {
    return <section className="page-section"><article className="panel-card">Chargement...</article></section>
  }

  return (
    <section className="page-section admin-page">
      <div className="page-heading-row">
        <div className="page-heading">
          <h1>{isNew ? 'Créer un cours' : mode === 'content' ? 'Contenu du cours' : 'Modifier le cours'}</h1>
          <p>Gestion pédagogique réservée au professeur propriétaire.</p>
        </div>
        <Link className="outline-button" to="/professor/courses">Retour aux cours</Link>
      </div>

      {message && <article className="panel-card"><p>{message}</p></article>}

      <article className="panel-card admin-course-form">
        <h3>Informations</h3>
        <label>Titre<input onChange={(event) => setDraft((prev) => ({ ...prev, title: event.target.value }))} value={draft.title} /></label>
        <label>Résumé<textarea onChange={(event) => setDraft((prev) => ({ ...prev, summary: event.target.value }))} value={draft.summary} /></label>
        <label>Description<textarea onChange={(event) => setDraft((prev) => ({ ...prev, description: event.target.value }))} value={draft.description} /></label>
        <div className="admin-form-row">
          <label>Matière<select onChange={(event) => setDraft((prev) => ({ ...prev, subject_id: Number(event.target.value) || '' }))} value={draft.subject_id}>
            <option value="">Sélectionner</option>
            {subjects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <label>Niveau d'études<select onChange={(event) => setDraft((prev) => ({ ...prev, education_level_id: Number(event.target.value) || '' }))} value={draft.education_level_id}>
            <option value="">Non défini</option>
            {educationLevels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
          <label>Difficulté<select onChange={(event) => setDraft((prev) => ({ ...prev, difficulty_level_id: Number(event.target.value) || '' }))} value={draft.difficulty_level_id}>
            <option value="">Non définie</option>
            {difficultyLevels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>
        </div>
        <div className="admin-form-row">
          <label>Durée estimée<input onChange={(event) => setDraft((prev) => ({ ...prev, estimated_duration: event.target.value }))} value={draft.estimated_duration} /></label>
          <label>Prérequis<input onChange={(event) => setDraft((prev) => ({ ...prev, prerequisites: event.target.value }))} value={draft.prerequisites} /></label>
          <button className="primary-button" onClick={saveInfo} type="button"><Save size={18} /> Sauvegarder</button>
        </div>
      </article>

      {course && (
        <>
          <article className="panel-card admin-course-form">
            <h3>Objectifs, compétences et exemples</h3>
            <label>Objectifs (une ligne par objectif)<textarea onChange={(event) => setObjectivesText(event.target.value)} value={objectivesText} /></label>
            <label>Compétences (une ligne par compétence)<textarea onChange={(event) => setSkillsText(event.target.value)} value={skillsText} /></label>
            <label>Exemples (titre | description)<textarea onChange={(event) => setExamplesText(event.target.value)} value={examplesText} /></label>
            <button className="primary-button" onClick={saveLists} type="button">Sauvegarder le contenu</button>
          </article>

          <article className="panel-card admin-course-form">
            <h3>Chapitres</h3>
            {(course.chapters || []).map((chapter) => (
              <div className="professor-chapter-card" key={chapter.id}>
                <div className="professor-inline-editor">
                  <input onChange={(event) => updateChapter(chapter, { title: event.target.value })} value={chapter.title} />
                  <input onChange={(event) => updateChapter(chapter, { estimated_duration: event.target.value, duration: event.target.value })} value={chapter.estimated_duration || chapter.duration} />
                  <select onChange={(event) => updateChapter(chapter, { status: event.target.value, openable: ['completed', 'active'].includes(event.target.value) })} value={chapter.status}>
                    <option value="completed">completed</option>
                    <option value="active">active</option>
                    <option value="locked">locked</option>
                  </select>
                  <button onClick={() => removeChapter(chapter.id)} type="button">Supprimer</button>
                </div>
                <label>Blocs pédagogiques structurés<textarea onBlur={(event) => saveChapterBlocks(chapter, event.target.value, updateChapter, setMessage)} defaultValue={JSON.stringify(chapter.structured_content || [], null, 2)} /></label>
                <details>
                  <summary>Prévisualiser les blocs</summary>
                  {(chapter.structured_content || []).map((block, index) => <p key={`${block.type}-${index}`}><strong>{block.type}</strong> {block.title || String(block.content || '').slice(0, 80)}</p>)}
                </details>
              </div>
            ))}
            <label>Nouveau chapitre<input onChange={(event) => setChapterDraft((prev) => ({ ...prev, title: event.target.value }))} placeholder="Titre" value={chapterDraft.title} /></label>
            <label>Contenu<textarea onChange={(event) => setChapterDraft((prev) => ({ ...prev, content: event.target.value }))} value={chapterDraft.content} /></label>
            <div className="admin-form-row">
              <label>Durée<input onChange={(event) => setChapterDraft((prev) => ({ ...prev, estimated_duration: event.target.value }))} value={chapterDraft.estimated_duration} /></label>
              <label>Statut<select onChange={(event) => setChapterDraft((prev) => ({ ...prev, status: event.target.value, openable: ['completed', 'active'].includes(event.target.value) }))} value={chapterDraft.status}>
                <option value="completed">completed</option>
                <option value="active">active</option>
                <option value="locked">locked</option>
              </select></label>
              <button className="primary-button" onClick={saveChapter} type="button">Ajouter le chapitre</button>
            </div>
          </article>

          <article className="panel-card admin-course-form">
            <h3>Support PDF</h3>
            <p>{course.pdf_url ? `Support actuel : ${course.pdf_url}` : 'Aucun support PDF associé.'}</p>
            <p>Import pédagogique : {importStatus?.status || course.content_import_status || 'pending'}{importStatus?.error ? ` - ${importStatus.error}` : ''}</p>
            <p>Index RAG : {ragStatus?.index_status || 'pending'} · Pages : {ragStatus?.page_count || 0} · Chunks : {ragStatus?.chunk_count || 0}</p>
            {ragStatus?.checksum_short && <p>Checksum : {ragStatus.checksum_short} · Modèle : {ragStatus.embedding_model}</p>}
            {ragStatus?.index_error && <p>{ragStatus.index_error}</p>}
            <div className="admin-actions">
              <label className="admin-upload-button"><Upload size={16} /> Téléverser / remplacer<input accept="application/pdf" className="sr-only" onChange={handlePdfChange} type="file" /></label>
              {course.pdf_url && <button onClick={removePdf} type="button"><FileText size={16} /> Supprimer PDF</button>}
              {course.pdf_url && <button onClick={buildContentFromPdf} type="button">Construire le contenu à partir du PDF</button>}
              {course.pdf_url && <button onClick={() => runRagIndex('index')} type="button">Indexer</button>}
              {course.pdf_url && <button onClick={() => runRagIndex('reindex')} type="button">Réindexer</button>}
            </div>
          </article>

          <article className="panel-card admin-course-form">
            <h3>Publication</h3>
            <p>Informations : {validation.info ? 'complètes' : 'incomplètes'} · Chapitres : {validation.chapters ? 'présents' : 'absents'}</p>
            <button className="primary-button" onClick={togglePublication} type="button">{course.published ? 'Dépublier' : 'Publier le cours'}</button>
          </article>
        </>
      )}
    </section>
  )
}

function toLines(value) {
  return value.split('\n').map((line) => line.trim()).filter(Boolean)
}

function parseExamples(value) {
  return toLines(value).map((line) => {
    const [title, ...rest] = line.split('|')
    return { title: title.trim(), description: rest.join('|').trim() }
  })
}

function saveChapterBlocks(chapter, value, updateChapter, setMessage) {
  try {
    const structuredContent = JSON.parse(value || '[]')
    if (!Array.isArray(structuredContent)) {
      setMessage('Les blocs doivent être une liste JSON.')
      return
    }
    updateChapter(chapter, { structured_content: structuredContent })
  } catch {
    setMessage('JSON invalide : les blocs ne sont pas sauvegardés.')
  }
}

export default ProfessorCourseEditorPage
