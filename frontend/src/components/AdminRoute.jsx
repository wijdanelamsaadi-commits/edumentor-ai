import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'

function AdminRoute({ children }) {
  const { authReady, currentUser, isAdmin, loading } = useAuth()
  const location = useLocation()

  if (!authReady || loading) {
    return null
  }

  if (!currentUser) {
    return <Navigate replace state={{ from: location }} to="/login" />
  }

  if (!isAdmin) {
    return <Navigate replace to="/dashboard" />
  }

  return children || <Outlet />
}

export default AdminRoute
