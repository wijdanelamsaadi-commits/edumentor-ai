import { useEffect, useMemo, useState } from 'react'
import {
  Bell,
  Download,
  Eraser,
  LogOut,
  Moon,
  RotateCcw,
  Shield,
  Sun,
  User,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'
import { useTheme } from '../hooks/useTheme.js'
import {
  getNotificationPreferences,
  saveNotificationPreferences,
} from '../services/notifications.js'

const PREFERENCES_STORAGE_KEY = 'edumentor:preferences'

const DEFAULT_PREFERENCES = {
  language: 'Francais',
  explanationLevel: 'Standard',
  chatbotMiniQuiz: true,
  questionSuggestions: true,
  simulatedStreaming: true,
}

const LOCAL_USER_CACHE_KEYS = [
  'edumentor:userProfile',
  'diagnosticResult',
  'edumentor:chapterProgress',
  'edumentor:quizResults',
  'edumentor:notifications',
  'edumentor:chatSessions',
  'edumentor:chatXP',
  'edumentor:chatFeedback',
]

function SettingsPage() {
  const navigate = useNavigate()
  const { currentUser, logout, resetPassword, role, userProfile } = useAuth()
  const { resolvedTheme, setTheme, systemTheme, theme } = useTheme()
  const [preferences, setPreferences] = useState(() => readJson(PREFERENCES_STORAGE_KEY, DEFAULT_PREFERENCES))
  const [notificationPreferences, setNotificationPreferences] = useState(() => getNotificationPreferences())
  const [message, setMessage] = useState('')
  const [confirmAction, setConfirmAction] = useState(null)

  const provider = useMemo(() => {
    const providerId = currentUser?.providerData?.[0]?.providerId || 'password'
    return providerId === 'google.com' ? 'Google' : 'Email/Password'
  }, [currentUser])

  useEffect(() => {
    localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferences))
  }, [preferences])

  useEffect(() => {
    saveNotificationPreferences(notificationPreferences)
  }, [notificationPreferences])

  function updatePreference(field, value) {
    setPreferences((current) => ({ ...current, [field]: value }))
    setMessage('Preferences enregistrees.')
  }

  function updateNotificationPreference(field, value) {
    setNotificationPreferences((current) => ({ ...current, [field]: value }))
    setMessage('Preferences de notifications enregistrees.')
  }

  function exportUserData() {
    const data = {
      exported_at: new Date().toISOString(),
      user: {
        email: currentUser?.email || userProfile?.email || '',
        role,
        firebase_uid: currentUser?.uid || '',
      },
      localStorage: LOCAL_USER_CACHE_KEYS.reduce((items, key) => {
        items[key] = readJson(key, localStorage.getItem(key))
        return items
      }, {}),
      preferences,
      notificationPreferences,
      theme,
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `edumentor-data-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
    setMessage('Export des donnees genere.')
  }

  function clearChatHistory() {
    localStorage.removeItem('edumentor:chatSessions')
    localStorage.removeItem('edumentor:chatXP')
    localStorage.removeItem('edumentor:chatFeedback')
    setMessage('Historique local du chatbot efface.')
  }

  function clearLocalData() {
    LOCAL_USER_CACHE_KEYS.forEach((key) => localStorage.removeItem(key))
    setMessage('Caches locaux utilisateur supprimes. Les donnees PostgreSQL ne sont pas modifiees.')
  }

  async function handleResetPassword() {
    if (!currentUser?.email) {
      setMessage('Email indisponible pour la reinitialisation.')
      return
    }
    try {
      await resetPassword(currentUser.email)
      setMessage('Email de reinitialisation envoye.')
    } catch (error) {
      setMessage(error.message || 'Reinitialisation impossible.')
    }
  }

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  function runConfirmedAction() {
    if (confirmAction?.kind === 'clear-chat') clearChatHistory()
    if (confirmAction?.kind === 'clear-local') clearLocalData()
    setConfirmAction(null)
  }

  return (
    <section className="page-section dashboard-page settings-page">
      <div className="page-heading">
        <h1>Parametres</h1>
        <p>Personnalisez l'apparence, les preferences et les donnees locales de votre espace EduMentor AI.</p>
      </div>

      {message && <article className="progress-banner"><span><Shield size={28} /></span><p>{message}</p></article>}

      <div className="settings-grid">
        <SettingsCard icon={Sun} title="Apparence" text={`Theme applique : ${resolvedTheme}. Systeme : ${systemTheme}.`}>
          <div className="settings-choice-group" role="radiogroup" aria-label="Theme de l'application">
            <ThemeChoice checked={theme === 'light'} icon={Sun} label="Theme clair" onChange={() => setTheme('light')} />
            <ThemeChoice checked={theme === 'dark'} icon={Moon} label="Theme sombre" onChange={() => setTheme('dark')} />
            <ThemeChoice checked={theme === 'system'} icon={RotateCcw} label="Utiliser le theme du systeme" onChange={() => setTheme('system')} />
          </div>
        </SettingsCard>

        <SettingsCard icon={User} title="Preferences d'apprentissage" text="Ces preferences sont conservees localement pour preparer la personnalisation frontend.">
          <div className="settings-form-grid">
            <label>
              Langue preferee
              <select onChange={(event) => updatePreference('language', event.target.value)} value={preferences.language}>
                <option>Francais</option>
                <option>العربية</option>
                <option>English</option>
                <option>Darija</option>
              </select>
            </label>
            <label>
              Niveau d'explication prefere
              <select onChange={(event) => updatePreference('explanationLevel', event.target.value)} value={preferences.explanationLevel}>
                <option>Simple</option>
                <option>Standard</option>
                <option>Detaille</option>
              </select>
            </label>
          </div>
          <SettingsSwitch checked={preferences.chatbotMiniQuiz} label="Activer les mini-quiz du chatbot" onChange={(value) => updatePreference('chatbotMiniQuiz', value)} />
          <SettingsSwitch checked={preferences.questionSuggestions} label="Activer les suggestions de questions" onChange={(value) => updatePreference('questionSuggestions', value)} />
          <SettingsSwitch checked={preferences.simulatedStreaming} label="Activer le streaming simule des reponses" onChange={(value) => updatePreference('simulatedStreaming', value)} />
        </SettingsCard>

        <SettingsCard icon={Bell} title="Notifications" text="Les notifications desactivees ne seront plus creees localement.">
          <SettingsSwitch checked={notificationPreferences.progress} label="Progression des cours" onChange={(value) => updateNotificationPreference('progress', value)} />
          <SettingsSwitch checked={notificationPreferences.quiz} label="Resultats des quiz" onChange={(value) => updateNotificationPreference('quiz', value)} />
          <SettingsSwitch checked={notificationPreferences.chapters} label="Nouveaux chapitres" onChange={(value) => updateNotificationPreference('chapters', value)} />
          <SettingsSwitch checked={notificationPreferences.chatbot} label="Reponses du chatbot" onChange={(value) => updateNotificationPreference('chatbot', value)} />
          <SettingsSwitch checked={notificationPreferences.pdf} label="Supports pedagogiques" onChange={(value) => updateNotificationPreference('pdf', value)} />
        </SettingsCard>

        <SettingsCard icon={Eraser} title="Donnees et confidentialite" text="Les actions destructives demandent une confirmation.">
          <div className="settings-actions">
            <button className="outline-button" onClick={exportUserData} type="button"><Download size={18} /> Exporter mes donnees</button>
            <button className="outline-button" onClick={() => setConfirmAction({ kind: 'clear-chat', title: "Effacer l'historique du chatbot", text: 'Cette action supprime uniquement les conversations locales.' })} type="button"><Eraser size={18} /> Effacer l'historique du chatbot</button>
            <button className="outline-button" onClick={() => setMessage("Reinitialiser la progression n'est pas encore disponible : aucun endpoint backend adapte n'existe pour cette action.")} type="button"><RotateCcw size={18} /> Reinitialiser ma progression</button>
            <button className="outline-button danger-button" onClick={() => setConfirmAction({ kind: 'clear-local', title: 'Supprimer les donnees locales', text: 'Cette action supprime les caches localStorage du compte courant, sans modifier PostgreSQL.' })} type="button"><Eraser size={18} /> Supprimer les donnees locales</button>
          </div>
        </SettingsCard>

        <SettingsCard icon={User} title="Compte" text="Les roles sont lus depuis PostgreSQL et ne sont pas modifiables ici.">
          <div className="settings-account-list">
            <span><strong>Nom</strong>{userProfile?.full_name || currentUser?.displayName || currentUser?.email?.split('@')[0] || '--'}</span>
            <span><strong>Email</strong>{userProfile?.email || currentUser?.email || '--'}</span>
            <span><strong>Role</strong>{role}</span>
            <span><strong>Fournisseur de connexion</strong>{provider}</span>
          </div>
          <div className="settings-actions">
            <button className="outline-button" onClick={() => window.dispatchEvent(new Event('edumentor:openProfilePanel'))} type="button"><User size={18} /> Modifier le profil</button>
            {provider === 'Email/Password' && (
              <button className="outline-button" onClick={handleResetPassword} type="button"><RotateCcw size={18} /> Reinitialiser le mot de passe</button>
            )}
            <button className="primary-button" onClick={handleLogout} type="button"><LogOut size={18} /> Se deconnecter</button>
          </div>
        </SettingsCard>
      </div>

      {confirmAction && (
        <div className="settings-modal-backdrop" role="presentation" onMouseDown={() => setConfirmAction(null)}>
          <section className="settings-modal panel-card" role="dialog" aria-modal="true" aria-labelledby="settings-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <h2 id="settings-confirm-title">{confirmAction.title}</h2>
            <p>{confirmAction.text}</p>
            <div className="settings-actions">
              <button className="outline-button" onClick={() => setConfirmAction(null)} type="button">Annuler</button>
              <button className="primary-button" onClick={runConfirmedAction} type="button">Confirmer</button>
            </div>
          </section>
        </div>
      )}
    </section>
  )
}

function SettingsCard({ children, icon: Icon, text, title }) {
  return (
    <article className="panel-card settings-card">
      <div className="panel-title">
        <div>
          <span className="soft-icon"><Icon size={26} /></span>
          <h2>{title}</h2>
          <p>{text}</p>
        </div>
      </div>
      {children}
    </article>
  )
}

function ThemeChoice({ checked, icon: Icon, label, onChange }) {
  return (
    <label className={checked ? 'settings-theme-choice active' : 'settings-theme-choice'}>
      <input checked={checked} name="theme" onChange={onChange} type="radio" />
      <Icon size={20} />
      {label}
    </label>
  )
}

function SettingsSwitch({ checked, label, onChange }) {
  return (
    <label className="settings-switch">
      <span>{label}</span>
      <button
        aria-checked={checked}
        aria-label={label}
        className={checked ? 'switch-control active' : 'switch-control'}
        onClick={() => onChange(!checked)}
        role="switch"
        type="button"
      >
        <span />
      </button>
    </label>
  )
}

function readJson(key, fallback) {
  try {
    const value = localStorage.getItem(key)
    if (!value) return fallback
    return JSON.parse(value)
  } catch {
    return fallback
  }
}

export default SettingsPage
