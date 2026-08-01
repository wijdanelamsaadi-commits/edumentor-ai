import RequireRole from './RequireRole.jsx'

function ParentRoute({ children }) {
  return (
    <RequireRole allowedRoles={['parent', 'admin']} fallback="/login">
      {children}
    </RequireRole>
  )
}

export default ParentRoute
