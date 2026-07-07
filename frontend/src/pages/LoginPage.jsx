import { Brain, EyeOff, GraduationCap, Lock, Mail, MessageCircle, TrendingUp } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import studentIllustration from '../assets/student-illustration.jpg'

function LoginPage() {
  const navigate = useNavigate()

  function handleLogin(event) {
    event.preventDefault()
    navigate('/dashboard')
  }

  return (
    <div className="auth-page">
      <main className="auth-card">
        <AuthIntro />
        <form className="auth-panel" onSubmit={handleLogin}>
          <h1>Connexion</h1>
          <p>Bienvenue de retour ! Connectez-vous à votre compte.</p>

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
              <input defaultValue="demo2026" type="password" placeholder="Entrez votre mot de passe" />
              <EyeOff size={20} />
            </span>
          </label>
          <a className="form-link" href="#forgot">Mot de passe oublié ?</a>
          <button className="primary-button auth-submit" type="submit">Se connecter</button>
          <div className="divider"><span>ou continuer avec</span></div>
          <button className="google-button" type="button">G Continuer avec Google</button>
          <p className="auth-switch">
            Vous n'avez pas de compte ? <Link to="/register">S'inscrire</Link>
          </p>
        </form>
      </main>
      <AuthFooter />
    </div>
  )
}

export function AuthIntro() {
  return (
    <section className="auth-intro">
      <div className="auth-logo">
        <Brain size={42} />
        <strong>EduMentor <em>AI</em></strong>
      </div>
      <h2>Votre mentor intelligent pour <span>apprendre</span> mieux</h2>
      <p>Connectez-vous à votre espace et continuez votre apprentissage personnalisé avec l'IA à vos côtés.</p>
      <div className="auth-benefits">
        <AuthBenefit icon={GraduationCap} title="Apprenez plus vite" text="Des cours clairs et adaptés à votre niveau." />
        <AuthBenefit icon={TrendingUp} title="Suivez vos progrès" text="Visualisez vos statistiques et atteignez vos objectifs." />
        <AuthBenefit icon={MessageCircle} title="Obtenez de l'aide" text="Posez vos questions à notre chatbot IA 24/7." />
      </div>
      <img className="student-illustration" src={studentIllustration} alt="" />
    </section>
  )
}

function AuthBenefit({ icon: Icon, title, text }) {
  return (
    <div className="auth-benefit">
      <span><Icon size={30} /></span>
      <div>
        <strong>{title}</strong>
        <small>{text}</small>
      </div>
    </div>
  )
}

export function AuthFooter() {
  return (
    <footer className="auth-footer">
      <div className="auth-footer-brand">
        <div className="auth-logo compact">
          <Brain size={34} />
          <strong>EduMentor <em>AI</em></strong>
        </div>
        <p>Votre mentor intelligent pour un apprentissage plus efficace grâce à l'intelligence artificielle.</p>
        <small>© 2025 EduMentor AI. Tous droits réservés.</small>
      </div>
      <div>
        <strong>Produit</strong>
        <span>Fonctionnalités</span>
        <span>Tarifs</span>
        <span>FAQ</span>
        <span>Mises à jour</span>
      </div>
      <div>
        <strong>Ressources</strong>
        <span>Blog</span>
        <span>Guides</span>
        <span>Documentation</span>
        <span>Support</span>
      </div>
      <div>
        <strong>Entreprise</strong>
        <span>À propos</span>
        <span>Contact</span>
        <span>Carrières</span>
        <span>Mentions légales</span>
      </div>
      <div>
        <strong>Suivez-nous</strong>
        <div className="social-row">
          <span>f</span><span>x</span><span>in</span><span>◎</span>
        </div>
      </div>
    </footer>
  )
}

export default LoginPage
