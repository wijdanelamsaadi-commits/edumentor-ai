import { Outlet } from 'react-router-dom'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'

function AppLayout() {
  return (
    <div className="app-shell app-shell-dashboard">
      <Sidebar />
      <section className="workspace">
        <Header />
        <main className="main-content">
          <Outlet />
        </main>
      </section>
    </div>
  )
}

export default AppLayout
