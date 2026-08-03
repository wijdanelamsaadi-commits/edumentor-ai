import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  BarChart3,
  BookOpen,
  Brain,
  ClipboardCheck,
  Folder,
  GraduationCap,
  Home,
  LogOut,
  MessageCircle,
  FileText,
  PieChart,
  Settings,
  ShieldCheck,
  Tags,
  Target,
  Users,
} from 'lucide-react'
import { navItems } from '../services/routes.js'
import { useAuth } from '../hooks/useAuth.js'

const icons = {
  BarChart3,
  BookOpen,
  Brain,
  ClipboardCheck,
  Folder,
  GraduationCap,
  Home,
  MessageCircle,
  FileText,
  PieChart,
  Settings,
  ShieldCheck,
  Tags,
  Target,
  Users,
}

const adminItems = [
  { icon: 'ShieldCheck', path: '/admin', label: 'Tableau de bord admin' },
  { icon: 'Users', path: '/admin/users', label: 'Utilisateurs' },
  { icon: 'Tags', path: '/admin/subjects', label: 'Matieres' },
  { icon: 'Target', path: '/admin/diagnostic', label: 'Positionnement' },
  { icon: 'FileText', path: '/admin/courses', label: 'Cours & PDF' },
  { icon: 'PieChart', path: '/admin/statistics', label: 'Statistiques' },
  { icon: 'BarChart3', path: '/admin/rag', label: 'Gestion RAG' },
  { icon: 'ClipboardCheck', path: '/admin/audit', label: 'Journal admin' },
]

const professorItems = [
  { icon: 'GraduationCap', path: '/professor', label: 'Tableau de bord' },
  { icon: 'BookOpen', path: '/professor/courses', label: 'Mes cours' },
  { icon: 'FileText', path: '/professor/courses/automatic-import', label: 'Import automatique' },
  { icon: 'Users', path: '/professor/classrooms', label: 'Classes' },
  { icon: 'ClipboardCheck', path: '/professor/assessments', label: 'Évaluations' },
  { icon: 'Target', path: '/professor/remediation', label: 'Remediation' },
  { icon: 'BarChart3', path: '/professor/analytics', label: 'Statistiques' },
  { icon: 'Target', path: '/professor/profile', label: 'Profil' },
  { icon: 'Settings', path: '/professor/settings', label: 'Paramètres' },
]

const parentItems = [
  { icon: 'Home', path: '/parent/dashboard', label: 'Suivi parent' },
  { icon: 'Settings', path: '/parent/settings', label: 'Parametres' },
]

function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { isAdmin, isProfessor, isStudent, isParent, logout } = useAuth()
  const showRegionalHelp = isStudent && location.pathname.startsWith('/regional-exam-preparation')

  async function handleLogout() {
    try {
      await logout()
    } finally {
      navigate('/login')
    }
  }

  return (
    <aside className="sidebar">
      <div className="brand-mark">
        <span><Brain size={28} /></span>
        <div>
          <strong>EduMentor <em>AI</em></strong>
        </div>
      </div>
      <nav className="nav-list" aria-label="Navigation principale">
        {isStudent && navItems.map((item) => {
          const Icon = icons[item.icon]
          return (
            <NavLink
              className={({ isActive }) => {
                const suppressActive = item.label === 'Ressources' || item.label === 'Paramètres'
                return isActive && !suppressActive ? 'nav-item active' : 'nav-item'
              }}
              key={`${item.path}-${item.label}`}
              to={item.path}
            >
              <Icon size={22} />
              {item.label}
            </NavLink>
          )
        })}
        {isProfessor && !isAdmin && professorItems.map((item) => {
          const Icon = icons[item.icon]
          return (
            <NavLink
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
              key={`${item.path}-${item.label}`}
              to={item.path}
            >
              <Icon size={22} />
              {item.label}
            </NavLink>
          )
        })}
        {isParent && !isAdmin && parentItems.map((item) => {
          const Icon = icons[item.icon]
          return (
            <NavLink
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
              key={`${item.path}-${item.label}`}
              to={item.path}
            >
              <Icon size={22} />
              {item.label}
            </NavLink>
          )
        })}
        {isAdmin && adminItems.map((item) => {
          const Icon = icons[item.icon]
          return (
            <NavLink
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
              key={`${item.path}-${item.label}`}
              to={item.path}
            >
              <Icon size={22} />
              {item.label}
            </NavLink>
          )
        })}
      </nav>
      {showRegionalHelp && (
        <aside className="sidebar-help-card" aria-label="Aide personnalisée">
          <span><GraduationCap size={42} /></span>
          <h2>Besoin d'un coup de pouce ?</h2>
          <p>Discutez avec le Chatbot IA pour des conseils personnalisés.</p>
          <Link to="/chatbot">Ouvrir le Chatbot</Link>
        </aside>
      )}
      <button className="logout-button" onClick={handleLogout} type="button">
        <LogOut size={22} />
        Se déconnecter
      </button>
    </aside>
  )
}

export default Sidebar
