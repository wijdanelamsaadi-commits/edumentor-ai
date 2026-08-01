import { useCallback, useEffect, useState } from 'react'
import { Database, FileText, RefreshCw } from 'lucide-react'
import { ActivityIcon, AdminLoading, AdminMessage, AdminMetric } from '../components/admin/AdminShared.jsx'
import {
  deleteAdminRagDocumentIndex,
  fetchAdminRagDocuments,
  fetchAdminRagJobs,
  fetchAdminRagStatus,
  reindexAdminRag,
  reindexAdminRagCourse,
  reindexAdminRagDocument,
  reindexAdminRagSubject,
} from '../services/api.js'
import { delay, formatShortDate, formatTime } from '../utils/adminFormat.js'

function AdminRagPage() {
  const [ragStatus, setRagStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [ragLoading, setRagLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [documents, setDocuments] = useState([])
  const [jobs, setJobs] = useState([])
  const [filters, setFilters] = useState({ search: '', status: '', subject_id: '', course_id: '', professor_id: '' })

  const loadRagStatus = useCallback(async () => {
    setLoading(true)
    setMessage('')
    try {
      const [status, ragDocuments, ragJobs] = await Promise.all([
        fetchAdminRagStatus(),
        fetchAdminRagDocuments(filters),
        fetchAdminRagJobs(),
      ])
      setRagStatus(status)
      setDocuments(ragDocuments)
      setJobs(ragJobs)
    } catch {
      setMessage('Impossible de charger le statut RAG.')
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    loadRagStatus()
  }, [loadRagStatus])

  async function runDocumentAction(action, documentId) {
    setRagLoading(true)
    try {
      if (action === 'delete') {
        if (!window.confirm("Supprimer l'index de ce document sans supprimer le PDF ?")) return
        await deleteAdminRagDocumentIndex(documentId)
      } else {
        await reindexAdminRagDocument(documentId)
      }
      setMessage('Action RAG lancee.')
      await loadRagStatus()
    } catch (error) {
      setMessage(error.message || 'Action RAG impossible.')
    } finally {
      setRagLoading(false)
    }
  }

  async function runGroupReindex(type, id) {
    if (!id) return
    setRagLoading(true)
    try {
      if (type === 'course') {
        await reindexAdminRagCourse(id)
      } else {
        await reindexAdminRagSubject(id)
      }
      setMessage('Reindexation groupee lancee.')
      await loadRagStatus()
    } catch (error) {
      setMessage(error.message || 'Reindexation impossible.')
    } finally {
      setRagLoading(false)
    }
  }

  async function handleReindexRag() {
    if (!window.confirm("Lancer la reconstruction de l'index RAG ?")) return
    setRagLoading(true)
    try {
      const status = await reindexAdminRag()
      setRagStatus(status)
      setMessage('Reindexation RAG lancee en arriere-plan.')
      for (let attempt = 0; attempt < 10; attempt += 1) {
        await delay(2500)
        const nextStatus = await fetchAdminRagStatus()
        setRagStatus(nextStatus)
        if (nextStatus.state !== 'running') break
      }
    } catch (error) {
      setMessage(error.message || 'Reindexation RAG impossible.')
    } finally {
      setRagLoading(false)
    }
  }

  if (loading) return <AdminLoading text="Chargement du statut RAG..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Gestion RAG</h1>
        <p>Etat de l'index documentaire et reconstruction en arriere-plan.</p>
      </div>

      <AdminMessage message={message} />

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Reindexation RAG</h2>
            <p>Reconstruisez l'index documentaire sans interrompre le chatbot.</p>
          </div>
          <button className="outline-button" disabled={ragLoading || ragStatus?.state === 'running'} onClick={handleReindexRag} type="button">
            <RefreshCw size={18} />
            {ragStatus?.state === 'running' ? 'Indexation...' : 'Reconstruire'}
          </button>
        </div>
        <div className="dashboard-stats admin-compact-stats">
          <AdminMetric icon={FileText} label="PDF indexes" value={ragStatus?.pdf_count || 0} text="Supports detectes" />
          <AdminMetric icon={Database} label="Chunks" value={ragStatus?.chunk_count || 0} text="Passages disponibles" />
          <AdminMetric icon={ActivityIcon} label="Etat" value={ragStatus?.state || 'pending'} text={ragStatus?.error || 'Index RAG'} />
          <AdminMetric icon={RefreshCw} label="Derniere indexation" value={formatShortDate(ragStatus?.last_indexed_at)} text={formatTime(ragStatus?.last_indexed_at)} />
        </div>
        <div className="admin-progress-line">
          <div className="progress-track"><span style={{ width: `${Number(ragStatus?.progress || 0)}%` }} /></div>
          <strong>{Number(ragStatus?.progress || 0)}%</strong>
        </div>
      </article>

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Documents RAG</h2>
            <p>Supports PDF relies aux cours, matieres et index ChromaDB.</p>
          </div>
          <button className="outline-button" onClick={loadRagStatus} type="button">Actualiser</button>
        </div>
        <div className="admin-filters">
          <input onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))} placeholder="Recherche document" value={filters.search} />
          <select onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))} value={filters.status}>
            <option value="">Tous les statuts</option>
            <option value="pending">En attente</option>
            <option value="processing">Indexation</option>
            <option value="ready">Pret</option>
            <option value="failed">Echec</option>
            <option value="outdated">Outdated</option>
          </select>
          <input onChange={(event) => setFilters((current) => ({ ...current, subject_id: event.target.value }))} placeholder="subject_id" value={filters.subject_id} />
          <input onChange={(event) => setFilters((current) => ({ ...current, course_id: event.target.value }))} placeholder="course_id" value={filters.course_id} />
          <input onChange={(event) => setFilters((current) => ({ ...current, professor_id: event.target.value }))} placeholder="professor_id" value={filters.professor_id} />
          <button className="outline-button" onClick={loadRagStatus} type="button">Filtrer</button>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Cours</th>
                <th>Matiere</th>
                <th>Professeur</th>
                <th>Statut</th>
                <th>Pages</th>
                <th>Chunks</th>
                <th>Modele</th>
                <th>Indexe le</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id}>
                  <td>{document.original_filename}<small>{document.checksum_short}</small></td>
                  <td>{document.course_title}</td>
                  <td>{document.subject_name || '-'}</td>
                  <td>{document.professor_name || 'Admin'}</td>
                  <td>{document.index_status}</td>
                  <td>{document.page_count}</td>
                  <td>{document.chunk_count}</td>
                  <td>{document.embedding_model}</td>
                  <td>{formatShortDate(document.indexed_at)}</td>
                  <td>
                    <button disabled={ragLoading} onClick={() => runDocumentAction('reindex', document.id)} type="button">Reindexer</button>
                    <button disabled={ragLoading} onClick={() => runDocumentAction('delete', document.id)} type="button">Supprimer index</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {documents.length === 0 && <AdminMessage message="Aucun document RAG trouve." />}
        <div className="admin-actions-row">
          <button className="outline-button" disabled={!filters.course_id || ragLoading} onClick={() => runGroupReindex('course', filters.course_id)} type="button">Reindexer cours</button>
          <button className="outline-button" disabled={!filters.subject_id || ragLoading} onClick={() => runGroupReindex('subject', filters.subject_id)} type="button">Reindexer matiere</button>
        </div>
      </article>

      <article className="panel-card">
        <div className="panel-title">
          <div>
            <h2>Jobs recents</h2>
            <p>Suivi des indexations demandees par les administrateurs et professeurs.</p>
          </div>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Action</th>
                <th>Statut</th>
                <th>Cours</th>
                <th>Chunks</th>
                <th>Demande</th>
                <th>Fin</th>
                <th>Erreur</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.id}</td>
                  <td>{job.action}</td>
                  <td>{job.status}</td>
                  <td>{job.course_title || job.course_id}</td>
                  <td>{job.chunks_created}</td>
                  <td>{formatShortDate(job.created_at)}</td>
                  <td>{formatShortDate(job.finished_at)}</td>
                  <td>{job.error_message || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </section>
  )
}

export default AdminRagPage
