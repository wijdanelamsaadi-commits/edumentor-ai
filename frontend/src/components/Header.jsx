import {
  BarChart3,
  Bell,
  BookOpen,
  Brain,
  Calendar,
  Camera,
  Check,
  CheckCheck,
  ChevronDown,
  ClipboardList,
  FileText,
  Mail,
  PenLine,
  Save,
  Trash2,
  User,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import avatarUrl from '../assets/learner-avatar.jpg'
import { useAuth } from '../hooks/useAuth.js'
import { useUserData } from '../hooks/useUserData.js'
import { updateUserProfile } from '../services/api.js'
import {
  addNotification,
  clearNotifications,
  deleteNotification,
  getNotifications,
  markAllNotificationsAsRead,
  markNotificationAsRead,
  NOTIFICATIONS_UPDATED_EVENT,
} from '../services/notifications.js'

const USER_PROFILE_STORAGE_KEY = 'edumentor:userProfile'

const DEFAULT_USER_PROFILE = {
  fullName: 'Wijdane Lamsadi',
  email: 'wijdane@edumentor.ai',
  role: 'Apprenante en IA',
  registeredAt: 'Mai 2024',
  photo: '',
}

function Header() {
  const { currentUser } = useAuth()
  const {
    diagnosticResult,
    notifications: bootNotifications,
    profile: bootProfile,
  } = useUserData()
  const fileInputRef = useRef(null)
  const [isProfileOpen, setIsProfileOpen] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [profile, setProfile] = useState(() => readUserProfile())
  const [draftProfile, setDraftProfile] = useState(() => readUserProfile())
  const [currentLevel, setCurrentLevel] = useState('Non défini')
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false)
  const [notifications, setNotifications] = useState(() => getNotifications())

  const applyBootstrappedUserData = useCallback(() => {
    const nextProfile = bootProfile || readUserProfile(currentUser)
    setProfile(nextProfile)
    setDraftProfile(nextProfile)
    setCurrentLevel(diagnosticResult?.level || nextProfile?.level || readCurrentLevel())
    setNotifications(bootNotifications?.length ? bootNotifications : getNotifications())
  }, [bootNotifications, bootProfile, currentUser, diagnosticResult])

  const openProfilePanel = useCallback(() => {
    const nextProfile = readUserProfile(currentUser)
    setProfile(nextProfile)
    setDraftProfile(nextProfile)
    setCurrentLevel(readCurrentLevel())
    setIsNotificationsOpen(false)
    setIsEditing(false)
    setIsProfileOpen(true)
    applyBootstrappedUserData()
  }, [applyBootstrappedUserData, currentUser])

  useEffect(() => {
    applyBootstrappedUserData()

    function handleRefresh() {
      applyBootstrappedUserData()
    }

    window.addEventListener('storage', handleRefresh)
    window.addEventListener('focus', handleRefresh)
    window.addEventListener(NOTIFICATIONS_UPDATED_EVENT, refreshNotifications)
    window.addEventListener('edumentor:openProfilePanel', openProfilePanel)

    return () => {
      window.removeEventListener('storage', handleRefresh)
      window.removeEventListener('focus', handleRefresh)
      window.removeEventListener(NOTIFICATIONS_UPDATED_EVENT, refreshNotifications)
      window.removeEventListener('edumentor:openProfilePanel', openProfilePanel)
    }
  }, [applyBootstrappedUserData, openProfilePanel])

  function refreshNotifications() {
    setNotifications(getNotifications())
  }

  function toggleNotificationsPanel() {
    setIsProfileOpen(false)
    setIsNotificationsOpen((isOpen) => !isOpen)
  }

  function closeProfilePanel() {
    setIsProfileOpen(false)
    setIsEditing(false)
    setDraftProfile(profile)
  }

  function updateDraft(field, value) {
    setDraftProfile((current) => ({
      ...current,
      [field]: value,
    }))
  }

  function handlePhotoChange(event) {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = () => {
      updateDraft('photo', reader.result)
    }
    reader.readAsDataURL(file)
  }

  function saveProfile() {
    const hadPhotoChange = draftProfile.photo !== profile.photo
    const nextProfile = {
      ...DEFAULT_USER_PROFILE,
      ...draftProfile,
      fullName: draftProfile.fullName.trim() || DEFAULT_USER_PROFILE.fullName,
      email: draftProfile.email.trim() || DEFAULT_USER_PROFILE.email,
      role: profile.role || DEFAULT_USER_PROFILE.role,
    }

    localStorage.setItem(USER_PROFILE_STORAGE_KEY, JSON.stringify(nextProfile))
    updateUserProfile(toBackendProfile(nextProfile, currentLevel))
      .then((updatedProfile) => {
        const syncedProfile = normalizeBackendProfile(updatedProfile)
        localStorage.setItem(USER_PROFILE_STORAGE_KEY, JSON.stringify(syncedProfile))
        setProfile(syncedProfile)
        setDraftProfile(syncedProfile)
      })
      .catch(() => {})
    addNotification({
      type: 'profile',
      title: 'Profil modifié',
      message: 'Vos informations personnelles ont été mises à jour.',
    })
    if (hadPhotoChange) {
      addNotification({
        type: 'profile',
        title: 'Photo de profil mise à jour',
        message: 'Votre nouvelle photo de profil est maintenant affichée.',
      })
    }
    setProfile(nextProfile)
    setDraftProfile(nextProfile)
    setIsEditing(false)
  }

  const displayedPhoto = profile.photo || avatarUrl
  const draftPhoto = draftProfile.photo || avatarUrl
  const displayName = profile.fullName?.split(' ')[0] || 'Wijdane'
  const unreadCount = notifications.filter((notification) => !notification.read).length

  return (
    <header className="topbar">
      <div className="topbar-spacer" />
      <button className="notification-button" onClick={toggleNotificationsPanel} type="button" aria-label="Notifications">
        <Bell size={24} />
        {unreadCount > 0 && <span>{unreadCount}</span>}
      </button>
      <button className="profile-pill" onClick={openProfilePanel} type="button" aria-label="Ouvrir le profil personnel">
        <img src={displayedPhoto} alt="" />
        <strong>{displayName}</strong>
        <ChevronDown size={18} />
      </button>

      {isProfileOpen && (
        <div className="profile-panel-backdrop" role="presentation" onMouseDown={closeProfilePanel}>
          <aside
            className="profile-panel panel-card"
            aria-label="Profil personnel"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="profile-panel-header">
              <div>
                <p>Profil personnel</p>
                <h2>{isEditing ? 'Modifier le profil' : profile.fullName}</h2>
              </div>
              <button className="icon-button" onClick={closeProfilePanel} type="button" aria-label="Fermer le profil">
                <X size={20} />
              </button>
            </div>

            <div className="profile-panel-identity">
              <img src={draftPhoto} alt="" />
              {isEditing && (
                <>
                  <input
                    accept="image/*"
                    className="sr-only"
                    onChange={handlePhotoChange}
                    ref={fileInputRef}
                    type="file"
                  />
                  <button className="outline-button" onClick={() => fileInputRef.current?.click()} type="button">
                    <Camera size={18} />
                    Changer la photo
                  </button>
                </>
              )}
            </div>

            {isEditing ? (
              <div className="profile-edit-form">
                <label>
                  Nom complet
                  <input
                    onChange={(event) => updateDraft('fullName', event.target.value)}
                    type="text"
                    value={draftProfile.fullName}
                  />
                </label>
                <label>
                  Email
                  <input
                    onChange={(event) => updateDraft('email', event.target.value)}
                    type="email"
                    value={draftProfile.email}
                  />
                </label>
                <div className="profile-readonly-field">
                  <span>Rôle</span>
                  <strong>{profile.role}</strong>
                </div>
                <div className="profile-panel-actions">
                  <button className="primary-button" onClick={saveProfile} type="button">
                    <Save size={18} />
                    Enregistrer
                  </button>
                  <button
                    className="outline-button"
                    onClick={() => {
                      setDraftProfile(profile)
                      setIsEditing(false)
                    }}
                    type="button"
                  >
                    Annuler
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="profile-detail-list">
                  <span><User size={18} />{profile.role}</span>
                  <span><Mail size={18} />{profile.email}</span>
                  <span><Calendar size={18} />Inscrite depuis {profile.registeredAt}</span>
                  <span><ChevronDown size={18} />Niveau actuel : {currentLevel}</span>
                </div>
                <button className="outline-button" onClick={() => setIsEditing(true)} type="button">
                  <PenLine size={18} />
                  Modifier le profil
                </button>
              </>
            )}
          </aside>
        </div>
      )}

      {isNotificationsOpen && (
        <div className="profile-panel-backdrop" role="presentation" onMouseDown={() => setIsNotificationsOpen(false)}>
          <aside
            className="notifications-panel panel-card"
            aria-label="Centre de notifications"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="profile-panel-header">
              <div>
                <p>Notifications</p>
                <h2>Centre de notifications</h2>
              </div>
              <button className="icon-button" onClick={() => setIsNotificationsOpen(false)} type="button" aria-label="Fermer les notifications">
                <X size={20} />
              </button>
            </div>

            <div className="notifications-actions">
              <button
                className="outline-button"
                disabled={notifications.length === 0 || unreadCount === 0}
                onClick={markAllNotificationsAsRead}
                type="button"
              >
                <CheckCheck size={18} />
                Tout marquer comme lu
              </button>
              <button
                className="outline-button"
                disabled={notifications.length === 0}
                onClick={clearNotifications}
                type="button"
              >
                <Trash2 size={18} />
                Vider
              </button>
            </div>

            <div className="notifications-list">
              {notifications.length > 0 ? notifications.map((notification) => {
                const Icon = getNotificationIcon(notification.type)
                return (
                  <article className={notification.read ? 'notification-item read' : 'notification-item'} key={notification.id}>
                    <span className="notification-icon"><Icon size={20} /></span>
                    <div>
                      <div className="notification-title-row">
                        <strong>{notification.title}</strong>
                        {!notification.read && <em>Non lu</em>}
                      </div>
                      <p>{notification.message}</p>
                      <time>{formatNotificationDate(notification.date)}</time>
                      <div className="notification-inline-actions">
                        {!notification.read && (
                          <button onClick={() => markNotificationAsRead(notification.id)} type="button">
                            <Check size={16} />
                            Marquer comme lue
                          </button>
                        )}
                        <button onClick={() => deleteNotification(notification.id)} type="button">
                          <Trash2 size={16} />
                          Supprimer
                        </button>
                      </div>
                    </div>
                  </article>
                )
              }) : (
                <article className="notification-empty">
                  <Bell size={32} />
                  <strong>Aucune notification</strong>
                  <p>Vos alertes importantes apparaîtront ici.</p>
                </article>
              )}
            </div>
          </aside>
        </div>
      )}
    </header>
  )
}

