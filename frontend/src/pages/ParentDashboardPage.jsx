import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getParentDashboard, getParentNotifications } from '../services/api.js'

function ParentDashboardPage() {
  const [dashboard, setDashboard] = useState({ children: [] })
  const [notifications, setNotifications] = useState([])
  const [message, setMessage] = useState('')

  useEffect(() => {
    Promise.all([getParentDashboard(), getParentNotifications()])
      .then(([data, notificationData]) => {
        setDashboard(data)
        setNotifications(notificationData.notifications || [])
      })
      .catch((err) => setMessage(err.message || 'Espace parent indisponible.'))
  }, [])

  return (
    <section className="page-section dashboard-page">
      <div className="page-heading">
        <h1>Tableau de bord parent</h1>
        <p>Suivi pedagogique des enfants lies a votre compte.</p>
      </div>
      {message && <article className="panel-card"><p>{message}</p></article>}

      <div className="dashboard-stats">
        <article className="metric-card"><p>Enfants lies</p><h2>{dashboard.children.length}</h2><strong>Acces verifie</strong></article>
        <article className="metric-card"><p>Notifications</p><h2>{notifications.length}</h2><strong>Dashboard, email, WhatsApp</strong></article>
        <article className="metric-card"><p>Regional</p><h2>1ere Bac</h2><strong>Indicateur pedagogique</strong></article>
      </div>

      <article className="panel-card">
        <div className="panel-title"><h2>Mes enfants</h2><p>{dashboard.children.length}</p></div>
        {dashboard.children.length > 0 ? dashboard.children.map((child) => (
          <div className="history-item" key={child.id}>
            <span>{Math.round(child.progression || 0)}%</span>
            <div>
              <strong>{child.full_name}</strong>
              <p>{child.school_year || 'Niveau scolaire non renseigne'} - {child.region || 'Region non renseignee'}</p>
              <small>Dernier score : {child.latest_score ?? 'Aucun resultat'}</small>
            </div>
            <Link to={`/parent/students/${child.id}`}>Voir le suivi</Link>
          </div>
        )) : <p>Aucun enfant n'est encore lie a votre compte.</p>}
      </article>

      <article className="panel-card">
        <div className="panel-title"><h2>Notifications recentes</h2><p>{notifications.length}</p></div>
        {notifications.slice(0, 5).map((notification) => (
          <div className="history-item" key={notification.id}>
            <span>{notification.severity || 'info'}</span>
            <div>
              <strong>{notification.title}</strong>
              <p>{notification.message}</p>
            </div>
          </div>
        ))}
      </article>
    </section>
  )
}

export default ParentDashboardPage
