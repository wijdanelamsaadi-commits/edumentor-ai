import { useEffect, useState } from 'react'
import { ListFilter, Search } from 'lucide-react'
import {
  AdminLoading,
  AdminMessage,
} from '../components/admin/AdminShared.jsx'
import {
  formatAuditAction,
  formatAuditTarget,
  formatDate,
  formatTime,
} from '../utils/adminFormat.js'
import { fetchAdminAuditLogs } from '../services/api.js'

const DEFAULT_AUDIT_FILTERS = { search: '', action: 'all', target_type: 'all', page: 1 }

function AdminAuditPage() {
  const [auditLogs, setAuditLogs] = useState({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 })
  const [auditFilters, setAuditFilters] = useState(DEFAULT_AUDIT_FILTERS)
  const [loading, setLoading] = useState(true)
  const [auditLoading, setAuditLoading] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    async function loadInitialLogs() {
      setLoading(true)
      setMessage('')
      try {
        const data = await fetchAdminAuditLogs(DEFAULT_AUDIT_FILTERS)
        setAuditLogs(data || { items: [], total: 0, page: 1, page_size: 20, total_pages: 1 })
      } catch {
        setMessage('Chargement du journal impossible.')
      } finally {
        setLoading(false)
      }
    }

    loadInitialLogs()
  }, [])

  async function loadAuditLogs(nextFilters = auditFilters) {
    setAuditLoading(true)
    try {
      const data = await fetchAdminAuditLogs(nextFilters)
      setAuditLogs(data || { items: [], total: 0, page: 1, page_size: 20, total_pages: 1 })
    } catch (error) {
      setMessage(error.message || 'Chargement du journal impossible.')
    } finally {
      setAuditLoading(false)
    }
  }

  function updateAuditFilters(field, value) {
    setAuditFilters((current) => ({ ...current, [field]: value, page: 1 }))
  }

  async function applyAuditFilters(event) {
    event.preventDefault()
    const nextFilters = { ...auditFilters, page: 1 }
    setAuditFilters(nextFilters)
    await loadAuditLogs(nextFilters)
  }

  async function changeAuditPage(page) {
    const nextFilters = { ...auditFilters, page }
    setAuditFilters(nextFilters)
    await loadAuditLogs(nextFilters)
  }

  if (loading) return <AdminLoading text="Chargement du journal d'administration..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Journal d'administration</h1>
        <p>Historique des actions sensibles realisees par les administrateurs.</p>
      </div>

      <AdminMessage message={message} />

      <article className="panel-card admin-users-panel">
        <div className="panel-title">
          <div>
            <h2>Journal d'administration</h2>
            <p>Recherche, filtres et pagination des logs admin.</p>
          </div>
          <button className="outline-button" onClick={() => loadAuditLogs()} type="button">Actualiser</button>
        </div>

        <form className="admin-filters" onSubmit={applyAuditFilters}>
          <label className="admin-search">
            <Search size={18} />
            <input
              onChange={(event) => updateAuditFilters('search', event.target.value)}
              placeholder="Rechercher action ou cible"
              value={auditFilters.search}
            />
          </label>
          <select onChange={(event) => updateAuditFilters('action', event.target.value)} value={auditFilters.action}>
            <option value="all">Toutes les actions</option>
            <option value="create_course">Creation cours</option>
            <option value="update_course">Modification cours</option>
            <option value="delete_course">Suppression cours</option>
            <option value="upload_pdf">Upload PDF</option>
            <option value="replace_pdf">Remplacement PDF</option>
            <option value="delete_pdf">Suppression PDF</option>
            <option value="update_role">Changement role</option>
            <option value="enable_user">Activation</option>
            <option value="disable_user">Desactivation</option>
            <option value="delete_user">Suppression utilisateur</option>
            <option value="reindex_rag">Reindexation RAG</option>
          </select>
          <select onChange={(event) => updateAuditFilters('target_type', event.target.value)} value={auditFilters.target_type}>
            <option value="all">Toutes les cibles</option>
            <option value="course">Cours</option>
            <option value="course_pdf">PDF</option>
            <option value="user">Utilisateur</option>
            <option value="rag">RAG</option>
          </select>
          <button className="outline-button" type="submit"><ListFilter size={18} /> Filtrer</button>
        </form>

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Admin</th>
                <th>Action</th>
                <th>Cible</th>
                <th>ID cible</th>
              </tr>
            </thead>
            <tbody>
              {(auditLogs.items || []).map((log) => (
                <tr key={log.id}>
                  <td><strong>{formatDate(log.created_at)}</strong><span>{formatTime(log.created_at)}</span></td>
                  <td>#{log.admin_user_id}</td>
                  <td><em className="admin-pill">{formatAuditAction(log.action)}</em></td>
                  <td>{formatAuditTarget(log.target_type)}</td>
                  <td>{log.target_id || '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {auditLoading && <p className="admin-empty">Chargement du journal...</p>}
          {!auditLoading && (auditLogs.items || []).length === 0 && <p className="admin-empty">Aucune action administrative trouvee.</p>}
        </div>
        <div className="admin-pagination">
          <button disabled={auditLogs.page <= 1} onClick={() => changeAuditPage(auditLogs.page - 1)} type="button">Precedent</button>
          <span>Page {auditLogs.page} / {auditLogs.total_pages}</span>
          <button disabled={auditLogs.page >= auditLogs.total_pages} onClick={() => changeAuditPage(auditLogs.page + 1)} type="button">Suivant</button>
        </div>
      </article>
    </section>
  )
}

export default AdminAuditPage
