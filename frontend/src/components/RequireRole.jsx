import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'

function RequireRole({ allowedRoles, children, fallback = '/login' }) {
  const { authReady, currentUser, loading, role } = useAuth()
  const location = useLocation()

  if (!authReady || loading) {
    return null
  }

  if (!currentUser) {
    return <Navigate replace state={{ from: location }} to="/login" />
  }

  if (!allowedRoles.includes(role)) {
    return <Navigate replace to={fallback} />
  }

  return children || <Outlet />
}

export default RequireRole
