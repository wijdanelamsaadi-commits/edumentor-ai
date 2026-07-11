export function getBarWidth(count, total) {
  if (!total) return count > 0 ? 100 : 0
  return Math.max(6, Math.round((count / total) * 100))
}

export function normalizeLevel(level) {
  const clean = String(level || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  if (clean.includes('debut')) return 'debutant'
  if (clean.includes('avanc')) return 'avance'
  return 'intermediaire'
}

export function formatShortDate(dateValue) {
  if (!dateValue) return '--'
  return formatDate(dateValue)
}

export function formatDate(dateValue) {
  const date = new Date(dateValue)
  if (Number.isNaN(date.getTime())) return '--'
  return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(date)
}

export function formatTime(dateValue) {
  const date = new Date(dateValue)
  if (Number.isNaN(date.getTime())) return '--'
  return new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' }).format(date)
}

export function formatAuditAction(action) {
  const labels = {
    create_course: 'Creation cours',
    update_course: 'Modification cours',
    delete_course: 'Suppression cours',
    upload_pdf: 'Upload PDF',
    replace_pdf: 'Remplacement PDF',
    delete_pdf: 'Suppression PDF',
    update_role: 'Changement role',
    enable_user: 'Activation',
    disable_user: 'Desactivation',
    delete_user: 'Suppression utilisateur',
    reindex_rag: 'Reindexation RAG',
  }
  return labels[action] || action
}

export function formatAuditTarget(target) {
  const labels = {
    course: 'Cours',
    course_pdf: 'PDF',
    user: 'Utilisateur',
    rag: 'RAG',
  }
  return labels[target] || target
}

export function delay(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}
