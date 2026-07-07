import { NavLink } from 'react-router-dom'
import {
  BarChart3,
  BookOpen,
  Brain,
  ClipboardCheck,
  Folder,
  Home,
  LogOut,
  MessageCircle,
  Settings,
  Target,
} from 'lucide-react'
import { navItems } from '../services/routes.js'

const icons = {
  BarChart3,
  BookOpen,
  ClipboardCheck,
  Folder,
  Home,
  MessageCircle,
  Settings,
  Target,
}

function Sidebar() {
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
      </nav>
      <button className="logout-button" type="button">
        <LogOut size={22} />
        Se déconnecter
      </button>
    </aside>
  )
}

export default Sidebar
