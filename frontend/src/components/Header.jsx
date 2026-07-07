import { Bell, ChevronDown } from 'lucide-react'
import avatarUrl from '../assets/learner-avatar.jpg'
import { useLearning } from '../hooks/useLearning.js'

function Header() {
  const { learner } = useLearning()

  return (
    <header className="topbar">
      <div className="topbar-spacer" />
      <button className="notification-button" type="button" aria-label="Notifications">
        <Bell size={24} />
        <span>3</span>
      </button>
      <div className="profile-pill">
        <img src={avatarUrl} alt="" />
        <strong>{learner.name}</strong>
        <ChevronDown size={18} />
      </div>
    </header>
  )
}

export default Header
