import RequireRole from './RequireRole.jsx'

function StudentRoute({ children }) {
  return (
    <RequireRole allowedRoles={['student', 'professor', 'admin']} fallback="/login">
      {children}
    </RequireRole>
  )
}

export default StudentRoute
