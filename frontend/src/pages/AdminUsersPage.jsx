import { useEffect, useMemo, useState } from 'react'
import { Search, Trash2, UserCog } from 'lucide-react'
import { AdminLoading, AdminMessage } from '../components/admin/AdminShared.jsx'
import { deleteAdminUser, fetchAdminUsers, updateAdminUserRole, updateAdminUserStatus } from '../services/api.js'
import { formatDate, formatTime, normalizeLevel } from '../utils/adminFormat.js'

function AdminUsersPage() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [filters, setFilters] = useState({ level: 'all', query: '', role: 'all', status: 'all' })

  useEffect(() => {
    loadUsers()
  }, [])

  async function loadUsers() {
    setLoading(true)
    setMessage('')
    try {
      const usersData = await fetchAdminUsers()
      setUsers(Array.isArray(usersData) ? usersData : [])
    } catch {
      setMessage('Impossible de charger les utilisateurs.')
    } finally {
      setLoading(false)
    }
  }

  async function handleRoleChange(user, role) {
    if (user.role === role) return
    if (!window.confirm(`Confirmer le changement de role pour ${user.email} ?`)) return

    try {
      await updateAdminUserRole(user.id, role)
      await loadUsers()
      setMessage('Role utilisateur mis a jour.')
    } catch (error) {
      setMessage(error.message || 'Changement de role impossible.')
    }
  }

  async function handleStatusChange(user) {
    const nextStatus = user.status === 'disabled' ? 'active' : 'disabled'
    if (!window.confirm(`Confirmer le statut ${nextStatus} pour ${user.email} ?`)) return

    try {
      await updateAdminUserStatus(user.id, nextStatus)
      await loadUsers()
      setMessage('Statut utilisateur mis a jour.')
    } catch (error) {
      setMessage(error.message || 'Changement de statut impossible.')
    }
  }

  async function handleDelete(user) {
    if (!window.confirm(`Supprimer le profil PostgreSQL de ${user.email} ? Le compte Firebase Auth ne sera pas supprime.`)) return

    try {
      await deleteAdminUser(user.id)
      await loadUsers()
      setMessage('Profil PostgreSQL supprime. Le compte Firebase Auth reste conserve.')
    } catch (error) {
      setMessage(error.message || 'Suppression impossible.')
    }
  }

  const filteredUsers = useMemo(() => {
    const cleanQuery = filters.query.trim().toLowerCase()
    return users.filter((user) => {
      const matchesQuery = !cleanQuery
        || user.full_name.toLowerCase().includes(cleanQuery)
        || user.email.toLowerCase().includes(cleanQuery)
      const matchesRole = filters.role === 'all' || user.role === filters.role
      const matchesLevel = filters.level === 'all' || normalizeLevel(user.level) === filters.level
      const matchesStatus = filters.status === 'all' || user.status === filters.status
      return matchesQuery && matchesRole && matchesLevel && matchesStatus
    })
  }, [filters, users])

  if (loading) return <AdminLoading text="Chargement des utilisateurs..." />

  return (
    <section className="page-section dashboard-page admin-page">
      <div className="page-heading">
        <h1>Utilisateurs</h1>
        <p>Gestion des roles et statuts stockes dans PostgreSQL.</p>
      </div>

      <AdminMessage message={message} />

      <article className="panel-card admin-users-panel">
        <div className="panel-title">
          <div>
            <h2>Utilisateurs</h2>
            <p>Recherche, filtres et actions administrateur.</p>
          </div>
          <button className="outline-button" onClick={loadUsers} type="button">Actualiser</button>
        </div>

        <div className="admin-filters">
          <label className="admin-search">
            <Search size={18} />
            <input
              onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
              placeholder="Rechercher nom ou email"
              value={filters.query}
            />
          </label>
          <select onChange={(event) => setFilters((current) => ({ ...current, role: event.target.value }))} value={filters.role}>
            <option value="all">Tous les roles</option>
            <option value="admin">Admin</option>
            <option value="professor">Professor</option>
            <option value="student">Student</option>
          </select>
          <select onChange={(event) => setFilters((current) => ({ ...current, level: event.target.value }))} value={filters.level}>
            <option value="all">Tous les niveaux</option>
            <option value="debutant">Debutant</option>
            <option value="intermediaire">Intermediaire</option>
            <option value="avance">Avance</option>
          </select>
          <select onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))} value={filters.status}>
            <option value="all">Tous les statuts</option>
            <option value="active">Actif</option>
            <option value="disabled">Desactive</option>
          </select>
        </div>

        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Role</th>
                <th>Niveau</th>
                <th>Statut</th>
                <th>Derniere activite</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr key={user.id}>
                  <td><strong>{user.full_name}</strong><span>{user.email}</span></td>
                  <td><em className="admin-pill">{user.role}</em></td>
                  <td>{user.level || '--'}</td>
                  <td><em className={user.status === 'disabled' ? 'admin-pill muted' : 'admin-pill'}>{user.status}</em></td>
                  <td>{user.last_activity ? `${formatDate(user.last_activity)} ${formatTime(user.last_activity)}` : '--'}</td>
                  <td>
                    <div className="admin-actions">
                      <select
                        aria-label={`Changer le role de ${user.email}`}
                        onChange={(event) => handleRoleChange(user, event.target.value)}
                        value={user.role}
                      >
                        <option value="student">Student</option>
                        <option value="professor">Professor</option>
                        <option value="admin">Admin</option>
                      </select>
                      <button onClick={() => handleRoleChange(user, user.role === 'admin' ? 'student' : 'admin')} type="button">
                        <UserCog size={16} />
                        {user.role === 'admin' ? 'Retrograder' : 'Promouvoir'}
                      </button>
                      <button onClick={() => handleStatusChange(user)} type="button">
                        {user.status === 'disabled' ? 'Activer' : 'Desactiver'}
                      </button>
                      <button onClick={() => handleDelete(user)} type="button">
                        <Trash2 size={16} />
                        Supprimer
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredUsers.length === 0 && <p className="admin-empty">Aucun utilisateur ne correspond aux filtres.</p>}
        </div>
      </article>
    </section>
  )
}

export default AdminUsersPage
