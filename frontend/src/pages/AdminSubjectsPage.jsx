import { useEffect, useState } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import { AdminLoading, AdminMessage } from '../components/admin/AdminShared.jsx'
import { createAdminSubject, deleteAdminSubject, fetchAdminSubjects, updateAdminSubject } from '../services/api.js'

const EMPTY_SUBJECT = {
  name: '',
  slug: '',
  description: '',
  icon: '',
  active: true,
  display_order: 0,
}

function AdminSubjectsPage() {
  const [subjects, setSubjects] = useState([])
  const [draft, setDraft] = useState(EMPTY_SUBJECT)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadSubjects()
  }, [])

  async function loadSubjects() {
    setLoading(true)
    setMessage('')
    try {
      const data = await fetchAdminSubjects()
      setSubjects(Array.isArray(data) ? data : [])
    } catch {
      setMessage('Impossible de charger les matieres.')
    } finally {
      setLoading(false)
    }
  }

  function editSubject(subject) {
    setEditingId(subject.id)
    setDraft({
      name: subject.name || '',
      slug: subject.slug || '',
      description: subject.description || '',
      icon: subject.icon || '',
      active: subject.active !== false,
      display_order: subject.display_order || 0,
    })
  }

  function resetForm() {
    setEditingId(null)
    setDraft(EMPTY_SUBJECT)
  }

  async function saveSubject(event) {
    event.preventDefault()
    try {
      if (editingId) {
        await updateAdminSubject(editingId, draft)
        setMessage('Matiere modifiee avec succes.')
      } else {
        await createAdminSubject(draft)
        setMessage('Matiere ajoutee avec succes.')
      }
      resetForm()
      await loadSubjects()
    } catch (error) {
      setMessage(error.message || 'Enregistrement impossible.')
    }
  }

  async function toggleSubject(subject) {
    try {
      await updateAdminSubject(subject.id, { ...subject, active: !subject.active })
      await loadSubjects()
      setMessage(subject.active ? 'Matiere desactivee.' : 'Matiere activee.')
    } catch (error) {
      setMessage(error.message || 'Changement de statut impossible.')
    }
  }

  async function removeSubject(subject) {
    if (!window.confirm(`Supprimer la matiere "${subject.name}" ?`)) return
    try {
      await deleteAdminSubject(subject.id)
      await loadSubjects()
      setMessage('Matiere supprimee.')
    } catch (error) {
      setMessage(error.message || 'Suppression impossible.')
    }
  }

  if (loading) return <AdminLoading text="Chargement des matieres..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Matieres</h1>
        <p>Gestion des matieres disponibles dans EduMentor AI.</p>
      </div>

      <AdminMessage message={message} />

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Catalogue des matieres</h2>
            <p>Ajout, modification, ordre d'affichage et activation.</p>
          </div>
          <button className="outline-button" onClick={resetForm} type="button"><Plus size={18} /> Nouvelle matiere</button>
        </div>

        <div className="admin-course-grid">
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Matiere</th>
                  <th>Slug</th>
                  <th>Cours</th>
                  <th>Ordre</th>
                  <th>Statut</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {subjects.map((subject) => (
                  <tr key={subject.id}>
                    <td><strong>{subject.name}</strong><span>{subject.description || '--'}</span></td>
                    <td>{subject.slug}</td>
                    <td>{subject.course_count || 0}</td>
                    <td>{subject.display_order}</td>
                    <td><em className={subject.active ? 'admin-pill' : 'admin-pill muted'}>{subject.active ? 'active' : 'inactive'}</em></td>
                    <td>
                      <div className="admin-actions">
                        <button onClick={() => editSubject(subject)} type="button">Modifier</button>
                        <button onClick={() => toggleSubject(subject)} type="button">{subject.active ? 'Desactiver' : 'Activer'}</button>
                        <button onClick={() => removeSubject(subject)} type="button"><Trash2 size={16} /> Supprimer</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {subjects.length === 0 && <p className="admin-empty">Aucune matiere disponible.</p>}
          </div>

          <form className="admin-course-form" onSubmit={saveSubject}>
            <h3>{editingId ? 'Modifier la matiere' : 'Ajouter une matiere'}</h3>
            <div className="admin-form-row">
              <label>Nom<input onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} value={draft.name} /></label>
              <label>Slug<input onChange={(event) => setDraft((current) => ({ ...current, slug: event.target.value }))} value={draft.slug} /></label>
              <label>Ordre<input onChange={(event) => setDraft((current) => ({ ...current, display_order: event.target.value }))} type="number" value={draft.display_order} /></label>
            </div>
            <label>Description<textarea onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} value={draft.description} /></label>
            <label>Icone facultative<input onChange={(event) => setDraft((current) => ({ ...current, icon: event.target.value }))} value={draft.icon} /></label>
            <label className="terms-row">
              <input checked={draft.active} onChange={(event) => setDraft((current) => ({ ...current, active: event.target.checked }))} type="checkbox" />
              Matiere active
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

export default AdminSubjectsPage
