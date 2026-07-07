import { ChevronDown, EyeOff, GraduationCap, Lock, Mail, User } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthFooter, AuthIntro } from './LoginPage.jsx'

function RegisterPage() {
  const navigate = useNavigate()

  function handleRegister(event) {
    event.preventDefault()
    navigate('/dashboard')
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
              <input defaultValue="Wijdane Lamsadi" type="text" placeholder="Entrez votre nom complet" />
            </span>
          </label>
          <label>
            Adresse e-mail
            <span className="input-shell">
              <Mail size={22} />
              <input defaultValue="wijdane@exemple.com" type="email" placeholder="Entrez votre e-mail" />
            </span>
          </label>
          <label>
            Mot de passe
            <span className="input-shell">
              <Lock size={22} />
              <input defaultValue="demo2026" type="password" placeholder="Créez un mot de passe" />
              <EyeOff size={20} />
            </span>
          </label>
          <div className="password-strength"><span>Force du mot de passe :</span><strong>Faible</strong></div>
          <label>
            Confirmer le mot de passe
            <span className="input-shell">
              <Lock size={22} />
              <input defaultValue="demo2026" type="password" placeholder="Confirmez votre mot de passe" />
              <EyeOff size={20} />
            </span>
          </label>
          <label>
            Niveau d'études
            <span className="input-shell">
              <GraduationCap size={22} />
              <input readOnly value="Sélectionnez votre niveau" />
              <ChevronDown size={20} />
            </span>
          </label>
          <label className="terms-row">
            <input type="checkbox" defaultChecked />
            J'accepte les Conditions d'utilisation et la Politique de confidentialité
          </label>
          <button className="primary-button auth-submit" type="submit">Créer mon compte</button>
          <div className="divider"><span>ou continuer avec</span></div>
          <button className="google-button" type="button">G Continuer avec Google</button>
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
