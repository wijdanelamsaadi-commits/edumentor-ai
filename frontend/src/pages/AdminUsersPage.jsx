import { useEffect, useMemo, useState } from 'react'
import { Search, Trash2, UserCog } from 'lucide-react'
import { AdminLoading, AdminMessage } from '../components/admin/AdminShared.jsx'
import {
  deleteAdminUser,
  fetchAdminUsers,
  getAdminParentStudents,
  linkAdminParentStudent,
  unlinkAdminParentStudent,
  updateAdminUserRole,
  updateAdminUserStatus,
} from '../services/api.js'
import { formatDate, formatTime, normalizeLevel } from '../utils/adminFormat.js'

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'professor', label: 'Professeur', actionLabel: 'Professor' },
  { value: 'student', label: 'Étudiant', actionLabel: 'Student' },
  { value: 'parent', label: 'Parent' },
]

function AdminUsersPage() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [filters, setFilters] = useState({ level: 'all', query: '', role: 'all', status: 'all' })
  const [parentModal, setParentModal] = useState({ open: false, parent: null, children: [], query: '', loading: false, message: '' })

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

  async function openParentModal(parent) {
    setParentModal({ open: true, parent, children: [], query: '', loading: true, message: '' })
    try {
      const data = await getAdminParentStudents(parent.id)
      setParentModal((current) => ({ ...current, children: data.children || [], loading: false }))
    } catch (error) {
      setParentModal((current) => ({ ...current, loading: false, message: error.message || 'Chargement des enfants impossible.' }))
    }
  }

  async function refreshParentChildren() {
    if (!parentModal.parent) return
    setParentModal((current) => ({ ...current, loading: true, message: '' }))
    try {
      const data = await getAdminParentStudents(parentModal.parent.id)
      setParentModal((current) => ({ ...current, children: data.children || [], loading: false }))
    } catch (error) {
      setParentModal((current) => ({ ...current, loading: false, message: error.message || 'Chargement des enfants impossible.' }))
    }
  }

  async function handleLinkStudent(student) {
    if (!parentModal.parent) return
    try {
      await linkAdminParentStudent(parentModal.parent.id, student.id)
      await refreshParentChildren()
      setParentModal((current) => ({ ...current, query: '', message: 'Étudiant associé au parent.' }))
    } catch (error) {
      setParentModal((current) => ({ ...current, message: error.message || 'Association impossible.' }))
    }
  }

  async function handleUnlinkStudent(studentId) {
    if (!parentModal.parent) return
    if (!window.confirm('Dissocier cet étudiant du parent ?')) return
    try {
      await unlinkAdminParentStudent(parentModal.parent.id, studentId)
      await refreshParentChildren()
      setParentModal((current) => ({ ...current, message: 'Étudiant dissocié du parent.' }))
    } catch (error) {
      setParentModal((current) => ({ ...current, message: error.message || 'Dissociation impossible.' }))
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

  const studentSearchResults = useMemo(() => {
    const cleanQuery = parentModal.query.trim().toLowerCase()
    const linkedIds = new Set(parentModal.children.map((child) => child.student_id))
    return users
      .filter((user) => user.role === 'student')
      .filter((user) => !linkedIds.has(user.id))
      .filter((user) => !cleanQuery || user.full_name.toLowerCase().includes(cleanQuery) || user.email.toLowerCase().includes(cleanQuery))
      .slice(0, 8)
  }, [parentModal.children, parentModal.query, users])

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
            <option value="all">Tous les rôles</option>
            {ROLE_OPTIONS.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
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
                  <td><em className="admin-pill">{formatRole(user.role)}</em></td>
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
                        {ROLE_OPTIONS.map((role) => (
                          <option key={role.value} value={role.value}>{role.actionLabel || role.label}</option>
                        ))}
                      </select>
                      <button onClick={() => handleRoleChange(user, user.role === 'admin' ? 'student' : 'admin')} type="button">
                        <UserCog size={16} />
                        {user.role === 'admin' ? 'Retrograder' : 'Promouvoir'}
                      </button>
                      <button onClick={() => handleStatusChange(user)} type="button">
                        {user.status === 'disabled' ? 'Activer' : 'Desactiver'}
                      </button>
                      {user.role === 'parent' && (
                        <button onClick={() => openParentModal(user)} type="button">
                          Gérer les enfants
                        </button>
                      )}
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
      {parentModal.open && (
        <div className="admin-modal-backdrop" role="presentation" onMouseDown={() => setParentModal({ open: false, parent: null, children: [], query: '', loading: false, message: '' })}>
          <section className="admin-modal panel-card" role="dialog" aria-modal="true" aria-labelledby="admin-parent-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-title">
              <div>
                <h2 id="admin-parent-modal-title">Gérer les enfants</h2>
                <p>{parentModal.parent?.full_name} - {parentModal.parent?.email}</p>
              </div>
              <button className="outline-button" onClick={() => setParentModal({ open: false, parent: null, children: [], query: '', loading: false, message: '' })} type="button">Fermer</button>
            </div>
            {parentModal.message && <AdminMessage message={parentModal.message} />}
            {parentModal.loading ? <p className="admin-empty">Chargement...</p> : (
              <>
                <h3>Enfants actuellement liés</h3>
                <div className="admin-linked-list">
                  {parentModal.children.length ? parentModal.children.map((child) => (
                    <div className="history-item" key={child.student_id}>
                      <span>{child.status}</span>
                      <div>
                        <strong>{child.student_name}</strong>
                        <p>{child.student_email}</p>
                      </div>
                      <button onClick={() => handleUnlinkStudent(child.student_id)} type="button">Dissocier</button>
                    </div>
                  )) : <p className="admin-empty">Aucun enfant lié à ce parent.</p>}
                </div>

                <h3>Ajouter un enfant</h3>
                <label className="admin-search parent-student-search">
                  <Search size={18} />
                  <input
                    onChange={(event) => setParentModal((current) => ({ ...current, query: event.target.value }))}
                    placeholder="Rechercher un étudiant par nom ou email"
                    value={parentModal.query}
                  />
                </label>
                <div className="admin-linked-list">
                  {studentSearchResults.map((student) => (
                    <div className="history-item" key={student.id}>
                      <span>Student</span>
                      <div>
                        <strong>{student.full_name}</strong>
                        <p>{student.email}</p>
                      </div>
                      <button onClick={() => handleLinkStudent(student)} type="button">Associer</button>
                    </div>
                  ))}
                  {studentSearchResults.length === 0 && <p className="admin-empty">Aucun étudiant disponible pour cette recherche.</p>}
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </section>
  )
}

export default AdminUsersPage

function formatRole(role) {
  const option = ROLE_OPTIONS.find((item) => item.value === role)
  return option?.label || role || '--'
}
