import { NavLink, useNavigate } from 'react-router-dom'
import {
  BarChart3,
  BookOpen,
  Brain,
  ClipboardCheck,
  Folder,
  Home,
  LogOut,
  MessageCircle,
  FileText,
  PieChart,
  Settings,
  ShieldCheck,
  Target,
  Users,
} from 'lucide-react'
import { navItems } from '../services/routes.js'
import { useAuth } from '../hooks/useAuth.js'

const icons = {
  BarChart3,
  BookOpen,
  ClipboardCheck,
  Folder,
  Home,
  MessageCircle,
  FileText,
  PieChart,
  Settings,
  ShieldCheck,
  Target,
  Users,
}

const adminItems = [
  { icon: 'ShieldCheck', path: '/admin', label: 'Tableau de bord admin' },
  { icon: 'Users', path: '/admin/users', label: 'Utilisateurs' },
  { icon: 'FileText', path: '/admin/courses', label: 'Cours & PDF' },
  { icon: 'PieChart', path: '/admin/statistics', label: 'Statistiques' },
  { icon: 'BarChart3', path: '/admin/rag', label: 'Gestion RAG' },
  { icon: 'ClipboardCheck', path: '/admin/audit', label: 'Journal admin' },
]

function Sidebar() {
  const navigate = useNavigate()
  const { isAdmin, logout } = useAuth()

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
        {navItems.map((item) => {
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
      <button className="logout-button" onClick={handleLogout} type="button">
        <LogOut size={22} />
        Se déconnecter
      </button>
    </aside>
  )
}

export default Sidebar
