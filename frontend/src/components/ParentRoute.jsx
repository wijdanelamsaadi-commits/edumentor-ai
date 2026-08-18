import RequireRole from './RequireRole.jsx'

function ParentRoute({ children }) {
  return (
    <RequireRole allowedRoles={['parent']} fallback="/login">
      {children}
    </RequireRole>
  )
}

export default ParentRoute
