import { BarChart3, BookOpen, ShieldCheck } from 'lucide-react'

export function AdminLoading({ text = 'Chargement des donnees administrateur...' }) {
  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Tableau de bord admin</h1>
        <p>{text}</p>
      </div>
    </section>
  )
}

export function AdminMessage({ message }) {
  if (!message) return null
  return <article className="progress-banner"><span><ShieldCheck size={28} /></span><p>{message}</p></article>
}

export function AdminMetric({ icon: Icon, label, text, value }) {
  return (
    <article className="metric-card">
      <span className="soft-icon"><Icon size={38} /></span>
      <p>{label}</p>
      <h2>{value}</h2>
      <strong>{text}</strong>
    </article>
  )
}

export function AnalyticsPanel({ rows, title }) {
  const max = rows.reduce((highest, [, value]) => {
    const numeric = Number(String(value).replace('%', '')) || 0
    return Math.max(highest, numeric)
  }, 1)

  return (
    <article className="admin-analytics-card">
      <h3>{title}</h3>
      <div className="admin-bars">
        {rows.map(([label, value]) => {
          const numeric = Number(String(value).replace('%', '')) || 0
          return (
            <div className="admin-bar-row" key={label}>
              <span>{label}</span>
              <div className="progress-track"><span style={{ width: `${Math.max(8, Math.round((numeric / max) * 100))}%` }} /></div>
              <strong>{value}</strong>
            </div>
          )
        })}
      </div>
    </article>
  )
}

export function RankingList({ items, metric, title }) {
  return (
    <article className="panel-card admin-nested-panel">
      <div className="panel-title"><h2>{title}</h2></div>
      {(items || []).length > 0 ? items.map((item) => (
        <div className="history-item" key={`${title}-${item.course_id}`}>
          <span><BookOpen size={22} /></span>
          <div>
            <strong>{item.title}</strong>
            <p>{item.count ?? item.average_score ?? 0} {metric}</p>
          </div>
          <time>#{item.course_id}</time>
        </div>
      )) : (
        <p className="admin-empty">Aucune donnee disponible.</p>
      )}
    </article>
  )
}

export function ActivityIcon(props) {
  return <BarChart3 {...props} />
}
