import { useEffect, useState } from 'react'
import { Database, FileText, RefreshCw } from 'lucide-react'
import { ActivityIcon, AdminLoading, AdminMessage, AdminMetric } from '../components/admin/AdminShared.jsx'
import { fetchAdminRagStatus, reindexAdminRag } from '../services/api.js'
import { delay, formatShortDate, formatTime } from '../utils/adminFormat.js'

function AdminRagPage() {
  const [ragStatus, setRagStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [ragLoading, setRagLoading] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadRagStatus()
  }, [])

  async function loadRagStatus() {
    setLoading(true)
    setMessage('')
    try {
      setRagStatus(await fetchAdminRagStatus())
    } catch {
      setMessage('Impossible de charger le statut RAG.')
    } finally {
      setLoading(false)
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
    </section>
  )
}

export default AdminRagPage
