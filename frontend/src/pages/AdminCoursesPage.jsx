import { useEffect, useState } from 'react'
import { FileText, Plus, Save, Trash2 } from 'lucide-react'
import { AdminLoading, AdminMessage } from '../components/admin/AdminShared.jsx'
import {
  createAdminCourse,
  deleteAdminCourse,
  deleteAdminCoursePdf,
  fetchAdminCourses,
  updateAdminCourse,
  uploadAdminCoursePdf,
} from '../services/api.js'
import {
  courseToDraft,
  createEmptyCourseDraft,
  draftToCoursePayload,
  updateCourseDraftFactory,
} from '../utils/adminCourseForm.js'

function AdminCoursesPage() {
  const [courses, setCourses] = useState([])
  const [courseDraft, setCourseDraft] = useState(() => createEmptyCourseDraft())
  const [editingCourseId, setEditingCourseId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const updateCourseDraft = updateCourseDraftFactory(setCourseDraft)

  useEffect(() => {
    loadCourses()
  }, [])

  async function loadCourses() {
    setLoading(true)
    setMessage('')
    try {
      const coursesData = await fetchAdminCourses()
      setCourses(Array.isArray(coursesData) ? coursesData : [])
    } catch {
      setMessage('Impossible de charger les cours.')
    } finally {
      setLoading(false)
    }
  }

  function editCourse(course) {
    setEditingCourseId(course.id)
    setCourseDraft(courseToDraft(course))
  }

  function resetCourseForm() {
    setEditingCourseId(null)
    setCourseDraft(createEmptyCourseDraft())
  }

  async function handleSaveCourse(event) {
    event.preventDefault()
    try {
      const payload = draftToCoursePayload(courseDraft)
      if (editingCourseId) {
        await updateAdminCourse(editingCourseId, payload)
        setMessage('Cours modifie avec succes.')
      } else {
        await createAdminCourse(payload)
        setMessage('Cours ajoute avec succes.')
      }
      resetCourseForm()
      await loadCourses()
    } catch (error) {
      setMessage(error.message || 'Enregistrement du cours impossible.')
    }
  }

  async function handleDeleteCourse(course) {
    if (!window.confirm(`Supprimer le cours "${course.title}" ?`)) return
    try {
      await deleteAdminCourse(course.id)
      await loadCourses()
      setMessage('Cours supprime.')
    } catch (error) {
      setMessage(error.message || 'Suppression du cours impossible.')
    }
  }

  async function handlePdfChange(course, event, replace = false) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setMessage('Seuls les fichiers PDF sont acceptes.')
      return
    }
    if (replace && !window.confirm(`Remplacer le PDF du cours "${course.title}" ?`)) return
    try {
      await uploadAdminCoursePdf(course.id, file, replace)
      await loadCourses()
      setMessage('Support PDF mis a jour.')
    } catch (error) {
      setMessage(error.message || 'Upload PDF impossible.')
    }
  }

  async function handleDeletePdf(course) {
    if (!window.confirm(`Supprimer le PDF associe au cours "${course.title}" ?`)) return
    try {
      await deleteAdminCoursePdf(course.id)
      await loadCourses()
      setMessage('Support PDF supprime.')
    } catch (error) {
      setMessage(error.message || 'Suppression PDF impossible.')
    }
  }

  if (loading) return <AdminLoading text="Chargement des cours..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Cours & PDF</h1>
        <p>Gestion PostgreSQL des cours, chapitres, quiz et supports PDF.</p>
      </div>

      <AdminMessage message={message} />

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Cours & PDF</h2>
            <p>Ajout, modification, publication et supports de cours.</p>
          </div>
          <button className="outline-button" onClick={resetCourseForm} type="button"><Plus size={18} /> Nouveau cours</button>
        </div>

        <div className="admin-course-grid">
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Cours</th>
                  <th>Niveau</th>
                  <th>Ordre</th>
                  <th>Publication</th>
                  <th>PDF</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {courses.map((course) => (
                  <tr key={course.id}>
                    <td><strong>{course.title}</strong><span>{course.summary}</span></td>
                    <td>{course.level}</td>
                    <td>{course.display_order}</td>
                    <td><em className={course.published ? 'admin-pill' : 'admin-pill muted'}>{course.published ? 'publie' : 'brouillon'}</em></td>
                    <td>{course.pdf_url ? <a href={course.pdf_url} rel="noreferrer" target="_blank">Ouvrir PDF</a> : '--'}</td>
                    <td>
                      <div className="admin-actions">
                        <button onClick={() => editCourse(course)} type="button">Modifier</button>
                        <label className="admin-upload-button">
                          <FileText size={16} />
                          {course.pdf_url ? 'Remplacer PDF' : 'Upload PDF'}
                          <input accept="application/pdf" className="sr-only" onChange={(event) => handlePdfChange(course, event, Boolean(course.pdf_url))} type="file" />
                        </label>
                        {course.pdf_url && <button onClick={() => handleDeletePdf(course)} type="button">Supprimer PDF</button>}
                        <button onClick={() => handleDeleteCourse(course)} type="button"><Trash2 size={16} /> Supprimer</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {courses.length === 0 && <p className="admin-empty">Aucun cours disponible.</p>}
          </div>

          <form className="admin-course-form" onSubmit={handleSaveCourse}>
            <h3>{editingCourseId ? 'Modifier le cours' : 'Ajouter un cours'}</h3>
            <label>Titre<input onChange={(event) => updateCourseDraft('title', event.target.value)} value={courseDraft.title} /></label>
            <div className="admin-form-row">
              <label>Niveau<input onChange={(event) => updateCourseDraft('level', event.target.value)} value={courseDraft.level} /></label>
              <label>Duree<input onChange={(event) => updateCourseDraft('duration', event.target.value)} value={courseDraft.duration} /></label>
              <label>Ordre<input onChange={(event) => updateCourseDraft('display_order', event.target.value)} type="number" value={courseDraft.display_order} /></label>
            </div>
            <label>Resume<textarea onChange={(event) => updateCourseDraft('summary', event.target.value)} value={courseDraft.summary} /></label>
            <label>Description<textarea onChange={(event) => updateCourseDraft('description', event.target.value)} value={courseDraft.description} /></label>
            <label>Objectifs (un par ligne)<textarea onChange={(event) => updateCourseDraft('objectivesText', event.target.value)} value={courseDraft.objectivesText} /></label>
            <label>Chapitres (titre | duree | status)<textarea onChange={(event) => updateCourseDraft('chaptersText', event.target.value)} value={courseDraft.chaptersText} /></label>
            <label>Exemples (titre | description)<textarea onChange={(event) => updateCourseDraft('examplesText', event.target.value)} value={courseDraft.examplesText} /></label>
            <label>Competences (une par ligne)<textarea onChange={(event) => updateCourseDraft('skillsText', event.target.value)} value={courseDraft.skillsText} /></label>
            <label>Quiz (question | choix1;choix2;choix3 | reponse | explication)<textarea onChange={(event) => updateCourseDraft('quizText', event.target.value)} value={courseDraft.quizText} /></label>
            <label className="terms-row">
              <input checked={courseDraft.published} onChange={(event) => updateCourseDraft('published', event.target.checked)} type="checkbox" />
              Publier le cours
            </label>
            <div className="admin-actions">
              <button className="primary-button" type="submit"><Save size={18} /> Enregistrer</button>
              <button className="outline-button" onClick={resetCourseForm} type="button">Annuler</button>
            </div>
          </form>
        </div>
      </article>
    </section>
  )
}

export default AdminCoursesPage
