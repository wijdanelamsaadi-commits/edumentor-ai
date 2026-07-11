import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth.js'

function UserRoute({ children }) {
  const { authReady, currentUser, isAdmin, isUser, loading } = useAuth()
  const location = useLocation()

  if (!authReady || loading) {
    return null
  }

  if (!currentUser) {
    return <Navigate replace state={{ from: location }} to="/login" />
  }

  if (!isUser && !isAdmin) {
    return <Navigate replace to="/login" />
  }

  return children || <Outlet />
}

export default UserRoute