function normalizeBackendProfile(profile) {
  if (!profile) {
    return DEFAULT_USER_PROFILE
  }

  return {
    ...DEFAULT_USER_PROFILE,
    fullName: profile.full_name || profile.fullName || DEFAULT_USER_PROFILE.fullName,
    email: profile.email || DEFAULT_USER_PROFILE.email,
    role: profile.role || DEFAULT_USER_PROFILE.role,
    level: profile.level,
    registeredAt: profile.registration_date || profile.registeredAt || DEFAULT_USER_PROFILE.registeredAt,
    photo: profile.photo || '',
  }
}

function toBackendProfile(profile, level) {
  return {
    full_name: profile.fullName,
    email: profile.email,
    level,
    registration_date: profile.registeredAt,
    photo: profile.photo || null,
  }
}

function readUserProfile(firebaseUser = null) {
  const fallbackProfile = getFirebaseProfile(firebaseUser)
  try {
    const storedProfile = localStorage.getItem(USER_PROFILE_STORAGE_KEY)
    return storedProfile ? { ...fallbackProfile, ...JSON.parse(storedProfile) } : fallbackProfile
  } catch {
    return fallbackProfile
  }
}

function getFirebaseProfile(firebaseUser) {
  if (!firebaseUser) {
    return DEFAULT_USER_PROFILE
  }

  const email = firebaseUser.email || DEFAULT_USER_PROFILE.email
  return {
    ...DEFAULT_USER_PROFILE,
    fullName: firebaseUser.displayName || email.split('@')[0] || DEFAULT_USER_PROFILE.fullName,
    email,
    photo: firebaseUser.photoURL || '',
  }
}

function readCurrentLevel() {
  try {
    const diagnosticResult = JSON.parse(localStorage.getItem('diagnosticResult') || 'null')
    return diagnosticResult?.level || 'Non défini'
  } catch {
    return 'Non défini'
  }
}

function getNotificationIcon(type) {
  const icons = {
    chatbot: Brain,
    diagnostic: BarChart3,
    pdf: FileText,
    profile: User,
    progress: BookOpen,
    quiz: ClipboardList,
  }

  return icons[type] || Bell
}

function formatNotificationDate(dateValue) {
  const date = new Date(dateValue)
  if (Number.isNaN(date.getTime())) {
    return 'Maintenant'
  }

  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export default Header
