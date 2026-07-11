import { ChevronDown, Eye, EyeOff, GraduationCap, Lock, Mail, User } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'
import { AuthFooter, AuthIntro } from './LoginPage.jsx'

const STUDY_LEVELS = [
  'Lycée',
  'Bac',
  'Bac+1',
  'Bac+2',
  'Bac+3 (Licence)',
  'Bac+4',
  'Bac+5 (Master / Ingénieur)',
  'Doctorat',
]

function RegisterPage() {
  const navigate = useNavigate()
  const { loginWithGoogle, register } = useAuth()
  const [authMessage, setAuthMessage] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showPasswordConfirmation, setShowPasswordConfirmation] = useState(false)

  async function handleRegister(event) {
    event.preventDefault()
    setAuthMessage('')

    const formData = new FormData(event.currentTarget)
    const fullName = formData.get('fullName')
    const email = formData.get('email')
    const password = formData.get('password')
    const passwordConfirmation = formData.get('passwordConfirmation')
    const studyLevel = formData.get('studyLevel')

    if (password !== passwordConfirmation) {
      setAuthMessage('Les mots de passe ne correspondent pas.')
      return
    }

    try {
      await register(email, password, fullName, studyLevel)
      navigate('/dashboard')
    } catch {
      setAuthMessage("Impossible de créer le compte Firebase.")
    }
  }

  async function handleGoogleRegister() {
    setAuthMessage('')

    try {
      await loginWithGoogle()
      navigate('/dashboard')
    } catch {
      setAuthMessage('Connexion Google indisponible pour le moment.')
    }
  }

  return (
    <div className="auth-page">
      <main className="auth-card">
        <AuthIntro />
        <form className="auth-panel register-panel" onSubmit={handleRegister}>
          <h1>Créer un compte</h1>
          <p>Rejoignez EduMentor AI et commencez votre parcours d'apprentissage dès aujourd'hui.</p>

          <label>
            Nom complet
            <span className="input-shell">
              <User size={22} />
              <input defaultValue="Wijdane Lamsadi" name="fullName" type="text" placeholder="Entrez votre nom complet" />
            </span>
          </label>
          <label>
            Adresse e-mail
            <span className="input-shell">
              <Mail size={22} />
              <input defaultValue="wijdane@exemple.com" name="email" type="email" placeholder="Entrez votre e-mail" />
            </span>
          </label>
          <label>
            Mot de passe
            <span className="input-shell">
              <Lock size={22} />
              <input
                defaultValue="demo2026"
                name="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Créez un mot de passe"
              />
              <button
                type="button"
                className="icon-toggle-button"
                onClick={() => setShowPassword((prev) => !prev)}
                aria-label={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
              >
                {showPassword ? <Eye size={20} /> : <EyeOff size={20} />}
              </button>
            </span>
          </label>
          <div className="password-strength"><span>Force du mot de passe :</span><strong>Faible</strong></div>
          <label>
            Confirmer le mot de passe
            <span className="input-shell">
              <Lock size={22} />
              <input
                defaultValue="demo2026"
                name="passwordConfirmation"
                type={showPasswordConfirmation ? 'text' : 'password'}
                placeholder="Confirmez votre mot de passe"
              />
              <button
                type="button"
                className="icon-toggle-button"
                onClick={() => setShowPasswordConfirmation((prev) => !prev)}
                aria-label={showPasswordConfirmation ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
              >
                {showPasswordConfirmation ? <Eye size={20} /> : <EyeOff size={20} />}
              </button>
            </span>
          </label>
          <label>
            Niveau d'études
            <span className="input-shell select-shell">
              <GraduationCap size={22} />
              <select name="studyLevel" defaultValue="">
                <option value="" disabled>Sélectionnez votre niveau</option>
                {STUDY_LEVELS.map((level) => (
                  <option key={level} value={level}>{level}</option>
                ))}
              </select>
              <ChevronDown size={20} />
            </span>
          </label>
          <label className="terms-row">
            <input type="checkbox" defaultChecked />
            J'accepte les Conditions d'utilisation et la Politique de confidentialité
          </label>
          {authMessage && <p className="form-link">{authMessage}</p>}
          <button className="primary-button auth-submit" type="submit">Créer mon compte</button>
          <div className="divider"><span>ou continuer avec</span></div>
          <button className="google-button" onClick={handleGoogleRegister} type="button">G Continuer avec Google</button>
          <p className="auth-switch">
            Vous avez déjà un compte ? <Link to="/login">Se connecter</Link>
          </p>
        </form>
      </main>
      <AuthFooter />
    </div>
  )
}

export default RegisterPage